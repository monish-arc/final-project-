"""
Unit tests for the Bhuvan / ISRO supporting geospatial service.

HTTP is stubbed via monkeypatched app.bhuvan_service.http_get so no real calls
escape. Core contract: when the token is missing, upstream fails, or the
location is outside documented coverage (AP & Karnataka census, AP hospitals,
intra-state routing), the payload is explicitly UNAVAILABLE / ERROR — values
are never fabricated. Census geocoding must never report coordinates.
"""

import pytest

from app import config
from app.bhuvan_service import (
    STATUS_AVAILABLE,
    STATUS_CACHED,
    STATUS_ERROR,
    STATUS_MISMATCH,
    STATUS_UNAVAILABLE,
    bhuvan_service,
)
from app.http_client import HttpFetchError


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _patch_http(monkeypatch, handler):
    def _http_get(url, params=None, timeout=15.0, headers=None, max_retries=2):
        return handler(url, params)

    monkeypatch.setattr("app.bhuvan_service.http_get", _http_get)


def _enable_token(monkeypatch, value="fake-token"):
    monkeypatch.setattr(config, "BHUVAN_API_TOKEN", value)


@pytest.fixture(autouse=True)
def _fresh_service():
    # Isolate caches between tests.
    bhuvan_service._geocode_cache.clear()
    bhuvan_service._lulc_cache.clear()
    bhuvan_service._route_cache.clear()
    bhuvan_service._hospital_cache.clear()
    yield


# ---------------- five-village geocode (census-2001) ----------------

def test_village_geocode_available_and_no_coordinates(monkeypatch):
    _enable_token(monkeypatch)

    def handler(url, params):
        assert params["token"] == "fake-token"
        assert "village" in params
        return FakeResponse(payload=[{"name1": "Testpuram", "vid": "123456", "dhq_name": "Nellore", "thq_name": "Kovur", "no_hh": "120"}])

    _patch_http(monkeypatch, handler)

    payload = bhuvan_service.resolve_village("Testpuram")
    assert payload["data_status"] == STATUS_AVAILABLE
    assert payload["data_source"].startswith("Bhuvan")
    assert payload["dataset_year"] == "2001"
    assert payload["record"]["name"] == "Testpuram"
    assert payload["record"]["census_village_code"] == "123456"
    assert payload["record"]["district"] == "Nellore"
    assert payload["record"]["households"] == "120"
    assert payload["has_coordinates"] is False
    assert "no coordinates" in payload["coordinate_note"].lower()


def test_village_geocode_location_mismatch_kept_separate(monkeypatch):
    _enable_token(monkeypatch)

    def handler(url, params):
        return FakeResponse(payload=[{"name1": "Raini", "vid": "1", "dhq_name": "West Tripura"}])

    _patch_http(monkeypatch, handler)

    payload = bhuvan_service.resolve_village("Raini", district="Chamoli")
    assert payload["data_status"] == STATUS_MISMATCH
    assert payload["record"]["district"] == "West Tripura"
    assert "never merged" in payload["reason"]


def test_village_geocode_missing_token_is_unavailable(monkeypatch):
    monkeypatch.setattr(config, "BHUVAN_API_TOKEN", "")

    def handler(url, params):  # pragma: no cover - must not be called
        raise AssertionError("no upstream call when token is missing")

    _patch_http(monkeypatch, handler)

    payload = bhuvan_service.resolve_village("Anywhere")
    assert payload["data_status"] == STATUS_UNAVAILABLE
    assert "BHUVAN_API_TOKEN" in payload["reason"]


def test_village_geocode_cached_on_second_call(monkeypatch):
    _enable_token(monkeypatch)
    calls = {"n": 0}

    def handler(url, params):
        calls["n"] += 1
        return FakeResponse(payload=[{"name1": "Cachedville", "dhq_name": "Hyderabad"}])

    _patch_http(monkeypatch, handler)

    first = bhuvan_service.resolve_village("Cachedville")
    second = bhuvan_service.resolve_village("Cachedville")
    assert first["data_status"] == STATUS_AVAILABLE
    assert second["data_status"] == STATUS_CACHED
    assert calls["n"] == 1


# ---------------- reverse geocode ----------------

def test_reverse_geocode_available(monkeypatch):
    _enable_token(monkeypatch)

    def handler(url, params):
        return FakeResponse(payload=[{"name1": "Kovur"}, {"name": "Dondapadu"}])

    _patch_http(monkeypatch, handler)

    payload = bhuvan_service.reverse_geocode(14.2895, 79.9907)
    assert payload["data_status"] == STATUS_AVAILABLE
    assert payload["villages"] == ["Kovur", "Dondapadu"]


def test_reverse_geocode_none_is_unavailable(monkeypatch):
    _enable_token(monkeypatch)

    def handler(url, params):
        return FakeResponse(payload=False)

    _patch_http(monkeypatch, handler)

    payload = bhuvan_service.reverse_geocode(14.2895, 79.9907)
    assert payload["data_status"] == STATUS_UNAVAILABLE
    assert payload["villages"] == []
    assert "Karnataka" in payload["coverage_note"]


# ---------------- hospitals (Andhra Pradesh) ----------------

def test_hospitals_available_parses_name_keys(monkeypatch):
    _enable_token(monkeypatch)

    def handler(url, params):
        assert params["theme"] == "hospital"
        assert params["buffer"] == 3000
        return FakeResponse(payload=[{"name": "GH Nellore", "lat": "14.43", "lon": "79.97", "distance": "1200"}, {"h_name": "PHC Kovur", "latitude": 14.5, "longitude": 79.9, "distance_m": 3500}])

    _patch_http(monkeypatch, handler)

    payload = bhuvan_service.get_hospitals(14.43, 79.97, buffer_m=3000)
    assert payload["data_status"] == STATUS_AVAILABLE
    assert payload["count"] == 2
    assert payload["hospitals"][0]["name"] == "GH Nellore"
    assert payload["hospitals"][0]["distance_m"] == 1200.0
    assert payload["hospitals"][1]["name"] == "PHC Kovur"
    assert "Andhra Pradesh" in payload["coverage_note"]


def test_hospitals_without_records_is_unavailable(monkeypatch):
    _enable_token(monkeypatch)

    def handler(url, params):
        return FakeResponse(payload=[])

    _patch_http(monkeypatch, handler)

    payload = bhuvan_service.get_hospitals(30.3, 78.0)
    assert payload["data_status"] == STATUS_UNAVAILABLE
    assert payload["count"] == 0


# ---------------- LULC 50K / 250K ----------------

def test_lulc_250k_point_class_and_susceptibility(monkeypatch):
    _enable_token(monkeypatch)

    def handler(url, params):
        return FakeResponse(payload={"class": "water bodies", "percent": "3"})

    _patch_http(monkeypatch, handler)

    payload = bhuvan_service.get_lulc_250k(79.97, 14.43, year="all")
    assert payload["data_status"] == STATUS_AVAILABLE
    assert payload["class"] == "water bodies"
    assert payload["dataset_year"] == "all"
    assert bhuvan_service.lulc_susceptibility("water bodies") == 80.0
    assert bhuvan_service.lulc_susceptibility("unknown cover") == 30.0
    assert bhuvan_service.lulc_susceptibility("") is None


def test_lulc_250k_no_class_is_unavailable(monkeypatch):
    _enable_token(monkeypatch)

    def handler(url, params):
        return FakeResponse(payload={"class": ""})

    _patch_http(monkeypatch, handler)

    payload = bhuvan_service.get_lulc_250k(79.97, 14.43)
    assert payload["data_status"] == STATUS_UNAVAILABLE
    assert "class" in payload["reason"].lower()


def test_lulc_50k_requires_identifiers(monkeypatch):
    _enable_token(monkeypatch)

    def handler(url, params):  # pragma: no cover - must not be called
        raise AssertionError("no upstream call without a district/state code")

    _patch_http(monkeypatch, handler)

    payload = bhuvan_service.get_lulc_50k()
    assert payload["data_status"] == STATUS_UNAVAILABLE
    assert "required" in payload["reason"]


def test_lulc_50k_district_stats(monkeypatch):
    _enable_token(monkeypatch)

    def handler(url, params):
        assert params["distcode"] == "0503"
        assert params["year"] == "1112"
        return FakeResponse(payload={"Forest": 45, "Agriculture": 55})

    _patch_http(monkeypatch, handler)

    payload = bhuvan_service.get_lulc_50k(district_code="0503", year="1112")
    assert payload["data_status"] == STATUS_AVAILABLE
    assert payload["stats"]["Forest"] == 45

    cached = bhuvan_service.get_lulc_50k(district_code="0503", year="1112")
    assert cached["data_status"] == STATUS_CACHED


# ---------------- intra-state shortest path ----------------

def test_shortest_path_feature_collection_multiline(monkeypatch):
    _enable_token(monkeypatch)

    def handler(url, params):
        return FakeResponse(payload={
            "type": "FeatureCollection",
            "features": [{"geometry": {"type": "MultiLineString", "coordinates": [[[79.9, 14.4], [79.92, 14.45], [79.95, 14.5]]]}}],
        })

    _patch_http(monkeypatch, handler)

    payload = bhuvan_service.get_shortest_path(14.4, 79.9, 14.5, 79.95)
    assert payload["data_status"] == STATUS_AVAILABLE
    assert payload["geometry"]["type"] == "MultiLineString"
    assert payload["distance_km"] > 0
    assert payload["origin"] == [14.4, 79.9]
    assert "intra-state" in payload["coverage_note"]


def test_shortest_path_null_is_unavailable(monkeypatch):
    _enable_token(monkeypatch)

    def handler(url, params):
        return FakeResponse(payload={"type": "FeatureCollection", "features": []})

    _patch_http(monkeypatch, handler)

    payload = bhuvan_service.get_shortest_path(14.4, 79.9, 13.0, 77.0)
    assert payload["data_status"] == STATUS_UNAVAILABLE
    assert payload["geometry"] is None
    assert payload["distance_km"] is None


# ---------------- upstream failures ----------------

def test_upstream_500_is_error(monkeypatch):
    _enable_token(monkeypatch)

    def handler(url, params):
        return FakeResponse(status_code=500, payload={"detail": "boom"})

    _patch_http(monkeypatch, handler)

    payload = bhuvan_service.get_lulc_250k(79.97, 14.43)
    assert payload["data_status"] == STATUS_ERROR
    assert "500" in payload["reason"]


def test_http_exception_is_error(monkeypatch):
    _enable_token(monkeypatch)

    def handler(url, params):
        raise HttpFetchError("connection refused")

    _patch_http(monkeypatch, handler)

    payload = bhuvan_service.resolve_village("Somewhere")
    assert payload["data_status"] == STATUS_ERROR
    assert "connection refused" in payload["reason"]


# ---------------- geoid tile proxy ----------------

def test_geoid_proxy_needs_api_key(monkeypatch):
    monkeypatch.setattr(config, "BHUVAN_API_KEY", "")

    payload = bhuvan_service.convert_geoid("cdnc43e", datum="elipsoid")
    assert payload["data_status"] == STATUS_UNAVAILABLE
    assert "BHUVAN_API_KEY" in payload["reason"]
    assert payload["proxy"] is True


def test_geoid_proxy_available_is_download_only(monkeypatch):
    _enable_token(monkeypatch)
    monkeypatch.setattr(config, "BHUVAN_API_KEY", "fake-key")

    def handler(url, params):  # pragma: no cover - proxy makes no upstream call
        raise AssertionError("the tile proxy must not fetch during annotation")

    _patch_http(monkeypatch, handler)

    payload = bhuvan_service.convert_geoid("cdnc43e", datum="geoid")
    assert payload["data_status"] == STATUS_AVAILABLE
    assert payload["datum"] == "geoid"
    assert payload["tile_id"] == "cdnc43e"
    assert "/geoid/curl_gdal_api.php" in payload["download_endpoint"]
    assert "no height is fabricated" in payload["height_note"]