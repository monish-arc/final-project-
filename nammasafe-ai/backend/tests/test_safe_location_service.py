"""
Safe-location engine tests: candidate curation, risk-band exclusion, data-grade
labelling (REAL vs ESTIMATE) and honest "UNKNOWN" risk when terrain cannot fire.
"""

import pytest

from app.safe_location_service import SafeLocationService

CENTER = (30.5574, 79.5658)


def _reloc_sites():
    return [
        {
            "id": "site-gauchar-01", "site_name": "Gauchar Ground",
            "latitude": 30.2800, "longitude": 78.7000,
            "low_hazard_score": 88.5, "suitability_score": 82.0,
            "land_capacity_families": 500, "water_capacity_families": 300,
            "school_capacity_families": 200, "health_capacity_families": 150,
            "road_capacity_families": 400, "current_occupancy_families": 40,
            "drinking_water_available": True, "toilets_available": 20,
            "electricity_available": True, "medical_facility": False,
            "accessible_by_road": True, "contact_name": "DDMA Chamoli",
            "contact_phone": "+91 1372 252 246", "verified": True,
            "last_verified": "2025-06-20",
        },
        {
            "id": "site-bad-01", "site_name": "Risky Flat",
            "latitude": 30.2900, "longitude": 78.7100,
            "low_hazard_score": 30.0, "suitability_score": 40.0,
            "land_capacity_families": 500, "water_capacity_families": 500,
            "school_capacity_families": 500, "health_capacity_families": 500,
            "road_capacity_families": 500,
        },
    ]


def _make_service(monkeypatch, terrain_probe=None, places_payload=None):
    service = SafeLocationService()

    def fake_nearby(kind, lat, lng):
        return places_payload or {"data_status": "LIVE", "count": 0, "places": []}

    def fake_terrain(lat, lng):
        if terrain_probe:
            return terrain_probe(lat, lng)
        return {"data_status": "LIVE", "elevation_m": 1900.0, "slope_percent": 8.0, "slope_category": "NEARLY_LEVEL", "data_source": "Open-Meteo elevation"}

    monkeypatch.setattr(service._nearby, "get_nearby", fake_nearby)
    monkeypatch.setattr(service._terrain, "get_terrain", fake_terrain)
    return service


def test_relocation_site_risk_filtering(monkeypatch):
    service = _make_service(monkeypatch)
    data = {"relocation_sites": _reloc_sites()}
    result = service.get_safe_locations(data, *CENTER, affected_population=450)

    assert result["data_status"] == "LIVE"
    # Low-hazard relocation site stays in recommendations with REAL grade.
    included = {loc["id"]: loc for loc in result["locations"]}
    assert "site-gauchar-01" in included
    assert included["site-gauchar-01"]["data_grade"] == "REAL"
    assert included["site-gauchar-01"]["risk_band"] == "LOW"
    assert included["site-gauchar-01"]["capacity_families"] > 0
    # Phase 6: survey attributes flow into the facility layer
    assert included["site-gauchar-01"]["toilets"] == 20
    assert included["site-gauchar-01"]["drinking_water"] is True
    assert included["site-gauchar-01"]["electricity"] is True
    assert included["site-gauchar-01"]["medical_facility"] is False
    assert included["site-gauchar-01"]["accessibility"] == "Road accessible"
    assert "DDMA Chamoli" in included["site-gauchar-01"]["contact"]
    assert included["site-gauchar-01"]["verified"] is True
    assert included["site-gauchar-01"]["last_verified"] == "2025-06-20"
    # High-risk relocation site is excluded, never silently recommended.
    excluded = {loc["id"]: loc for loc in result["excluded_locations"]}
    assert "site-bad-01" in excluded
    assert excluded["site-bad-01"]["risk_band"] == "CRITICAL"
    assert all(loc["risk_band"] not in result["excluded_status"] for loc in result["locations"])


def test_osm_places_estimates_and_risk(monkeypatch):
    places = {
        "data_status": "LIVE", "count": 2, "places": [
            {"osm_type": "way", "osm_id": 101, "name": "Govt HSS", "latitude": 30.5581, "longitude": 79.5671, "kind": "school"},
            {"osm_type": "node", "osm_id": 202, "name": "Community Hall", "latitude": 30.5560, "longitude": 79.5665, "kind": "facility"},
        ],
    }

    def terrain_probe(lat, lng):
        if abs(lat - 30.5581) < 0.001:
            return {"data_status": "LIVE", "elevation_m": 1700.0, "slope_percent": 30.0, "slope_category": "STEEP", "data_source": "Open-Meteo elevation"}
        return {"data_status": "LIVE", "elevation_m": 1900.0, "slope_percent": 5.0, "slope_category": "NEARLY_LEVEL", "data_source": "Open-Meteo elevation"}

    service = _make_service(monkeypatch, terrain_probe=terrain_probe, places_payload=places)
    result = service.get_safe_locations({"relocation_sites": []}, *CENTER)

    included = {loc["id"]: loc for loc in result["locations"]}
    excluded = {loc["id"]: loc for loc in result["excluded_locations"]}
    assert "node-202" in included
    assert included["node-202"]["data_grade"] == "ESTIMATE"
    assert included["node-202"]["risk_band"] == "LOW"
    assert "way-101" in excluded
    assert excluded["way-101"]["risk_band"] == "HIGH"


def test_unknown_osm_risk_not_assumed_safe(monkeypatch):
    places = {
        "data_status": "LIVE", "count": 1, "places": [
            {"osm_type": "node", "osm_id": 303, "name": "Remote Camp", "latitude": 30.5600, "longitude": 79.5700, "kind": "facility"},
        ],
    }

    def terrain_probe(lat, lng):
        return {"data_status": "UNAVAILABLE", "elevation_m": None, "slope_percent": None, "slope_category": None}

    service = _make_service(monkeypatch, terrain_probe=terrain_probe, places_payload=places)
    result = service.get_safe_locations({"relocation_sites": []}, *CENTER)

    loc = result["locations"][0]
    assert loc["risk_band"] == "UNKNOWN"  # flagged, not silently treated as safe.