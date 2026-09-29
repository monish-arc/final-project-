"""
Testable core of the historical-data CSV importer.

The CLI wrapper (backend/scripts/import_historical_data.py) only parses
arguments and connects the pieces; all validation logic lives here so it can be
unit-tested with an in-memory SQLite session.

Design guarantees
-----------------
- Districts are validated against the single source of truth
  (app.kerala_districts) — a typo'd district is a hard error, never a guess.
- observation_date must be a real YYYY-MM-DD and must fall inside data_year.
- rainfall_mm must be a finite number >= 0 and <= HISTORICAL_MAX_RAINFALL_MM.
- hazard_type must be from the documented vocabulary.
- Idempotent re-runs: rows already in the DB (same district + date + year +
  source_reference) are skipped, so importing the same dataset twice is a no-op.
- --dry-run reports what *would* be inserted without touching the DB.
- Exit is non-zero if any row was rejected.
"""

import csv
import io
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, IO, List, Optional, Union

from sqlalchemy.orm import Session

from app.config import HISTORICAL_MAX_RAINFALL_MM
from app.kerala_districts import resolve_district
from app.models import HistoricalHazardObservation

EXPECTED_COLUMNS = {
    "district",
    "observation_date",
    "rainfall_mm",
    "source",
    "source_reference",
    "data_year",
}

KNOWN_HAZARD_TYPES = {
    "rainfall",
    "flood",
    "landslide",
    "extreme rainfall",
    "cyclone",
    "other",
}


@dataclass
class ImportRecord:
    district_id: int
    district: str
    observation_date: date
    hazard_type: str
    rainfall_mm: float
    source: str
    source_reference: str
    data_year: int


@dataclass
class ImportIssue:
    row_number: int
    reason: str


@dataclass
class DistrictReport:
    district: str
    inserted: int = 0
    skipped_duplicate: int = 0


@dataclass
class ImportResult:
    inserted: int = 0
    skipped_duplicate: int = 0
    rejected: int = 0
    raw: int = 0
    issues: List[ImportIssue] = field(default_factory=list)
    district_reports: List[DistrictReport] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.rejected == 0


def parse_observation_date(value: str) -> Optional[date]:
    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _is_number(value: Any) -> bool:
    try:
        float(str(value).strip())
        return True
    except (TypeError, ValueError):
        return False


def _parse_row(row_number: int, raw: Dict[str, Any], expected_year: Optional[int]) -> "Union[ImportRecord, ImportIssue]":
    """Validate a single CSV row -> (record, None) or (None, issue)."""
    missing = EXPECTED_COLUMNS - set(raw)
    if missing:
        return ImportIssue(row_number, f"Missing required column(s): {sorted(missing)}")

    district = str(raw.get("district", "")).strip()
    code, name = resolve_district(district)
    if code is None or name is None:
        return ImportIssue(row_number, f"Unknown district '{district}' (expected a Kerala LGD code or name)")

    obs_date = parse_observation_date(str(raw.get("observation_date", "")).strip())
    if obs_date is None:
        return ImportIssue(row_number, f"Invalid observation_date '{raw.get('observation_date')}' (expected YYYY-MM-DD)")

    rainfall = raw.get("rainfall_mm")
    if not _is_number(rainfall):
        return ImportIssue(row_number, f"rainfall_mm '{rainfall}' is not numeric")
    rainfall_value = float(str(rainfall).strip())
    if math.isnan(rainfall_value) or math.isinf(rainfall_value) or rainfall_value < 0 or rainfall_value > HISTORICAL_MAX_RAINFALL_MM:
        return ImportIssue(row_number, f"rainfall_mm {rainfall_value} outside [0, {HISTORICAL_MAX_RAINFALL_MM}]")

    source = str(raw.get("source", "")).strip()
    if not source:
        return ImportIssue(row_number, "source must not be empty")

    source_reference = str(raw.get("source_reference", "")).strip()

    try:
        data_year = int(str(raw.get("data_year", "")).strip())
    except ValueError:
        return ImportIssue(row_number, f"data_year '{raw.get('data_year')}' is not an integer")
    if expected_year is not None and data_year != expected_year:
        return ImportIssue(row_number, f"data_year {data_year} does not match expected dataset year {expected_year}")
    if obs_date.year != data_year:
        return ImportIssue(row_number, f"observation_date {obs_date} is not within data_year {data_year}")

    hazard_type = str(raw.get("hazard_type", "rainfall")).strip().lower()
    if hazard_type not in KNOWN_HAZARD_TYPES:
        return ImportIssue(row_number, f"hazard_type '{hazard_type}' not in {sorted(KNOWN_HAZARD_TYPES)}")

    return ImportRecord(
        district_id=code,
        district=name,
        observation_date=obs_date,
        hazard_type=hazard_type,
        rainfall_mm=round(rainfall_value, 2),
        source=source,
        source_reference=source_reference,
        data_year=data_year,
    )


def import_csv_text(db: Session, text: str, expected_year: Optional[int] = None, dry_run: bool = False) -> ImportResult:
    """Import a CSV *string*. Used by the CLI wrapper and unit tests alike."""
    return import_csv_file(db, io.StringIO(text), expected_year=expected_year, dry_run=dry_run)


def import_csv_file(
    db: Session,
    handle: IO[str],
    expected_year: Optional[int] = None,
    dry_run: bool = False,
) -> ImportResult:
    result = ImportResult()
    rows = list(csv.DictReader(handle))
    result.raw = len(rows)

    district_reports: Dict[str, DistrictReport] = {}
    existing_keys: set = _load_existing_keys(db)
    seen_this_file: set = set()

    for idx, raw in enumerate(rows, start=2):  # row 1 is the header
        parsed = _parse_row(idx, raw, expected_year)
        if isinstance(parsed, ImportIssue):
            result.rejected += 1
            result.issues.append(parsed)
            continue

        record = parsed
        key = (record.district_id, record.observation_date, record.data_year, record.source_reference)
        if key in existing_keys or key in seen_this_file:
            result.skipped_duplicate += 1
            _touch_report(district_reports, record.district).skipped_duplicate += 1
            continue
        seen_this_file.add(key)
        _touch_report(district_reports, record.district).inserted += 1

        if not dry_run:
            db.add(HistoricalHazardObservation(
                district_id=record.district_id,
                district=record.district,
                observation_date=record.observation_date,
                hazard_type=record.hazard_type,
                rainfall_mm=record.rainfall_mm,
                source=record.source,
                source_reference=record.source_reference,
                data_year=record.data_year,
            ))
            existing_keys.add(key)
        result.inserted += 1

    if not dry_run:
        db.commit()

    result.district_reports = sorted(district_reports.values(), key=lambda r: r.district)
    return result


def _load_existing_keys(db: Session) -> set:
    rows = db.query(
        HistoricalHazardObservation.district_id,
        HistoricalHazardObservation.observation_date,
        HistoricalHazardObservation.data_year,
        HistoricalHazardObservation.source_reference,
    ).all()
    return set(rows)


def _touch_report(reports: Dict[str, DistrictReport], district: str) -> DistrictReport:
    if district not in reports:
        reports[district] = DistrictReport(district=district)
    return reports[district]