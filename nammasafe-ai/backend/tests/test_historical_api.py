"""
End-to-end tests for the /api/historical/* endpoints.

Uses the real FastAPI app with the get_db dependency overridden to an in-memory
SQLite database so assertions run against a real table (not mocks).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import HISTORICAL_DATA_YEAR
from app.database import get_db
from app.historical_importer import import_csv_text
from app.main import app
from app.models import Base

YEAR = HISTORICAL_DATA_YEAR


@pytest.fixture()
def ctx():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def _override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as test_client:
        yield {"client": test_client, "session_factory": Session}
    app.dependency_overrides.clear()


def _import(ctx, rows):
    csv_text = "district,observation_date,rainfall_mm,source,source_reference,data_year\n" + rows
    db = ctx["session_factory"]()
    try:
        result = import_csv_text(db, csv_text)
    finally:
        db.close()
    assert result.success, result.issues
    return result


def _c(ctx):
    return ctx["client"]


def _rows(district="Wayanad", ref="ref-w", extra=""):
    return "\n".join(
        f"{district},{YEAR}-01-{d:02d},{mm},{extra}IMD,{ref}-{d},{YEAR}"
        for d, mm in [(1, 100), (2, 110), (3, 90)]
    )


def test_availability_empty_is_not_configured(ctx):
    res = _c(ctx).get("/api/historical/availability")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "NOT CONFIGURED"
    assert data["total_records"] == 0
    assert data["state"]["code"] == 32
    assert data["live_data_status"] == "NOT CONFIGURED"
    district_codes = {d["code"] for d in data["districts"]}
    assert 567 in district_codes
    assert district_codes == set(range(554, 568))


def test_availability_after_import_is_historical(ctx):
    _import(ctx, _rows())
    data = _c(ctx).get("/api/historical/availability").json()
    assert data["status"] == "HISTORICAL"
    assert data["total_records"] == 3
    assert YEAR in data["years_available"]
    wayanad = next(d for d in data["districts"] if d["code"] == 567)
    assert wayanad["records"] == 3


def test_kerala_district_summaries_present_all_14(ctx):
    data = _c(ctx).get("/api/historical/kerala").json()
    assert len(data) == 14
    assert {d["district_id"] for d in data} == set(range(554, 568))


def test_kerala_summary_marks_district_historical(ctx):
    _import(ctx, _rows())
    data = _c(ctx).get("/api/historical/kerala").json()
    wayanad = next(d for d in data if d["district_id"] == 567)
    assert wayanad["status"] == "HISTORICAL"
    assert wayanad["observation_count"] == 3
    assert wayanad["average_rainfall_mm"] == 100
    assert wayanad["quality_grade"] in ("GOOD", "LIMITED", "INSUFFICIENT")


def test_district_endpoint_returns_latest_observations(ctx):
    _import(ctx, _rows())
    data = _c(ctx).get("/api/historical/kerala/Wayanad").json()
    assert data["district_id"] == 567
    assert data["observation_count"] == 3
    assert len(data["latest_observations"]) == 3
    assert data["latest_observations"][0]["status"] == "HISTORICAL"
    assert data["latest_observations"][0]["rainfall_mm"] == 90  # desc date order


def test_district_endpoint_accepts_lgd_code(ctx):
    _import(ctx, _rows())
    data = _c(ctx).get("/api/historical/kerala/567").json()
    assert data["district"] == "Wayanad"


def test_unknown_district_is_404(ctx):
    res = _c(ctx).get("/api/historical/kerala/999")
    assert res.status_code == 404
    res = _c(ctx).get("/api/historical/kerala/Delhi")
    assert res.status_code == 404


def test_baseline_empty_is_not_configured(ctx):
    data = _c(ctx).get("/api/historical/kerala/Wayanad/baseline").json()
    assert data["status"] == "NOT CONFIGURED"
    assert data["observation_count"] == 0
    assert data["quality"]["grade"] == "INSUFFICIENT"


def test_baseline_populated_after_import(ctx):
    _import(ctx, _rows())
    data = _c(ctx).get("/api/historical/kerala/Wayanad/baseline").json()
    assert data["status"] == "HISTORICAL"
    assert data["average_rainfall_mm"] == 100.0
    assert data["total_rainfall_mm"] == 300.0
    assert data["date_range"]["first"] == f"{YEAR}-01-01"
    assert data["source"] == "IMD"
    assert data["live_data_status"] == "NOT CONFIGURED"


def test_compare_requires_rainfall_and_date(ctx):
    client = _c(ctx)
    res = client.get("/api/historical/kerala/Wayanad/compare")
    assert res.status_code == 422
    res = client.get("/api/historical/kerala/Wayanad/compare?rainfall_mm=120")
    assert res.status_code == 422
    res = client.get("/api/historical/kerala/Wayanad/compare?observation_date=2025-01-05")
    assert res.status_code == 422


def test_compare_with_empty_baseline_is_not_configured(ctx):
    data = _c(ctx).get(
        "/api/historical/kerala/Wayanad/compare?rainfall_mm=120&observation_date=2025-01-05"
    ).json()
    assert data["live_data_status"] == "NOT CONFIGURED"
    assert data["baseline_status"] == "NOT CONFIGURED"
    assert data["severity"] == "NORMAL"


def test_compare_computes_anomaly_against_historical(ctx):
    _import(ctx, _rows())
    data = _c(ctx).get(
        "/api/historical/kerala/Wayanad/compare?rainfall_mm=150&observation_date=2025-01-05"
    ).json()
    assert data["baseline_average"] == 100.0
    assert data["anomaly_mm"] == 50.0
    assert data["percent_difference"] == 50.0
    assert data["baseline_status"] == "HISTORICAL"
    assert data["live_data_status"] == "NOT CONFIGURED"


def test_import_roundtrip_idempotency_via_api_db(ctx):
    first = _import(ctx, _rows())
    assert first.inserted == 3
    second = _import(ctx, _rows())
    assert second.inserted == 0
    assert second.skipped_duplicate == 3