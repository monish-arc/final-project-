"""
Wire-contract tests for the /api/bhuvan/* endpoints.

Services are stubbed at the BhuvanService boundary so upstream HTTP never fires.
The tests assert the route contract: auth enforcement, query passthrough, the
explicit data vocabulary (AVAILABLE / UNAVAILABLE / LOCATION_MISMATCH), and the
open validator on the geoid datum parameter.
"""

import pytest

from app import config
from app.bhuvan_service import bhuvan_service


V = {
    "source": "Bhuvan / ISRO",
    "service": "village_geocode",
    "data_status": "AVAILABLE",
    "data_source": "Bhuvan village geocode (census-2001)",
    "dataset_year": "2001",
    "query": {"village": "Testpuram"},
    "record": {"name": "Testpuram", "census_village_code": "123", "district": "Nellore"},
    "has_coordinates": False,
    "coordinate_note": "no coordinates",
    "coverage_note": "Andhra Pradesh & Karnataka",
    "reason": None,
    "computed_at": "2026-09-19T00:00:00Z",
}


def _stub_village(payload):
    def _inner(*args, **kwargs):
        return payload
    return _inner


def test_bhuvan_endpoints_require_auth(db_ctx):
    client = db_ctx["client"]
    assert client.get("/api/bhuvan/village/geocode?village=Testpuram").status_code == 401
    assert client.get("/api/bhuvan/hospitals?lat=14.4&lng=79.9").status_code == 401
    assert client.post("/api/bhuvan/shortest-path", json={"lat1": 14.4, "lon1": 79.9, "lat2": 14.5, "lon2": 80.0}).status_code == 401


def test_village_geocode_route_contract(monkeypatch, db_ctx, auth_headers):
    monkeypatch.setattr(config, "BHUVAN_API_TOKEN", "fake-token")
    monkeypatch.setattr(bhuvan_service, "resolve_village", _stub_village(V))

    response = db_ctx["client"].get("/api/bhuvan/village/geocode?state=AP&district=Nellore&village=Testpuram", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["data_status"] == "AVAILABLE"
    assert data["record"]["name"] == "Testpuram"
    assert data["has_coordinates"] is False
    assert data["dataset_year"] == "2001"


def test_village_geocode_mismatch_passthrough(monkeypatch, db_ctx, auth_headers):
    monkeypatch.setattr(config, "BHUVAN_API_TOKEN", "fake-token")
    mismatch = dict(V, data_status="LOCATION_MISMATCH", reason="Requested Chamoli, census says Nellore. Kept separate — never merged.")
    monkeypatch.setattr(bhuvan_service, "resolve_village", _stub_village(mismatch))

    response = db_ctx["client"].get("/api/bhuvan/village/geocode?district=Chamoli&village=Testpuram", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["data_status"] == "LOCATION_MISMATCH"
    assert "never merged" in data["reason"]


def test_hospitals_route_passthrough_buffer(monkeypatch, db_ctx, auth_headers):
    monkeypatch.setattr(config, "BHUVAN_API_TOKEN", "fake-token")
    monkeypatch.setattr(bhuvan_service, "get_hospitals", _stub_village({
        "source": "Bhuvan / ISRO", "service": "hospitals", "data_status": "AVAILABLE",
        "data_source": "Bhuvan hospitals proximity (Andhra Pradesh)",
        "center": {"latitude": 14.4, "longitude": 79.9}, "buffer_m": 3000,
        "count": 1, "hospitals": [{"name": "GH Nellore", "latitude": 14.43, "longitude": 79.97, "distance_m": 1200}],
        "reason": None, "computed_at": "2026-09-19T00:00:00Z",
    }))

    response = db_ctx["client"].get("/api/bhuvan/hospitals?lat=14.4&lng=79.9&buffer_m=3000", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["data_status"] == "AVAILABLE"
    assert data["buffer_m"] == 3000
    assert data["hospitals"][0]["name"] == "GH Nellore"


def test_shortest_path_route_passthrough(monkeypatch, db_ctx, auth_headers):
    monkeypatch.setattr(config, "BHUVAN_API_TOKEN", "fake-token")
    monkeypatch.setattr(bhuvan_service, "get_shortest_path", _stub_village({
        "source": "Bhuvan / ISRO", "service": "shortest_path", "data_status": "AVAILABLE",
        "data_source": "Bhuvan intra-state routing (v1)",
        "origin": [14.4, 79.9], "destination": [14.5, 80.0],
        "geometry": {"type": "MultiLineString", "coordinates": [[[79.9, 14.4], [80.0, 14.5]]]},
        "distance_km": 14.2, "reason": None, "computed_at": "2026-09-19T00:00:00Z",
    }))

    response = db_ctx["client"].post("/api/bhuvan/shortest-path", json={"lat1": 14.4, "lon1": 79.9, "lat2": 14.5, "lon2": 80.0}, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["data_status"] == "AVAILABLE"
    assert data["distance_km"] == 14.2


def test_shortest_path_rejects_invalid_geometry(monkeypatch, db_ctx, auth_headers):
    monkeypatch.setattr(config, "BHUVAN_API_TOKEN", "fake-token")
    monkeypatch.setattr(bhuvan_service, "get_shortest_path", _stub_village({}))

    response = db_ctx["client"].post("/api/bhuvan/shortest-path", json={"lat1": 91.0, "lon1": 79.9, "lat2": 14.5, "lon2": 80.0}, headers=auth_headers)
    assert response.status_code == 422


def test_geoid_datum_validated(monkeypatch, db_ctx, auth_headers):
    monkeypatch.setattr(config, "BHUVAN_API_KEY", "fake-key")
    monkeypatch.setattr(bhuvan_service, "convert_geoid", _stub_village({
        "source": "Bhuvan / ISRO", "service": "geoid_tile_proxy", "data_status": "AVAILABLE",
        "data_source": "Bhuvan CartoDEM v3R1 (CDEM) geoid tile proxy", "tile_id": "cdnc43e",
        "datum": "elipsoid", "proxy": True, "reason": None, "computed_at": "2026-09-19T00:00:00Z",
    }))

    ok = db_ctx["client"].get("/api/bhuvan/geoid?tile_id=cdnc43e&datum=geoid", headers=auth_headers)
    assert ok.status_code == 200
    assert ok.json()["data_status"] == "AVAILABLE"

    bad = db_ctx["client"].get("/api/bhuvan/geoid?tile_id=cdnc43e&datum=orthometric", headers=auth_headers)
    assert bad.status_code == 422