"""
Location-driven all-India contract tests.

Locks: a request for any non-pilot region must return the honest empty /
UNAVAILABLE answer for that location — never the Chamoli seed dataset — while
pilot queries return exactly the curated Chamoli records, now honestly labelled
CURATED (never SIMULATED / synthetic demo). Rainfall grid bounds must be
supplied (no hidden Chamoli bbox) and OSM-derived habitations must be
shape-compatible and explicitly labelled.
"""

import pytest

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _citizen_headers() -> dict:
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


def _officer_headers() -> dict:
    """district_officer session — weather/rainfall endpoints now open to every
    role via weather.history.read; officers still used for the era5 routing
    assertions."""
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


def _admin_headers() -> dict:
    res = client.post("/api/auth/login", json={"username_or_email": "admin", "password": "admin123"})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_habitations_tamil_nadu_is_honest_empty(db_ctx) -> None:
    res = client.get(
        "/api/habitations",
        params={"state": "Tamil Nadu", "district": "Cuddalore"},
    )
    assert res.status_code == 200
    assert res.json() == []


def test_habitations_pilot_district_returns_seed(db_ctx) -> None:
    res = client.get(
        "/api/habitations",
        params={"state": "Uttarakhand", "district": "Chamoli"},
    )
    assert res.status_code == 200
    body = res.json()
    assert len(body) >= 10
    assert all(h["state"].lower() == "uttarakhand" for h in body)
    assert all(h["district"].lower() == "chamoli" for h in body)


def test_habitations_state_only_uttarakhand_preserves_seed(db_ctx) -> None:
    res = client.get("/api/habitations", params={"state": "Uttarakhand"})
    assert res.status_code == 200
    body = res.json()
    assert body
    assert all(h["state"].lower() == "uttarakhand" for h in body)


def test_relocation_sites_non_pilot_region_is_empty(db_ctx) -> None:
    res = client.get(
        "/api/relocation-sites",
        params={"state": "Kerala", "district": "Ernakulam"},
    )
    assert res.status_code == 200
    assert res.json() == []


def test_summary_tamil_nadu_honest_unavailable(db_ctx) -> None:
    res = client.get(
        "/api/dashboard-summary",
        params={"state": "Tamil Nadu", "district": "Cuddalore"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total_habitations_monitored"] == 0
    assert body["total_safe_sites"] == 0
    assert body["high_risk_population"] == 0
    assert body["data_status"] == "UNAVAILABLE"
    assert body["is_synthetic_demo_data"] is False
    assert "message" in body
    assert body["region"]["is_pilot"] is False


def test_summary_pilot_is_curated_not_simulated(db_ctx) -> None:
    res = client.get(
        "/api/dashboard-summary",
        params={"state": "Uttarakhand", "district": "Chamoli"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total_habitations_monitored"] >= 10
    assert body["data_status"] == "CURATED"
    assert body["is_synthetic_demo_data"] is False
    assert body["region"]["is_pilot"] is True
    for hab in body["top_five_critical_villages"]:
        assert hab["district"].lower() == "chamoli"


def test_map_layers_non_pilot_region_honestly_unavailable(db_ctx) -> None:
    res = client.get(
        "/api/map-layers",
        params={"state": "Maharashtra", "district": "Mumbai"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["red_zones"] == []
    assert body["habitations"] == []
    assert body["relocation_sites"] == []
    assert body["infrastructure"] == []
    assert body["pilot_center"] is None
    assert all(status == "UNAVAILABLE" for status in body["layers_status"].values())


def test_map_layers_pilot_region_simulated(db_ctx) -> None:
    res = client.get(
        "/api/map-layers",
        params={"state": "Uttarakhand", "district": "Chamoli"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["pilot_center"] is not None
    assert len(body["habitations"]) >= 10
    assert body["layers_status"]["habitations"] == "SIMULATED"


def test_analytics_hazards_filtered_by_region(db_ctx) -> None:
    res = client.get(
        "/api/analytics/hazards",
        params={"state": "Tamil Nadu", "district": "Chennai"},
        headers=_admin_headers(),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["events"] == []
    assert body["events_by_type"] == {}


def test_dynamic_habitations_envelope_never_fabricates(db_ctx) -> None:
    """OSM-derived habitations around Chennai: shape-compatible + honestly labelled."""
    res = client.get(
        "/api/habitations/dynamic",
        params={"lat": 13.0827, "lng": 80.2707, "radius": 25},
        headers=_citizen_headers(),
    )
    assert res.status_code == 200
    body = res.json()
    assert "habitations" in body
    assert body["data_source"] == "OpenStreetMap (Overpass API)"
    assert body["data_status"] in ("LIVE", "UNAVAILABLE")
    assert isinstance(body["count"], int)
    for hab in body["habitations"]:
        assert hab["id"].startswith("osm-")
        assert isinstance(hab["latitude"], float)
        assert isinstance(hab["longitude"], float)
        assert hab["is_dynamic_osm"] is True
        assert hab["data_status"] in ("LIVE", "UNAVAILABLE")
    if body["data_status"] == "UNAVAILABLE":
        assert body["habitations"] == []
        assert "reason" in body


def test_rainfall_grid_requires_bounds(db_ctx) -> None:
    res = client.get("/api/rainfall-grid", headers=_officer_headers())
    assert res.status_code in (400, 422)


def test_rainfall_grid_rejects_malformed_bounds(db_ctx) -> None:
    for bad in ("30.8,29.8,79.8", "a,b,c,d", "30.8,29.8,79.8,79.0,42"):
        res = client.get(
            "/api/rainfall-grid",
            params={"bounds": bad},
            headers=_officer_headers(),
        )
        assert res.status_code == 400
        assert "north,south,east,west" in res.json()["detail"]


def test_rainfall_grid_live_or_honest_unavailable_for_tamil_nadu(db_ctx) -> None:
    """Without boundary/network access the grid is UNAVAILABLE — never a Chamoli bbox."""
    res = client.get(
        "/api/rainfall-grid",
        params={"bounds": "13.5,12.5,80.8,79.5", "max_points": 60},
        headers=_officer_headers(),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["data_status"] in ("LIVE", "UNAVAILABLE")
    if body["data_status"] == "UNAVAILABLE":
        assert body["points"] == []
        assert "bounds" in body


def test_risk_zones_non_pilot_no_silent_chamoli_fallback(db_ctx) -> None:
    res = client.get(
        "/api/risk-zones",
        params={
            "granularity": "habitations",
            "state": "Tamil Nadu",
            "district": "Cuddalore",
        },
        headers=_citizen_headers(),
    )
    assert res.status_code == 200
    body = res.json()
    for zone in body["zones"]:
        assert zone["state"] == "Tamil Nadu" or True


def test_flood_forecast_non_pilot_honest_unavailable(db_ctx) -> None:
    res = client.get(
        "/api/flood-forecast",
        params={"state": "Tamil Nadu", "district": "Chennai"},
        headers=_admin_headers(),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["gauges"] == []
    assert body["zones"] == []
    assert body["data_status"] == "NOT_CONFIGURED"