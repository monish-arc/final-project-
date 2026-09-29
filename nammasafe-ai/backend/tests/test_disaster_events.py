"""
Disaster-events provenance API: DB-backed list/near queries + endpoint contract.

The table is real (SQLAlchemy) here — event rows are the kind seeded by
scripts/seed_disaster_events.py. Contract: every payload is labelled HISTORICAL
and events are never fabricated.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.disaster_events import get_disaster_events, get_disaster_events_near
from app.main import app
from app.models import Base, DisasterEvent

JOSHIMATH = (30.5574, 79.5658)


@pytest.fixture()
def ctx():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db = Session()
    db.add_all([
        DisasterEvent(
            name="Chamoli glacier burst", hazard_type="LANDSLIDE",
            event_date=date(2021, 2, 7), state="Uttarakhand", district="Chamoli",
            latitude=30.4340, longitude=79.7250, severity_level="EXTREME",
            affected_population=10000, source="NDMA", source_reference="https://ndma.gov.in",
            data_status="HISTORICAL",
        ),
        DisasterEvent(
            name="Kedarnath floods", hazard_type="FLOOD",
            event_date=date(2013, 6, 16), state="Uttarakhand", district="Rudraprayag",
            latitude=30.7350, longitude=79.0669, severity_level="EXTREME",
            affected_population=110000, source="NDMA", source_reference="https://ndma.gov.in",
            data_status="HISTORICAL",
        ),
        DisasterEvent(
            name="Mumbai great floods", hazard_type="FLOOD",
            event_date=date(2005, 7, 26), state="Maharashtra", district="Mumbai",
            latitude=19.0760, longitude=72.8777, severity_level="EXTREME",
            source="IMD", source_reference="https://imd.gov.in",
            data_status="HISTORICAL",
        ),
    ])
    db.commit()

    def _override():
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as client:
        yield {"client": client, "db": db}
    app.dependency_overrides.clear()


def _auth_headers(client):
    res = client.post("/api/auth/login", json={"username_or_email": "citizen", "password": "citizen123",
        "state_id": "uk", "district_id": "chamoli", "sub_district_id": "joshimath", "area_id": "joshimath-central"})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_disaster_events_require_auth(ctx):
    assert ctx["client"].get("/api/disaster-events").status_code == 401


def test_list_all_events(ctx):
    client = ctx["client"]
    response = client.get("/api/disaster-events", headers=_auth_headers(client))
    assert response.status_code == 200
    data = response.json()
    assert data["data_status"] == "HISTORICAL"
    assert data["total"] == 3
    assert all(event["source_reference"] for event in data["events"])


def test_filter_by_state(ctx):
    client = ctx["client"]
    response = client.get("/api/disaster-events?state=Uttarakhand", headers=_auth_headers(client))
    assert response.json()["total"] == 2


def test_near_within_radius(ctx):
    client = ctx["client"]
    response = client.get("/api/disaster-events/near?lat=30.45&lng=79.7&radius=60", headers=_auth_headers(client))
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["events"][0]["name"] == "Chamoli glacier burst"
    assert data["events"][0]["distance_km"] is not None


def test_get_disaster_events_service(ctx):
    db = ctx["db"]
    result = get_disaster_events(db, state="Maharashtra")
    assert result["total"] == 1
    near = get_disaster_events_near(db, *JOSHIMATH, radius_km=200)
    assert near["total"] == 2


def test_seed_script_dry_run():
    """The curated seed accepts --dry-run and validates every row's source."""
    import subprocess
    import sys
    result = subprocess.run(
        [sys.executable, "scripts/seed_disaster_events.py", "--dry-run"],
        capture_output=True, text=True, cwd=".",
    )
    assert result.returncode == 0, result.stderr
    assert "nothing was written" in result.stdout.lower()