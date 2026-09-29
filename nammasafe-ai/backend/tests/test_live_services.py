"""
Unit tests for the SAFE_MOVE_AI live-data services (weather, terrain, flood,
rainfall, nearby places, geocode). HTTP is stubbed so no real calls escape.

Core contract: when upstream data cannot be reached, every payload must stay
explicitly labelled (UNAVAILABLE / NOT CONFIGURED) — never fabricated values.
"""

import httpx
import pytest

from app.http_client import HttpFetchError


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    @property
    def content(self):
        return b""


def _patch_http(monkeypatch, module, handler):
    def _http_get(url, params=None, timeout=15.0, headers=None, max_retries=2):
        return handler(url, params)

    monkeypatch.setattr(f"app.{module}.http_get", _http_get)


# ---------------- Weather ----------------

def test_weather_service_live_payload(monkeypatch):
    from app.weather_service import WeatherService

    def handler(url, params):
        assert "/forecast" in url
        assert params["latitude"] == 30.43
        return FakeResponse(200, {
            "current": {
                "time": "2025-09-18T10:00",
                "temperature_2m": 17.2,
                "relative_humidity_2m": 61,
                "precipitation": 12.3,
                "weather_code": 81,
                "wind_speed_10m": 9.1,
                "wind_gusts_10m": 21.4,
            },
            "daily": {
                "time": ["2025-09-18", "2025-09-19"],
                "temperature_2m_max": [19.0, 20.0],
                "temperature_2m_min": [11.0, 12.0],
                "precipitation_sum": [8.0, 0.0],
                "precipitation_probability_max": [70, 20],
                "wind_speed_10m_max": [15.0, 12.0],
            },
        })

    _patch_http(monkeypatch, "weather_service", handler)
    service = WeatherService(base_url="https://test")
    payload = service.get_weather(30.43, 79.56)

    assert payload["data_status"] == "LIVE"
    assert payload["current"]["temperature_c"] == 17.2
    assert payload["current"]["rain_intensity"] == "HEAVY"
    assert payload["current"]["weather_description"] == "Moderate rain showers"
    assert len(payload["forecast"]) == 2
    assert payload["forecast"][0]["date"] == "2025-09-18"


def test_weather_service_unavailable_is_labelled_not_fabricated(monkeypatch):
    from app.weather_service import WeatherService

    def handler(url, params):
        raise HttpFetchError("boom")

    _patch_http(monkeypatch, "weather_service", handler)
    payload = WeatherService(base_url="https://test").get_weather(30.43, 79.56)

    assert payload["data_status"] == "UNAVAILABLE"
    assert payload["current"] is None
    assert payload["forecast"] == []


# ---------------- Terrain ----------------

def test_terrain_service_slope_computation(monkeypatch):
    from app.terrain_service import TerrainService

    calls = []

    def handler(url, params):
        calls.append(url)
        count = len(params["latitude"].split(","))
        # centre at 300 m, ring lower -> positive slope estimate
        return FakeResponse(200, {"elevation": [300.0] + [320.0] * (count - 1)})

    _patch_http(monkeypatch, "terrain_service", handler)
    payload = TerrainService(base_url="https://test").get_terrain(30.0, 79.0)

    assert payload["data_status"] == "LIVE"
    assert payload["elevation_m"] == 300.0
    assert payload["slope_percent"] is not None and payload["slope_percent"] > 0
    assert payload["slope_category"] in ("NEARLY_LEVEL", "GENTLY_SLOPING", "MODERATELY_SLOPING", "STEEP", "VERY_STEEP")
    assert calls  # one multi-point request happened


def test_terrain_service_unavailable(monkeypatch):
    from app.terrain_service import TerrainService

    def handler(url, params):
        raise HttpFetchError("boom")

    _patch_http(monkeypatch, "terrain_service", handler)
    payload = TerrainService(base_url="https://test").get_terrain(30.0, 79.0)

    assert payload["data_status"] == "UNAVAILABLE"
    assert payload["elevation_m"] is None


# ---------------- Flood (GloFAS) ----------------

def test_flood_service_not_configured_without_dataset(monkeypatch):
    from app import config as _config
    monkeypatch.setattr(_config, "GLOPAS_DATA_DIR", "")
    monkeypatch.setattr(_config, "GLOFAS_DATASET_PATH", "")
    from app.flood_service import FloodDataService

    payload = FloodDataService().get_flood_risk(30.0, 79.0)
    assert payload["data_status"] == "NOT_CONFIGURED"
    assert payload["latitude"] == 30.0
    assert payload["longitude"] == 79.0


def test_flood_service_forecast_honest_with_configured_readable_dataset(monkeypatch):
    """Configured + readable dataset returns data_status=FORECAST with the full
    discharge/threshold/lead-time/horizon contract — never fabricated levels."""
    import sys
    import types

    from app.flood_service import CopernicusGloFASProvider, FloodDataService

    monkeypatch.setitem(sys.modules, "netCDF4", types.SimpleNamespace(Dataset=None))
    monkeypatch.setattr(CopernicusGloFASProvider, "_dataset_path", lambda self: "glofas_forecast.nc")

    def _dup(self, *args, **kwargs):
        raise AssertionError("_read_forecast must be stubbed")  # pragma: no cover

    def _read(self, netCDF4, dataset_path, latitude, longitude):
        return {
            "data_status": "FORECAST",
            "data_source": "Copernicus GloFAS via CDS",
            "latitude": 30.5,
            "longitude": 79.9,
            "river_discharge_m3s": 4210.25,
            "threshold_m3s": 3511.2,
            "discharge_band": "ELEVATED",
            "lead_time_hours": 72,
            "issue_time": "2026-09-23T00:00:00",
            "valid_time": "2026-09-26T00:00:00",
            "forecast_hours": 4,
            "dataset": "glofas_forecast.nc",
            "computed_at": "2026-09-24T00:00:00Z",
            "assumption": "Percentile-derived band/threshold.",
        }

    monkeypatch.setattr(CopernicusGloFASProvider, "_read_forecast", _read)

    payload = FloodDataService().get_flood_risk(30.5, 79.9)
    assert payload["data_status"] == "FORECAST"
    assert payload["discharge_band"] == "ELEVATED"
    assert payload["river_discharge_m3s"] == 4210.25
    assert payload["threshold_m3s"] == 3511.2
    assert payload["lead_time_hours"] == 72
    assert payload["issue_time"] and payload["valid_time"]


def test_flood_service_decode_time_horizon_requires_no_cftime(monkeypatch):
    """Without cftime/netCDF4 time decoding the horizon stays null rather than
    a fabricated estimate."""
    import sys
    import types

    from app.flood_service import _decode_time_horizon

    # Modules present but expose no num2date -> both import paths fail.
    monkeypatch.setitem(sys.modules, "cftime", types.ModuleType("cftime"))
    monkeypatch.setitem(sys.modules, "netCDF4", types.ModuleType("netCDF4"))
    assert _decode_time_horizon(None) == (None, None)


# ---------------- Rainfall (GPM) ----------------

def test_rainfall_service_not_configured_when_off(monkeypatch):
    from app import config as _config
    monkeypatch.setattr(_config, "GPM_MODE", "off")
    from app.rainfall_service import RainfallDataService

    payload = RainfallDataService().get_rainfall(30.0, 79.0)
    assert payload["data_status"] == "NOT_CONFIGURED"
    assert "GPM_MODE" in payload["reason"]


# ---------------- Nearby places (Overpass) ----------------

def test_nearby_places_sorted_and_live(monkeypatch):
    from app.nearby_places import NearbyPlacesService

    def handler(url, params):
        assert "overpass" in url
        return FakeResponse(200, {
            "elements": [
                {"type": "node", "id": 1, "lat": 30.50, "lon": 79.50, "tags": {"name": "District Hospital", "amenity": "hospital"}},
            ]
        })

    _patch_http(monkeypatch, "nearby_places", handler)
    payload = NearbyPlacesService(overpass_url="https://overpass.test", radius_km=20.0).get_nearby("hospitals", 30.50, 79.50)

    assert payload["data_status"] == "LIVE"
    assert payload["count"] == 1  # only the hospital matches "hospitals" kind query
    assert payload["places"][0]["name"] == "District Hospital"


def test_nearby_places_rejects_unknown_kind(monkeypatch):
    from app.nearby_places import NearbyPlacesService

    with pytest.raises(ValueError):
        NearbyPlacesService().get_nearby("nope", 30.0, 79.0)


def test_nearby_places_unavailable_on_error(monkeypatch):
    from app.nearby_places import NearbyPlacesService

    def handler(url, params):
        raise HttpFetchError("rate limit")

    _patch_http(monkeypatch, "nearby_places", handler)
    payload = NearbyPlacesService(overpass_url="https://overpass.test").get_nearby("schools", 30.0, 79.0)
    assert payload["data_status"] == "UNAVAILABLE"
    assert payload["places"] == []


# ---------------- Geocode (Nominatim) ----------------

def test_geocode_live(monkeypatch):
    from app.geocode_service import GeocodeService

    def handler(url, params):
        assert "nominatim" in url
        return FakeResponse(200, [
            {"place_id": 42, "display_name": "Joshimath, Chamoli",
             "lat": "30.5574", "lon": "79.5658", "type": "town", "category": "place", "address": {"village": "Joshimath"}},
        ])

    _patch_http(monkeypatch, "geocode_service", handler)
    payload = GeocodeService(base_url="https://nominatim.test").search("Joshimath")

    assert payload["data_status"] == "LIVE"
    assert payload["count"] == 1
    assert payload["places"][0]["latitude"] == 30.5574


def test_geocode_unavailable(monkeypatch):
    from app.geocode_service import GeocodeService

    def handler(url, params):
        raise HttpFetchError("429 rate limited")

    _patch_http(monkeypatch, "geocode_service", handler)
    payload = GeocodeService(base_url="https://nominatim.test").search("Joshimath")
    assert payload["data_status"] == "UNAVAILABLE"
    assert payload["count"] == 0


# ---------------- Routing service ----------------

def test_osrm_route_payload(monkeypatch):
    from app import config as _config
    monkeypatch.setattr(_config, "ROUTING_PROVIDER", "osrm")
    from app.routing_service import RoutingService

    def handler(url, params):
        assert "osrm" in url or "router.project-osrm" in url
        return FakeResponse(200, {
            "code": "Ok",
            "routes": [{"distance": 55400.0, "duration": 2700.0, "geometry": {"type": "LineString", "coordinates": [[79.5, 30.4], [79.2, 30.3]]}}],
        })

    _patch_http(monkeypatch, "routing_service", handler)
    payload = RoutingService().safe_routes({}, (30.4, 79.5), (30.3, 79.2))

    assert "options" in payload
    assert payload["options"][0]["data_source"] == "OSRM (open routing service)"
    assert payload["options"][0]["distance_km"] == pytest.approx(55.4, abs=0.01)


def test_routing_no_route_labelled(monkeypatch):
    from app import config as _config
    monkeypatch.setattr(_config, "ROUTING_PROVIDER", "local")
    from app.routing_service import RoutingService

    # No local graph VPN: far-off coordinates cannot snap -> NO_ROUTE
    payload = RoutingService().safe_routes({}, (28.6, 77.2), (19.07, 72.87))
    assert payload["data_status"] == "NO_ROUTE"
    assert payload["options"] == []