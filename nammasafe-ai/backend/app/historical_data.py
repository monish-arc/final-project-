"""
Database access for the historical (previous-year) observation subsystem.

All rows read here are previous-year provenance data — every function returns
records carrying status="HISTORICAL" so they can never be mistaken for live
telemetry.  When no dataset has been imported the availability/baseline
responses degrade to status="NOT CONFIGURED".

The import itself lives in app.historical_importer (CLI wrapper in
scripts/import_historical_data.py); this module only reads.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import HISTORICAL_DATA_YEAR
from app.historical_baseline import compute_baseline
from app.kerala_districts import (
    KERALA_DISTRICTS,
    KERALA_STATE_NAME,
    district_code,
    district_name,
)
from app.models import HistoricalHazardObservation

HISTORICAL = "HISTORICAL"
NOT_CONFIGURED = "NOT CONFIGURED"
LIVE_NOT_CONFIGURED = "NOT CONFIGURED"


def _record_dict(row: HistoricalHazardObservation) -> Dict[str, Any]:
    return {
        "district_id": row.district_id,
        "district": row.district,
        "observation_date": row.observation_date.isoformat(),
        "hazard_type": row.hazard_type,
        "rainfall_mm": round(float(getattr(row, "rainfall_mm")), 2),
        "source": row.source,
        "source_reference": row.source_reference,
        "data_year": row.data_year,
        "status": HISTORICAL,
    }


def count_records(db: Session) -> int:
    return int(db.query(func.count(HistoricalHazardObservation.id)).scalar() or 0)


def last_import_at(db: Session) -> Optional[str]:
    value = db.query(func.max(HistoricalHazardObservation.created_at)).scalar()
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def dataset_years(db: Session) -> List[int]:
    values = (
        db.query(HistoricalHazardObservation.data_year)
        .distinct()
        .order_by(HistoricalHazardObservation.data_year.desc())
        .all()
    )
    return [v[0] for v in values]


def district_records(
    db: Session,
    district_id: int,
    data_year: Optional[int] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    query = db.query(HistoricalHazardObservation).filter(
        HistoricalHazardObservation.district_id == district_id
    )
    if data_year is not None:
        query = query.filter(HistoricalHazardObservation.data_year == data_year)
    query = query.order_by(
        HistoricalHazardObservation.observation_date.desc(),
        HistoricalHazardObservation.data_year.desc(),
    )
    if limit:
        query = query.limit(limit)
    return [_record_dict(row) for row in query.all()]


def district_records_for_baseline(
    db: Session,
    district_id: int,
    data_year: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Raw records hydrated for compute_baseline (minimal fields, no labels)."""
    year = data_year if data_year is not None else HISTORICAL_DATA_YEAR
    query = db.query(HistoricalHazardObservation).filter(
        HistoricalHazardObservation.district_id == district_id,
        HistoricalHazardObservation.data_year == year,
    )
    return [
        {
            "rainfall_mm": float(getattr(row, "rainfall_mm")),
            "observation_date": row.observation_date,
        }
        for row in query.all()
    ]


def district_baseline(
    db: Session,
    district_id: int,
    data_year: Optional[int] = None,
) -> Dict[str, Any]:
    """Full baseline for one district; district metadata + status attached."""
    code = int(district_id)
    name = district_name(code) or "Unknown"
    year = data_year if data_year is not None else HISTORICAL_DATA_YEAR

    if district_code(code) is None:
        return {
            "district_id": code,
            "district": name,
            "data_year": year,
            "status": NOT_CONFIGURED,
            "live_data_status": LIVE_NOT_CONFIGURED,
            "reason": f"Unknown district code {code}. Valid Kerala codes are 554-567.",
        }

    records = district_records_for_baseline(db, code, year)
    baseline = compute_baseline(records, year)

    sources = (
        db.query(HistoricalHazardObservation.source)
        .filter(
            HistoricalHazardObservation.district_id == code,
            HistoricalHazardObservation.data_year == year,
        )
        .distinct()
        .all()
    )
    source_refs = (
        db.query(HistoricalHazardObservation.source_reference)
        .filter(
            HistoricalHazardObservation.district_id == code,
            HistoricalHazardObservation.data_year == year,
        )
        .distinct()
        .all()
    )

    baseline.update(
        {
            "district_id": code,
            "district": name,
            "source": "; ".join(s[0] for s in sources) if sources else None,
            "source_reference": "; ".join(r[0] for r in source_refs[:5]) or None,
            "live_data_status": LIVE_NOT_CONFIGURED,
        }
    )
    return baseline


def district_summary(db: Session, district_id: int) -> Dict[str, Any]:
    """Lightweight per-district summary used by /api/historical/kerala."""
    code = int(district_id)
    name = district_name(code) or "Unknown"
    baseline = district_baseline(db, code)
    observations = district_records(db, code, limit=3)
    return {
        "district_id": code,
        "district": name,
        "data_year": baseline.get("data_year"),
        "observation_count": baseline.get("observation_count", 0),
        "average_rainfall_mm": baseline.get("average_rainfall_mm", 0.0),
        "max_rainfall_mm": baseline.get("max_rainfall_mm", 0.0),
        "source": baseline.get("source"),
        "status": baseline.get("status", NOT_CONFIGURED),
        "quality_grade": baseline.get("quality", {}).get("grade") if baseline.get("quality") else None,
        "latest_observations": observations,
    }


def all_district_summaries(db: Session) -> List[Dict[str, Any]]:
    return [
        {**district_summary(db, code), "district_id": code, "district": name}
        for code, name in KERALA_DISTRICTS
    ]


def availability(db: Session) -> Dict[str, Any]:
    total = count_records(db)
    years = dataset_years(db)
    default_year = HISTORICAL_DATA_YEAR
    districts = []
    for code, name in KERALA_DISTRICTS:
        n = int(
            db.query(func.count(HistoricalHazardObservation.id))
            .filter(HistoricalHazardObservation.district_id == code)
            .scalar()
            or 0
        )
        districts.append({"code": code, "name": name, "records": n})

    return {
        "state": {"code": 32, "name": KERALA_STATE_NAME},
        "dataset_year": default_year,
        "years_available": years,
        "total_records": total,
        "districts": districts,
        "last_import_at": last_import_at(db),
        "live_data_status": LIVE_NOT_CONFIGURED,
        "status": HISTORICAL if total > 0 else NOT_CONFIGURED,
    }