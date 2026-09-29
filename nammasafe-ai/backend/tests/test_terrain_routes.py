"""Route-level tests for /api/terrain and the /api/elevation alias."""

import pytest

from app.terrain_service import terrain_service


@pytest.fixture
def canned_terrain(monkeypatch):
    payload = {
        "latitude": 30.5,
        "longitude": 79.5,
        "data_status": "LIVE",
        "data_source": "NASA SRTMGL1.003 (LP DAAC Earthdata Cloud)",
        "provider": "nasa",
        "provider_role": "primary",
        "dataset": "NASA SRTMGL1.003",
        "elevation_m": 1892.3,
        "slope_percent": 6.2,
        "slope_degrees": 3.55,
        "slope_category": "GENTLY_SLOPING",
        "elevation_change_m": 44.0,
        "slope_window_arcsec": 3,
        "sample_radius_km": None,
        "sample_count": 9,
        "computed_at": "2026-09-21T00:00:00Z",
    }

    def fake_get(lat, lon):
        return dict(payload, latitude=lat, longitude=lon)

    monkeypatch.setattr(terrain_service, "get_terrain", fake_get)
    return payload


def test_terrain_route_live(db_ctx, auth_headers, canned_terrain):
    resp = db_ctx["client"].get("/api/terrain/30.5/79.5", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["data_status"] == "LIVE"
    assert body["provider"] == "nasa"
    assert body["elevation_m"] == 1892.3


def test_terrain_rejects_out_of_range(db_ctx, auth_headers, canned_terrain):
    assert db_ctx["client"].get("/api/terrain/300/79.5", headers=auth_headers).status_code == 400
    assert db_ctx["client"].get("/api/terrain/30.5/999", headers=auth_headers).status_code == 400


def test_terrain_requires_auth(db_ctx):
    assert db_ctx["client"].get("/api/terrain/30.5/79.5").status_code == 401


def test_elevation_alias(db_ctx, auth_headers, canned_terrain):
    resp = db_ctx["client"].get("/api/elevation?lat=30.5&lon=79.5", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "nasa"
    assert body["elevation_m"] == 1892.3


def test_elevation_alias_longitude_kw(db_ctx, auth_headers, canned_terrain):
    resp = db_ctx["client"].get("/api/elevation?lat=30.5&longitude=79.5", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["data_status"] == "LIVE"


def test_elevation_rejects_bad_lat(db_ctx, auth_headers, canned_terrain):
    resp = db_ctx["client"].get("/api/elevation?lat=999&lon=79.5", headers=auth_headers)
    assert resp.status_code == 422