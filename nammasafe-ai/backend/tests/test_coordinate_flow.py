"""
Coordinate-flow honesty contract for six distinct India locations.

Locks the "coordinates/region are the single source of truth" rule: a request
for one location must never observe data curated for another location, nothing
is ever fabricated, and the former Chamoli pilot is treated with the same
honesty as every other district.

The hazard-events surface in this codebase is `/api/disaster-events`
(+ `/api/analytics/hazards`); it is exercised here for every location.
"""

import pytest

from fastapi.testclient import TestClient

from app.main import app
from app.config import PILOT_STATE, PILOT_DISTRICT
from app.flood_forecast import get_flood_forecasts


client = TestClient(app)

LOCATIONS = [
    ("Tamil Nadu", "Chennai"),
    ("Tamil Nadu", "Cuddalore"),
    ("Kerala", "Thrissur"),
    ("Maharashtra", "Raigad"),
    ("Odisha", "Puri"),
    ("Uttarakhand", "Chamoli"),
]


def _admin_headers(db_ctx) -> dict:
    test_client = db_ctx["client"]
    res = test_client.post(
        "/api/auth/login",
        json={"username_or_email": "admin", "password": "admin123"},
    )
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _effective_state(item: dict) -> str:
    return (item.get("state") or PILOT_STATE).lower()


def _effective_district(item: dict) -> str:
    return (item.get("district") or PILOT_DISTRICT).lower()


@pytest.mark.parametrize("state,district", LOCATIONS)
def test_dashboard_summary_never_claims_synthetic_demo(db_ctx, state, district) -> None:
    res = db_ctx["client"].get(
        "/api/dashboard-summary",
        params={"state": state, "district": district},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["is_synthetic_demo_data"] is False
    assert body["data_status"] in ("UNAVAILABLE", "CURATED")
    assert "data_provenance" in body
    if body["data_status"] == "UNAVAILABLE":
        assert body["total_habitations_monitored"] == 0
        assert body["message"] == "Data unavailable for this location"


@pytest.mark.parametrize("state,district", LOCATIONS)
def test_flood_forecast_is_honest_per_location(db_ctx, state, district) -> None:
    res = db_ctx["client"].get(
        "/api/flood-forecast",
        params={"state": state, "district": district},
        headers=_admin_headers(db_ctx),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["data_status"] in ("UNAVAILABLE", "LIVE", "FORECAST", "NOT_CONFIGURED")
    assert "computed_at" in body
    assert body["data_source"]
    if body["data_status"] == "UNAVAILABLE":
        assert body["gauges"] == []
        assert body["zones"] == []


def test_no_fixed_gauge_set_substituted_across_locations() -> None:
    """Either every location is honest-UNAVAILABLE (empty gauge set) or each
    live location receives its own region-filtered gauge set — never one fixed
    set cloned onto all six."""
    results = [
        get_flood_forecasts(state=state, district=district)
        for state, district in LOCATIONS
    ]
    assert len(results) == len(LOCATIONS)
    for payload in results:
        assert payload["data_status"] in ("UNAVAILABLE", "LIVE", "FORECAST", "NOT_CONFIGURED")
        assert isinstance(payload["gauges"], list)
        assert isinstance(payload["zones"], list)
        assert payload["data_source"]

    gauge_sets = {
        tuple(sorted(g["gauge_id"] for g in payload["gauges"]))
        for payload in results
    }
    # A single identical set across all six is acceptable only when it is the
    # empty, honest UNAVAILABLE set — a non-empty set cloned everywhere is
    # cross-region substitution.
    assert len(gauge_sets) >= 2 or not any(gauge_sets)


@pytest.mark.parametrize("state,district", LOCATIONS)
def test_habitations_only_match_requested_region(db_ctx, state, district) -> None:
    res = db_ctx["client"].get(
        "/api/habitations",
        params={"state": state, "district": district},
    )
    assert res.status_code == 200
    body = res.json()
    for hab in body:
        assert _effective_state(hab) == state.lower()
        assert _effective_district(hab) == district.lower()


@pytest.mark.parametrize("state,district", LOCATIONS)
def test_relocation_sites_only_match_requested_region(db_ctx, state, district) -> None:
    res = db_ctx["client"].get(
        "/api/relocation-sites",
        params={"state": state, "district": district},
    )
    assert res.status_code == 200
    body = res.json()
    for site in body:
        assert _effective_state(site) == state.lower()
        assert _effective_district(site) == district.lower()


@pytest.mark.parametrize("state,district", LOCATIONS)
def test_hazard_events_only_match_requested_region(db_ctx, state, district) -> None:
    res = db_ctx["client"].get(
        "/api/disaster-events",
        params={"state": state, "district": district},
        headers=_admin_headers(db_ctx),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["data_status"] == "HISTORICAL"
    assert body["total"] == len(body["events"])
    for event in body["events"]:
        assert event["state"].lower() == state.lower()
        assert event["district"].lower() == district.lower()


@pytest.mark.parametrize("state,district", LOCATIONS)
def test_analytics_hazards_only_match_requested_region(db_ctx, state, district) -> None:
    res = db_ctx["client"].get(
        "/api/analytics/hazards",
        params={"state": state, "district": district},
        headers=_admin_headers(db_ctx),
    )
    assert res.status_code == 200
    body = res.json()
    all_habitations = db_ctx["client"].get("/api/habitations").json()
    for event in body["events"]:
        hab = next(
            (h for h in all_habitations if h["id"] == event.get("habitation_id")),
            None,
        )
        if hab is not None:
            assert _effective_state(hab) == state.lower()
            assert _effective_district(hab) == district.lower()


def test_uttarakhand_curated_data_never_leaks_into_other_locations(db_ctx) -> None:
    """A Chennai/Cuddalore/etc. request never returns records tagged
    Uttarakhand/Chamoli, and vice-versa."""
    non_pilot = [loc for loc in LOCATIONS if loc[0].lower() != "uttarakhand"]
    for state, district in non_pilot:
        res = db_ctx["client"].get(
            "/api/habitations",
            params={"state": state, "district": district},
        )
        body = res.json()
        assert all(_effective_state(h) != "uttarakhand" for h in body)
        assert all(_effective_district(h) != "chamoli" for h in body)

        res = db_ctx["client"].get(
            "/api/relocation-sites",
            params={"state": state, "district": district},
        )
        body = res.json()
        assert all(_effective_state(s) != "uttarakhand" for s in body)
        assert all(_effective_district(s) != "chamoli" for s in body)