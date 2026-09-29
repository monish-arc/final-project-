"""
Contract tests for the SAFE_MOVE_AI /api/* live-intelligence endpoints.

DCost services are patched at the boundary so upsteam HTTP never fires; the
tests assert the wire contract: auth, data_status labelling and honest
"UNKNOWN / UNAVAILABLE" behaviour instead of fabricated numbers.
"""

from app.flood_service import FloodDataService
from app.main import app
from app.rainfall_service import RainfallDataService
from app.safe_location_service import safe_location_service
from app.terrain_service import TerrainService
from app.weather_service import WeatherService


class _FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    @property
    def content(self):
        return b""


def _weather_live(self, lat, lng):
    return {
        "data_status": "LIVE",
        "current": {"temperature_c": 17.0, "precipitation_mm": 14.0, "weather_code": 63,
                    "rain_intensity": "HEAVY", "weather_description": "Moderate rain showers"},
        "forecast": [],
    }


def _rain_live(self, lat, lng):
    return {"data_status": "LIVE", "precipitation_mm_hour": 12.0, "dataset": "3B-HHR.MS.MRG.3IMERG.20250917-S000000-E002959.0000.V07A.HDF5"}


def _flood_live(self, lat, lng):
    return {"data_status": "LIVE", "discharge_band": "ELEVATED", "river_discharge_m3s": 4200.0, "dataset": "glofas.nc", "data_source": "Copernicus GloFAS"}


def _terrain_live(self, lat, lng):
    return {"data_status": "LIVE", "elevation_m": 1950.0, "slope_percent": 12.0, "slope_category": "MODERATELY_SLOPING", "data_source": "Open-Meteo elevation"}


def test_weather_endpoint_requires_auth(db_ctx):
    assert db_ctx["client"].get("/api/weather/30.4/79.5").status_code == 401


def test_weather_endpoint_contract(monkeypatch, db_ctx, officer_headers):
    calls = []

    def handler(url, params=None, timeout=15.0, headers=None, max_retries=2):
        calls.append(url)
        return _FakeResp(200, {
            "current": {"time": "t", "temperature_2m": 17.0, "relative_humidity_2m": 60,
                        "precipitation": 14.0, "weather_code": 63, "wind_speed_10m": 9.0, "wind_gusts_10m": 20.0},
            "daily": {"time": [], "temperature_2m_max": [], "temperature_2m_min": [],
                      "precipitation_sum": [], "precipitation_probability_max": [], "wind_speed_10m_max": []},
        })

    monkeypatch.setattr("app.weather_service.http_get", handler)
    response = db_ctx["client"].get("/api/weather/30.4/79.5", headers=officer_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["data_status"] == "LIVE"
    assert data["current"]["precipitation_mm"] == 14.0
    assert calls


def test_weather_endpoint_unavailable_is_explicit(monkeypatch, db_ctx, officer_headers):
    from app.http_client import HttpFetchError

    def handler(url, params=None, timeout=15.0, headers=None, max_retries=2):
        raise HttpFetchError("no network")

    monkeypatch.setattr("app.weather_service.http_get", handler)
    response = db_ctx["client"].get("/api/weather/30.42/79.52", headers=officer_headers)
    assert response.status_code == 200
    assert response.json()["data_status"] == "UNAVAILABLE"
    assert response.json()["current"] is None


def test_weather_forecast_endpoint_requires_auth(db_ctx):
    assert db_ctx["client"].get(
        "/api/weather/forecast?latitude=30.4&longitude=79.5"
    ).status_code == 401


def test_weather_forecast_endpoint_contract(monkeypatch, db_ctx, officer_headers):
    from app.weather_service import weather_service

    weather_service._cache.clear()
    weather_service._grid_cache.clear()

    def handler(url, params=None, timeout=15.0, headers=None, max_retries=2):
        return _FakeResp(200, {
            "current": {"time": "t", "temperature_2m": 17.0, "relative_humidity_2m": 60,
                        "precipitation": 14.0, "weather_code": 63, "wind_speed_10m": 9.0,
                        "wind_gusts_10m": 20.0},
            "daily": {"time": ["2026-09-19"], "temperature_2m_max": [22.0],
                      "temperature_2m_min": [14.0], "precipitation_sum": [16.0],
                      "precipitation_probability_max": [80], "wind_speed_10m_max": [16.0],
                      "weather_code": [63]},
        })

    monkeypatch.setattr("app.weather_service.http_get", handler)
    response = db_ctx["client"].get(
        "/api/weather/forecast?latitude=30.4&longitude=79.5&days=7", headers=officer_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["data_status"] == "LIVE"
    assert data["provider"] == "Open-Meteo"
    assert data["provider_role"] == "primary"
    assert "timezone" in data
    assert data["fetched_at"].endswith("Z") and data["fetched_at"]
    assert data["dataset"].startswith("Open-Meteo")
    assert isinstance(data["forecast"], list)


def _grid_cell_payload(temperature):
    return {
        "current": {
            "temperature_2m": temperature,
            "precipitation": 1.0,
            "weather_code": 61,
            "wind_speed_10m": 6.0,
            "relative_humidity_2m": 80,
            "pressure_msl": 1010.0,
            "time": "2026-09-19T10:00",
        },
        "hourly": {
            "time": [f"2026-09-19T{h:02d}:00" for h in range(48)],
            "temperature_2m": [temperature + h for h in range(48)],
            "precipitation": [float(h % 4) for h in range(48)],
            "precipitation_probability": [h % 101 for h in range(48)],
            "weather_code": [0] * 48,
            "wind_speed_10m": [8.0] * 48,
            "wind_gusts_10m": [30.0] * 48,
            "relative_humidity_2m": [70.0] * 48,
            "cloud_cover": [40.0] * 48,
        },
        "daily": {
            "time": ["2026-09-19"],
            "temperature_2m_max": [temperature],
            "temperature_2m_min": [temperature - 5.0],
            "precipitation_sum": [1.0],
            "precipitation_probability_max": [40],
            "wind_speed_10m_max": [12.0],
            "weather_code": [61],
        },
        "timezone": "Asia/Kolkata",
        "elevation": 300.0,
    }


def test_weather_grid_endpoint_requires_auth(db_ctx):
    assert db_ctx["client"].get(
        "/api/weather/grid?bounds=30.8,30,80,78"
    ).status_code == 401


def test_weather_grid_endpoint_contract(monkeypatch, db_ctx, officer_headers):
    from app.weather_service import weather_service

    weather_service._grid_cache.clear()
    weather_service._cache.clear()

    def handler(url, params=None, timeout=15.0, headers=None, max_retries=2):
        params = params or {}
        count = len(params.get("latitude", "").split(","))
        return _FakeResp(200, [_grid_cell_payload(17.0 + i) for i in range(count)])

    monkeypatch.setattr("app.weather_service.http_get", handler)
    response = db_ctx["client"].get(
        "/api/weather/grid?bounds=30.8,30,80,78&step=0.5&variable=temperature_2m&day=0&max_points=50",
        headers=officer_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["data_status"] == "LIVE"
    assert data["provider"] == "Open-Meteo"
    assert data["provider_role"] == "primary"
    assert data["variable"] == "temperature_2m"
    assert data["unit"] == "°C"
    assert data["points"]
    assert all(p["value"] is not None for p in data["points"])


def test_weather_grid_endpoint_hour_intraday(monkeypatch, db_ctx, officer_headers):
    from app.weather_service import weather_service

    weather_service._grid_cache.clear()
    weather_service._cache.clear()

    def handler(url, params=None, timeout=15.0, headers=None, max_retries=2):
        params = params or {}
        count = len(params.get("latitude", "").split(","))
        return _FakeResp(200, [_grid_cell_payload(17.0 + i) for i in range(count)])

    monkeypatch.setattr("app.weather_service.http_get", handler)
    response = db_ctx["client"].get(
        "/api/weather/grid?bounds=30.8,30,80,78&step=0.5&variable=temperature_2m"
        "&hour=3&max_points=50",
        headers=officer_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["hour"] == 3
    assert data["day"] == 0
    assert data["data_status"] == "FORECAST"
    # hourly[3] of the stub block for the first cell: 17.0 + 3 = 20.0
    assert data["points"][0]["value"] == 20.0


def test_weather_grid_endpoint_rejects_hour_out_of_range(db_ctx, officer_headers):
    response = db_ctx["client"].get(
        "/api/weather/grid?bounds=30.8,30,80,78&hour=48",
        headers=officer_headers,
    )
    assert response.status_code == 422


def test_weather_grid_endpoint_rejects_unknown_variable(db_ctx, officer_headers):
    response = db_ctx["client"].get(
        "/api/weather/grid?bounds=30.8,30,80,78&variable=bogus",
        headers=officer_headers,
    )
    assert response.status_code == 400


def test_weather_grid_endpoint_rejects_bad_bounds(db_ctx, officer_headers):
    response = db_ctx["client"].get(
        "/api/weather/grid?bounds=abc",
        headers=officer_headers,
    )
    assert response.status_code == 400


def test_nearby_endpoint_rejects_unknown_kind(db_ctx, auth_headers):
    response = db_ctx["client"].get("/api/nearby/bunkers?lat=30.4&lng=79.5", headers=auth_headers)
    assert response.status_code == 400


def test_rainfall_endpoint_unconfigured_returns_clean_200(monkeypatch, db_ctx, officer_headers):
    from app import config as _config

    monkeypatch.setattr(_config, "GPM_MODE", "off")
    monkeypatch.setattr(_config, "GPM_DATA_DIR", "")

    response = db_ctx["client"].get(
        "/api/rainfall/30.5574/79.5658", headers=officer_headers
    )
    assert response.status_code == 200  # labelled payload, never a 500
    data = response.json()
    assert data["data_status"] == "NOT_CONFIGURED"
    assert data["latitude"] == 30.5574
    assert data["longitude"] == 79.5658
    assert "GPM_MODE" in data["reason"]


def test_rainfall_grid_endpoint_unconfigured_returns_clean_200(monkeypatch, db_ctx, officer_headers):
    from app import config as _config

    monkeypatch.setattr(_config, "GPM_MODE", "off")
    monkeypatch.setattr(_config, "GPM_DATA_DIR", "")

    response = db_ctx["client"].get(
        "/api/rainfall-grid?bounds=30.8,29.8,79.8,79.0&max_points=10", headers=officer_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["data_status"] == "NOT_CONFIGURED"
    assert data["points"] == []
    assert data["bounds"] == {"north": 30.8, "south": 29.8, "east": 79.8, "west": 79.0}
    assert "GPM_MODE" in data["reason"]


def test_rainfall_grid_endpoint_contract(monkeypatch, db_ctx, officer_headers):
    def _grid_live(self, north, south, east, west, step=0.05, max_points=400):
        return {
            "data_status": "LIVE",
            "data_source": "NASA GPM IMERG (GES DISC)",
            "dataset": "3B-HHR-E.MS.MRG.3IMERG.20250917-S053000-E055959.0330.V07C.HDF5",
            "tile_time": None,
            "computed_at": "2026-09-18T05:30:00Z",
            "bounds": {"north": north, "south": south, "east": east, "west": west},
            "points": [
                {"latitude": 30.8, "longitude": 79.0, "precipitation_mm_hour": 0.0},
                {"latitude": 30.75, "longitude": 79.1, "precipitation_mm_hour": 3.2},
                {"latitude": 30.7, "longitude": 79.2, "precipitation_mm_hour": None},
            ],
            "assumption": "IMERG precipitation estimate.",
            "reason": None,
        }

    monkeypatch.setattr(RainfallDataService, "get_grid_samples", _grid_live)
    response = db_ctx["client"].get(
        "/api/rainfall-grid?bounds=30.8,29.8,79.8,79.0&step=0.05&max_points=3",
        headers=officer_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["data_status"] == "LIVE"
    assert len(data["points"]) == 3
    assert data["points"][1]["precipitation_mm_hour"] == 3.2
    assert data["points"][2]["precipitation_mm_hour"] is None
    assert data["dataset"].endswith("V07C.HDF5")


def test_risk_assessment_endpoint_citizen_ok(monkeypatch, db_ctx, auth_headers):
    monkeypatch.setattr(WeatherService, "get_weather", _weather_live)
    monkeypatch.setattr(RainfallDataService, "get_rainfall", _rain_live)
    monkeypatch.setattr(FloodDataService, "get_flood_risk", _flood_live)
    monkeypatch.setattr(TerrainService, "get_terrain", _terrain_live)

    response = db_ctx["client"].get(
        "/api/risk-assessment?lat=30.45&lng=79.70&place_label=Joshimath&force=true",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "risk_score" in data
    assert data["risk_band"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data["caveat"]
    assert data["assessment_mode"] == "rule_based"
    assert data["model_status"] == "RULE_BASED"
    factors = {f["key"] for f in data["factors"]}
    assert "historical" in factors and "proximity" in factors
    assert data["sources"]


def test_risk_assessment_recalculate_requires_auth(db_ctx):
    response = db_ctx["client"].get("/api/risk-assessment?lat=30.4&lng=79.5")
    assert response.status_code == 401


def test_risk_zones_contract(monkeypatch, db_ctx, auth_headers):
    monkeypatch.setattr(WeatherService, "get_weather", _weather_live)
    monkeypatch.setattr(RainfallDataService, "get_rainfall", _rain_live)
    monkeypatch.setattr(FloodDataService, "get_flood_risk", _flood_live)
    monkeypatch.setattr(TerrainService, "get_terrain", _terrain_live)

    response = db_ctx["client"].get(
        "/api/risk-zones?granularity=habitations&max_points=2", headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["granularity"] == "habitations"
    assert data["assessment_label"] == "AI-Assessed High-Risk Zone"
    assert len(data["zones"]) >= 1
    for zone in data["zones"]:
        assert "rz-" in zone["id"]
        assert zone["risk_band"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert zone["assessment_label"] == "AI-Assessed High-Risk Zone"


def test_safe_locations_endpoint(monkeypatch, db_ctx, auth_headers):
    def fake_nearby(kind, lat, lng):
        return {"data_status": "LIVE", "count": 1, "places": [
            {"osm_type": "node", "osm_id": 202, "name": "Community Hall", "latitude": 30.5560, "longitude": 79.5665, "kind": "facility"},
        ]} if kind == "facilities" else {"data_status": "LIVE", "count": 0, "places": []}

    def fake_terrain(lat, lng):
        return {"data_status": "LIVE", "elevation_m": 1950.0, "slope_percent": 12.0, "slope_category": "MODERATELY_SLOPING", "data_source": "Open-Meteo elevation"}

    monkeypatch.setattr(safe_location_service._nearby, "get_nearby", fake_nearby)
    monkeypatch.setattr(safe_location_service._terrain, "get_terrain", fake_terrain)

    response = db_ctx["client"].get(
        "/api/safe-locations?lat=30.5574&lng=79.5658&affected_population=100", headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["data_status"] == "LIVE"
    assert data["center"]["latitude"] == 30.5574
    assert "node-202" in {loc["id"] for loc in data["locations"]}
    assert all(loc["data_grade"] in ("REAL", "ESTIMATE") for loc in data["locations"])