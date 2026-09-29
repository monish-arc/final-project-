"""
Unit tests for the historical-data importer + baseline math.

Runs against an in-memory SQLite database so nothing leaks into the real DB.
"""

import calendar
import math

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import HISTORICAL_DATA_YEAR, HISTORICAL_MAX_RAINFALL_MM
from app.historical_baseline import (
    compare_observation,
    compute_baseline,
    grade_quality,
    percentile,
    severity_from_ratio,
    size_bucket,
)
from app.historical_importer import import_csv_text
from app.models import Base, HistoricalHazardObservation

VALID_YEAR = HISTORICAL_DATA_YEAR
MAX_MM = HISTORICAL_MAX_RAINFALL_MM


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _valid_row(
    district="Wayanad",
    day="15",
    month="06",
    rainfall="183.5",
    source="IMD Gridded",
    reference="https://imd.example/wayanad-2025",
    data_year=VALID_YEAR,
):
    return (
        "district,observation_date,rainfall_mm,source,source_reference,data_year\n"
        f"{district},{VALID_YEAR}-{month}-{day},{rainfall},{source},{reference},{data_year}\n"
    )


# -------------------- Import validation --------------------

def test_imports_valid_row(db):
    result = import_csv_text(db, _valid_row())
    assert result.success
    assert result.inserted == 1
    assert result.rejected == 0
    row = db.query(HistoricalHazardObservation).first()
    assert row.district == "Wayanad"
    assert row.district_id == 567
    assert row.rainfall_mm == 183.5
    assert row.data_year == VALID_YEAR
    assert row.hazard_type == "rainfall"
    assert row.source_reference == "https://imd.example/wayanad-2025"


@pytest.mark.parametrize("district", ["567", "555", "wayanad", "Thiruvananthapuram", "556"])
def test_import_accepts_lgd_code_and_name_forms(db, district):
    year = VALID_YEAR
    csv_text = (
        "district,observation_date,rainfall_mm,source,source_reference,data_year\n"
        f"{district},{year}-03-10,50,IMD,ref-1,{year}\n"
    )
    result = import_csv_text(db, csv_text)
    assert result.success
    assert result.inserted == 1


@pytest.mark.parametrize("district", ["Delhi", "999", "", "Keralaa", "Trivandrum"])
def test_import_rejects_unknown_district(db, district):
    year = VALID_YEAR
    csv_text = (
        "district,observation_date,rainfall_mm,source,source_reference,data_year\n"
        f"{district},{year}-03-10,50,IMD,ref-1,{year}\n"
    )
    result = import_csv_text(db, csv_text)
    assert not result.success
    assert result.rejected == 1
    assert "district" in result.issues[0].reason.lower()


@pytest.mark.parametrize(
    "bad_date",
    ["2025-02-30", "2025/03/10", "not-a-date", "", "15-06-2025", "03-10-2025"],
)
def test_import_rejects_invalid_dates(db, bad_date):
    year = VALID_YEAR
    csv_text = (
        "district,observation_date,rainfall_mm,source,source_reference,data_year\n"
        f"Wayanad,{bad_date},50,IMD,ref-1,{year}\n"
    )
    result = import_csv_text(db, csv_text)
    assert not result.success
    assert result.rejected == 1


@pytest.mark.parametrize("mismatch_year", [VALID_YEAR + 1, VALID_YEAR - 1])
def test_import_rejects_data_year_different_from_observation_date_year(db, mismatch_year):
    csv_text = (
        "district,observation_date,rainfall_mm,source,source_reference,data_year\n"
        f"Wayanad,{VALID_YEAR}-03-10,50,IMD,ref-1,{mismatch_year}\n"
    )
    result = import_csv_text(db, csv_text)
    assert not result.success
    assert result.rejected == 1


def test_import_rejects_expected_year_conflict_when_supplied(db):
    csv_text = (
        "district,observation_date,rainfall_mm,source,source_reference,data_year\n"
        f"Wayanad,{VALID_YEAR}-03-10,50,IMD,ref-1,{VALID_YEAR}\n"
    )
    result = import_csv_text(db, csv_text, expected_year=VALID_YEAR - 1)
    assert not result.success
    assert result.rejected == 1


@pytest.mark.parametrize("bad_rain", ["-5", "abc", "1e500", f"{MAX_MM + 1}", ""])
def test_import_rejects_bad_rainfall_values(db, bad_rain):
    year = VALID_YEAR
    csv_text = (
        "district,observation_date,rainfall_mm,source,source_reference,data_year\n"
        f"Wayanad,{year}-03-10,{bad_rain},IMD,ref-1,{year}\n"
    )
    result = import_csv_text(db, csv_text)
    assert not result.success
    assert result.rejected == 1


def test_import_rejects_missing_required_columns(db):
    year = VALID_YEAR
    csv_text = (
        "district,observation_date,rainfall_mm,data_year\n"
        f"Wayanad,{year}-03-10,50,{year}\n"
    )
    result = import_csv_text(db, csv_text)
    assert not result.success
    assert result.rejected == 1
    assert "column" in result.issues[0].reason.lower()


def test_import_rejects_unknown_hazard_type(db):
    year = VALID_YEAR
    csv_text = (
        "district,observation_date,rainfall_mm,source,source_reference,data_year,hazard_type\n"
        f"Wayanad,{year}-03-10,50,IMD,ref-1,{year},tornado\n"
    )
    result = import_csv_text(db, csv_text)
    assert not result.success
    assert result.rejected == 1
    assert "hazard_type" in result.issues[0].reason.lower()


def test_import_is_idempotent(db):
    csv_text = _valid_row()
    first = import_csv_text(db, csv_text)
    second = import_csv_text(db, csv_text)
    assert first.inserted == 1
    assert second.inserted == 0
    assert second.skipped_duplicate == 1
    assert db.query(HistoricalHazardObservation).count() == 1


def test_import_deduplicates_within_single_file(db):
    csv_text = _valid_row() + _valid_row()
    result = import_csv_text(db, csv_text)
    assert result.inserted == 1
    assert db.query(HistoricalHazardObservation).count() == 1


def test_import_dry_run_writes_nothing(db):
    result = import_csv_text(db, _valid_row(), dry_run=True)
    assert result.inserted == 1
    assert db.query(HistoricalHazardObservation).count() == 0


def test_import_per_district_report(db):
    csv_text = (
        "district,observation_date,rainfall_mm,source,source_reference,data_year\n"
        f"Wayanad,{VALID_YEAR}-01-01,50,IMD,ref-w-1,{VALID_YEAR}\n"
        f"Ernakulam,{VALID_YEAR}-01-02,50,IMD,ref-e-1,{VALID_YEAR}\n"
        f"Ernakulam,{VALID_YEAR}-01-02,60,IMD,ref-e-1,{VALID_YEAR}\n"
    )
    result = import_csv_text(db, csv_text)
    assert result.inserted == 2
    assert len(result.district_reports) == 2
    by_name = {r.district: r for r in result.district_reports}
    assert by_name["Wayanad"].inserted == 1
    assert by_name["Ernakulam"].inserted == 1
    assert by_name["Ernakulam"].skipped_duplicate == 1


# -------------------- Baseline math --------------------

def test_baseline_empty_is_not_configured():
    baseline = compute_baseline([], VALID_YEAR)
    assert baseline["status"] == "NOT CONFIGURED"
    assert baseline["observation_count"] == 0
    assert baseline["quality"]["grade"] == "INSUFFICIENT"
    for key in ("median_rainfall_mm", "p90_rainfall_mm", "p95_rainfall_mm"):
        assert baseline[key] is None


def test_baseline_totals_and_range():
    records = [
        {"rainfall_mm": 10, "observation_date": f"{VALID_YEAR}-01-01"},
        {"rainfall_mm": 30, "observation_date": f"{VALID_YEAR}-01-02"},
        {"rainfall_mm": 20, "observation_date": f"{VALID_YEAR}-01-03"},
    ]
    b = compute_baseline(records, VALID_YEAR)
    assert b["status"] == "HISTORICAL"
    assert b["total_rainfall_mm"] == 60
    assert b["average_rainfall_mm"] == 20
    assert b["max_rainfall_mm"] == 30
    assert b["min_rainfall_mm"] == 10
    assert b["date_range"] == {"first": f"{VALID_YEAR}-01-01", "last": f"{VALID_YEAR}-01-03"}
    assert b["median_rainfall_mm"] is None  # below percentile threshold


def test_baseline_percentiles_appear_after_threshold():
    records = [
        {"rainfall_mm": float(i), "observation_date": f"{VALID_YEAR}-%02d-%02d" % (1 + i // 28, 1 + i % 28)}
        for i in range(30)
    ]
    b = compute_baseline(records, VALID_YEAR)
    assert b["median_rainfall_mm"] is not None
    assert b["p90_rainfall_mm"] is not None
    assert b["p95_rainfall_mm"] is not None
    assert b["p95_rainfall_mm"] >= b["p90_rainfall_mm"] >= b["median_rainfall_mm"]


def test_percentile_linear_interpolation():
    assert percentile([1, 2, 3, 4], 50) == 2.5


def test_grade_quality_boundaries():
    assert grade_quality(0, VALID_YEAR)["grade"] == "INSUFFICIENT"
    good_days = math.ceil(365 * 0.90)
    assert grade_quality(good_days, VALID_YEAR)["grade"] == "GOOD"
    limited_days = int(365 * 0.60)
    assert grade_quality(limited_days, VALID_YEAR)["grade"] == "LIMITED"
    assert grade_quality(5, VALID_YEAR)["grade"] == "INSUFFICIENT"


def test_size_bucket_consistency():
    assert size_bucket(0) == "INSUFFICIENT"
    assert size_bucket(366, 2024) == "GOOD"  # leap year


def test_severity_thresholds():
    assert severity_from_ratio(2.5) == "EXTREME"
    assert severity_from_ratio(1.6) == "HIGH"
    assert severity_from_ratio(1.3) == "ELEVATED"
    assert severity_from_ratio(1.1) == "NORMAL"
    assert severity_from_ratio(None) == "NORMAL"


def test_compare_observation_with_baseline():
    baseline = compute_baseline(
        [{"rainfall_mm": 100, "observation_date": f"{VALID_YEAR}-01-01"}], VALID_YEAR
    )
    result = compare_observation(150, baseline)
    assert result["baseline_average"] == 100
    assert result["anomaly_mm"] == 50
    assert result["percent_difference"] == 50
    assert result["severity"] == "HIGH"  # 1.5x the average -> HIGH threshold
    assert result["live_data_status"] == "NOT CONFIGURED"


def test_compare_observation_with_empty_baseline_is_not_configured():
    baseline = compute_baseline([], VALID_YEAR)
    result = compare_observation(150, baseline)
    assert result["live_data_status"] == "NOT CONFIGURED"
    assert result["baseline_average"] is None
    assert result["baseline_status"] == "NOT CONFIGURED"