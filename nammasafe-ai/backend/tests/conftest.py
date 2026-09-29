"""Shared fixtures for SAFE_MOVE_AI backend tests."""

import os
from datetime import date

# The production default disables live-weather fetching (WEATHER_LIVE_ENABLED=off)
# so a fresh deployment never calls live APIs unsolicited. The existing unit
# tests exercise the live provider chain against mocked upstream responses, so
# they opt in here BEFORE app.config is imported.
os.environ.setdefault("WEATHER_LIVE_ENABLED", "on")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models import Base, DisasterEvent


@pytest.fixture()
def db_ctx():
    """App with get_db overridden to a seeded in-memory SQLite database."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    session = Session()
    session.add(DisasterEvent(
        name="Chamoli glacier burst", hazard_type="LANDSLIDE",
        event_date=date(2021, 2, 7), state="Uttarakhand", district="Chamoli",
        latitude=30.4340, longitude=79.7250, severity_level="EXTREME",
        affected_population=10000, source="NDMA", source_reference="https://ndma.gov.in",
        data_status="HISTORICAL",
    ))
    session.commit()
    session.close()

    def _override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as client:
        yield {"client": client, "session_factory": Session}
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_headers(db_ctx):
    client = db_ctx["client"]
    res = client.post("/api/auth/login", json={
        "username_or_email": "citizen",
        "password": "citizen123",
        "state_id": "uk",
        "district_id": "chamoli",
        "sub_district_id": "joshimath",
        "area_id": "joshimath-central",
    })
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture()
def officer_headers(db_ctx):
    """A district_officer session — used by the officer-side weather/rainfall
    assertions. Citizens also hold weather.history.read; the officer fixture is
    kept where the assertions are written against an officer token."""
    client = db_ctx["client"]
    res = client.post("/api/auth/login", json={
        "username_or_email": "officer",
        "password": "officer123",
        "state_id": "uk",
        "district_id": "chamoli",
        "sub_district_id": "joshimath",
        "area_id": "joshimath-central",
    })
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}