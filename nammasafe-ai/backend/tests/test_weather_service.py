"""
Unit tests for the live weather service — Open-Meteo primary / ECMWF backup /
IMD (Mausam, legacy opt-in).

HTTP is stubbed via monkeypatched app.weather_service.http_get so no real calls
escape. Contract:
  * default chain -> Open-Meteo is the honest primary (LIVE).
  * Open-Meteo unreachable -> ECMWF (IFS 0.25°) serves as provider_role=backup
    and payloads label the missing ECBWF variables honestly (null, never fake).
  * IMD configured + usable -> IMD serves (legacy opt-in, backward compatible).
  * IMD configured but unusable -> Open-Meteo fallback names the IMD failure.
  * both providers fail -> payload is explicitly UNAVAILABLE, no values fabricated.
  * grid samples are per-cell cached and bounded to India.
"""

import pytest
import threading
import time
from datetime import datetime, timedelta, timezone

from app import config
from app.http_client import HttpFetchError
from app.weather_service import (
    IMDProvider,
    _PROVIDER_COOLDOWN_UNTIL,
    _imd_configured,
    _mark_provider_cooldown,
    weather_service,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, raw=None):
        self.status_code = status_code
        self._payload = payload
        self._raw = raw

    def json(self):
        if self._payload is not None:
            return self._payload
        raise ValueError("no json")

    @property
    def text(self):
        return self._raw or ""


def _patch_http(monkeypatch, handler):
    def _http_get(url, params=None, timeout=15.0, headers=None, max_retries=2):
        return handler(url, params)

    monkeypatch.setattr("app.weather_service.http_get", _http_get)


def _enable_imd(monkeypatch, base="https://mausam.imd.gov.in/apix", token="fake-token"):
    monkeypatch.setattr(config, "IMD_MAUSAM_BASE_URL", base)
    monkeypatch.setattr(config, "IMD_MAUSAM_TOKEN", token)


def _disable_imd(monkeypatch):
    monkeypatch.setattr(config, "IMD_MAUSAM_BASE_URL", "")
    monkeypatch.setattr(config, "IMD_MAUSAM_TOKEN", "")


OPEN_METEO_BODY = {
    "current": {
        "temperature_2m": 19.5,
        "relative_humidity_2m": 84,
        "precipitation": 2.2,
        "weather_code": 61,
        "wind_speed_10m": 5.5,
        "wind_gusts_10m": 12.0,
        "pressure_msl": 1009.0,
        "cloud_cover": 70,
        "wind_direction_10m": 190,
        "time": "2026-09-19T10:00",
    },
    "daily": {
        "time": ["2026-09-19"],
        "temperature_2m_max": [23.4],
        "temperature_2m_min": [14.2],
        "precipitation_sum": [4.0],
        "precipitation_probability_max": [60],
        "wind_speed_10m_max": [18.0],
        "weather_code": [61],
    },
    "hourly": {
        "time": ["2026-09-19T10:00"],
        "temperature_2m": [19.5],
        "precipitation": [2.2],
        "precipitation_probability": [60],
        "weather_code": [61],
        "wind_speed_10m": [5.5],
        "relative_humidity_2m": [84],
    },
    "timezone": "Asia/Kolkata",
    "elevation": 1250.0,
    "generationtime_ms": 12.3,
}


@pytest.fixture(autouse=True)
def _fresh_service():
    weather_service._cache.clear()
    weather_service._grid_cache.clear()
    yield


# ---------------- IMD legacy opt-in ----------------

def test_imd_not_configured_when_missing_values(monkeypatch):
    monkeypatch.setattr(config, "IMD_MAUSAM_BASE_URL", "")
    monkeypatch.setattr(config, "IMD_MAUSAM_TOKEN", "x")
    assert _imd_configured() is False

    monkeypatch.setattr(config, "IMD_MAUSAM_BASE_URL", "https://x")
    monkeypatch.setattr(config, "IMD_MAUSAM_TOKEN", "")
    assert _imd_configured() is False


def test_imd_configured_only_with_both_values(monkeypatch):
    _enable_imd(monkeypatch)
    assert _imd_configured() is True


def test_imd_provider_class_reflects_config_status(monkeypatch):
    imd = IMDProvider()
    _disable_imd(monkeypatch)
    assert imd.configured() is False
    assert imd.status() == "NOT_CONFIGURED"

    _enable_imd(monkeypatch)
    assert imd.configured() is True
    assert imd.status() == "LIVE"
    assert imd.role == "legacy"
    assert imd.dataset == "IMD Mausam (Current Weather)"


def test_imd_provider_fetch_many_refuses_grid(monkeypatch):
    imd = IMDProvider()
    with pytest.raises(HttpFetchError):
        imd.fetch_many([(30.42, 79.35)], [0], days=1)


def test_provider_chain_orders_imd_first(monkeypatch):
    _enable_imd(monkeypatch)
    chain = weather_service._provider_chain
    assert [p.name for p in chain] == ["IMD", "Open-Meteo", "ECMWF"]


def test_open_meteo_payload_carries_dataset_and_fetched_at(monkeypatch):
    _disable_imd(monkeypatch)

    def handler(url, params):
        return FakeResponse(payload=OPEN_METEO_BODY)

    _patch_http(monkeypatch, handler)
    payload = weather_service.get_weather(30.42, 79.35)
    assert payload["dataset"] == "Open-Meteo Global Forecast (GFS Seamless + ICON)"
    assert payload["fetched_at"].endswith("Z") and payload["fetched_at"]


def test_imd_payload_carries_dataset_and_fetched_at(monkeypatch):
    _enable_imd(monkeypatch)
    _patch_http(
        monkeypatch,
        lambda url, params: FakeResponse(payload={"data": {"temp_c": 21.0}}),
    )
    payload = weather_service.get_weather(28.61, 77.21)
    assert payload["dataset"] == "IMD Mausam (Current Weather)"
    assert payload["fetched_at"].endswith("Z") and payload["fetched_at"]


# ---------------- fallback default: Open-Meteo primary ----------------

def test_open_meteo_primary_when_imd_not_configured(monkeypatch):
    _disable_imd(monkeypatch)

    def handler(url, params):
        assert "open-meteo.com" in url
        assert params["latitude"] == 30.42
        return FakeResponse(payload=OPEN_METEO_BODY)

    _patch_http(monkeypatch, handler)

    payload = weather_service.get_weather(30.42, 79.35)
    assert payload["data_status"] == "LIVE"
    assert payload["data_source"] == "Open-Meteo"
    assert payload["provider"] == "Open-Meteo"
    assert payload["provider_role"] == "primary"
    assert payload["current"]["temperature_c"] == 19.5
    assert payload["current"]["rain_intensity"] == "LIGHT"
    assert payload["current"]["pressure_hpa"] == 1009.0
    assert payload["current"]["cloud_cover_percent"] == 70
    assert payload["current"]["wind_direction_deg"] == 190
    assert payload["elevation_actual"] == 1250.0
    assert payload["timezone"] == "Asia/Kolkata"
    assert isinstance(payload["units"], dict)
    assert len(payload["hourly"]) == 1
    assert len(payload["forecast"]) == 1
    assert payload["forecast"][0]["weather_code"] == 61


# ---------------- IMD legacy primary (opt-in, backward compatible) ----------------

def test_imd_primary_when_configured_and_usable(monkeypatch):
    _enable_imd(monkeypatch)

    def handler(url, params):
        assert "mausam" in url and url.endswith("/currweather/location")
        assert params["token"] == "fake-token"
        assert params["lat"] == 30.42
        return FakeResponse(
            payload={
                "response": [
                    {
                        "data": [
                            {
                                "stationName": "Chamoli",
                                "lat": "30.42",
                                "lon": "79.35",
                                "temp": "18.2",
                                "humidity": "88",
                                "weatherDesc": "Light Rain",
                                "time": "2026-09-19 08:30",
                            }
                        ]
                    }
                ]
            }
        )

    _patch_http(monkeypatch, handler)

    payload = weather_service.get_weather(30.42, 79.35)
    assert payload["data_status"] == "LIVE"
    assert payload["data_source"].startswith("IMD")
    assert payload["provider_role"] == "legacy"
    assert payload["observed_at"] == "2026-09-19 08:30"
    assert payload["current"]["temperature_c"] == 18.2
    assert payload["current"]["relative_humidity_percent"] == 88
    assert payload["current"]["rain_intensity"] == "LIGHT"
    assert payload["current"]["weather_description"] == "Light Rain"


def test_imd_primary_no_forecast_but_live_current(monkeypatch):
    _enable_imd(monkeypatch)
    _patch_http(
        monkeypatch,
        lambda url, params: FakeResponse(
            payload={"data": {"temp_c": 21.0, "weather_desc": "Heavy Rain"}}
        ),
    )
    payload = weather_service.get_weather(28.61, 77.21)
    assert payload["data_status"] == "LIVE"
    assert payload["current"]["rain_intensity"] == "HEAVY"
    assert payload["forecast"] == []


def test_imd_rejection_falls_back_to_open_meteo(monkeypatch):
    _enable_imd(monkeypatch)

    calls = []

    def handler(url, params):
        calls.append(url)
        if "mausam" in url:
            return FakeResponse(status_code=401, payload={})
        return FakeResponse(payload=OPEN_METEO_BODY)

    _patch_http(monkeypatch, handler)

    payload = weather_service.get_weather(30.42, 79.35)
    assert payload["data_status"] == "LIVE"
    assert payload["data_source"] == "Open-Meteo (IMD fallback)"
    assert payload["current"]["temperature_c"] == 19.5
    assert "IMD" in (payload.get("reason") or "")
    assert len(calls) == 2


def test_imd_unparseable_falls_back_to_open_meteo(monkeypatch):
    _enable_imd(monkeypatch)

    def handler(url, params):
        if "mausam" in url:
            return FakeResponse(payload={"status": "error", "message": "no data"})
        return FakeResponse(payload=OPEN_METEO_BODY)

    _patch_http(monkeypatch, handler)

    payload = weather_service.get_weather(30.42, 79.35)
    assert payload["data_status"] == "LIVE"
    assert payload["data_source"] == "Open-Meteo (IMD fallback)"
    assert "no usable current weather" in (payload.get("reason") or "")


def test_imd_non_json_falls_back_to_open_meteo(monkeypatch):
    _enable_imd(monkeypatch)

    def handler(url, params):
        if "mausam" in url:
            return FakeResponse(payload=None, raw="<html>gateway</html>")
        return FakeResponse(payload=OPEN_METEO_BODY)

    _patch_http(monkeypatch, handler)

    payload = weather_service.get_weather(30.42, 79.35)
    assert payload["data_status"] == "LIVE"
    assert payload["data_source"] == "Open-Meteo (IMD fallback)"


# ---------------- ECMWF backup (default chain) ----------------

ECMWF_BODY = {
    "current": {
        "temperature_2m": 18.9,
        "precipitation": 0.4,
        "weather_code": 2,
        "wind_speed_10m": 7.0,
        "wind_gusts_10m": 13.0,
        "cloud_cover": 40,
        "time": "2026-09-19T10:00",
    },
    "daily": {
        "time": ["2026-09-19", "2026-09-20"],
        "temperature_2m_max": [22.0, 23.5],
        "temperature_2m_min": [12.5, 13.9],
        "precipitation_sum": [0.4, 1.1],
        "wind_speed_10m_max": [14.0, 15.0],
        "weather_code": [2, 61],
    },
    "timezone": "Asia/Kolkata",
    "elevation": 1240.0,
    "generationtime_ms": 9.1,
}


def test_ecmwf_backup_when_open_meteo_unreachable(monkeypatch):
    _disable_imd(monkeypatch)
    calls = []

    def handler(url, params):
        calls.append(url)
        if "mausam" in url:
            return FakeResponse(status_code=500, payload={})
        # ECMWF backup selects the model via the standard /forecast contract.
        if params and params.get("models") == "ecmwf_ifs025":
            return FakeResponse(payload=ECMWF_BODY)
        return FakeResponse(status_code=500, payload={})

    _patch_http(monkeypatch, handler)

    payload = weather_service.get_weather(30.42, 79.35)
    assert payload["data_status"] == "LIVE"
    assert payload["data_source"] == "ECMWF (Open-Meteo backup)"
    assert payload["provider"] == "ECMWF"
    assert payload["provider_role"] == "backup"
    assert payload["current"]["temperature_c"] == 18.9
    # Variables ECMWF does not provide are honestly null — never fabricated.
    assert payload["current"]["relative_humidity_percent"] is None
    assert payload["current"]["pressure_hpa"] is None
    assert payload["current"]["weather_description"] == "Partly cloudy"
    assert "ECMWF" in (payload.get("reason") or "")
    assert len(payload["forecast"]) == 2


# ---------------- both providers fail: honest UNAVAILABLE ----------------

def test_both_providers_fail_returns_unavailable(monkeypatch):
    _enable_imd(monkeypatch)

    def handler(url, params):
        return FakeResponse(status_code=500, payload={})

    _patch_http(monkeypatch, handler)

    payload = weather_service.get_weather(30.42, 79.35)
    assert payload["data_status"] == "UNAVAILABLE"
    assert payload["current"] is None
    assert payload["forecast"] == []
    assert payload["provider_role"] is None
    assert "IMD primary unavailable" in (payload.get("reason") or "")
    assert "upstream unreachable" in (payload.get("reason") or "")


def test_open_meteo_fail_no_imd_returns_unavailable(monkeypatch):
    _disable_imd(monkeypatch)

    def handler(url, params):
        return FakeResponse(status_code=500, payload={})

    _patch_http(monkeypatch, handler)

    payload = weather_service.get_weather(30.42, 79.35)
    assert payload["data_status"] == "UNAVAILABLE"
    assert payload["current"] is None
    assert "upstream unreachable" in (payload.get("reason") or "")


# ---------------- cache hit bypasses upstream ----------------

def test_cached_response_avoids_upstream(monkeypatch):
    _disable_imd(monkeypatch)
    calls = []

    def handler(url, params):
        calls.append(url)
        return FakeResponse(payload=OPEN_METEO_BODY)

    _patch_http(monkeypatch, handler)

    weather_service.get_weather(30.42, 79.35)
    weather_service.get_weather(30.42, 79.35)
    assert len(calls) == 1

    # A different coordinate is a different cache entry.
    weather_service.get_weather(28.61, 77.21)
    assert len(calls) == 2


def test_days_param_changes_cache_key(monkeypatch):
    _disable_imd(monkeypatch)
    calls = []

    def handler(url, params):
        calls.append(url)
        return FakeResponse(payload=OPEN_METEO_BODY)

    _patch_http(monkeypatch, handler)

    weather_service.get_weather(30.42, 79.35, days=7)
    weather_service.get_weather(30.42, 79.35, days=3)
    assert len(calls) == 2


# ---------------- batch (grid cells) ----------------

def test_batch_multi_location_parsing(monkeypatch):
    _disable_imd(monkeypatch)

    def handler(url, params):
        lats = params["latitude"]
        assert "," in lats  # multi-location request
        count = len(lats.split(","))
        assert params["timezone"] == "UTC"
        return FakeResponse(payload=[OPEN_METEO_BODY for _ in range(count)])

    _patch_http(monkeypatch, handler)

    results = weather_service.get_weather_batch(
        [(30.42, 79.35), (28.61, 77.21), (12.09, 79.69)]
    )
    assert len(results) == 3
    assert all(r["data_status"] == "LIVE" for r in results.values())
    assert results[1]["current"]["temperature_c"] == 19.5


def test_batch_reuses_per_point_cache(monkeypatch):
    _disable_imd(monkeypatch)
    calls = []

    def handler(url, params):
        calls.append(url)
        lat = params.get("latitude")
        count = len(str(lat).split(","))
        return FakeResponse(payload=[OPEN_METEO_BODY for _ in range(count)])

    _patch_http(monkeypatch, handler)

    weather_service.get_weather(30.42, 79.35)
    results = weather_service.get_weather_batch([(30.42, 79.35), (28.61, 77.21)])
    assert len(results) == 2
    # First cell was cached by get_weather; only the second hit upstream.
    assert len(calls) == 2
    assert calls[0]  # first call from get_weather
    assert calls[1]  # batch only fetched the missing cell


# ---------------- grid sampling ----------------

def _grid_payloads(lat_count):
    return [
        {
            "current": {
                "temperature_2m": 17.0 + 0.5 * i,
                "precipitation": 1.0 + i,
                "weather_code": 61,
                "wind_speed_10m": 6.0,
                "wind_gusts_10m": 22.0 + i,
                "cloud_cover": 55.0 + i,
                "relative_humidity_2m": 80,
                "pressure_msl": 1010.0,
                "time": "2026-09-19T10:00",
            },
            "hourly": {
                "time": [f"2026-09-19T{h:02d}:00" for h in range(48)],
                "temperature_2m": [15.0 + h for h in range(48)],
                "precipitation": [float(h % 4) for h in range(48)],
                "precipitation_probability": [(h * 2) % 101 for h in range(48)],
                "weather_code": [0] * 48,
                "wind_speed_10m": [8.0] * 48,
                "wind_gusts_10m": [30.0] * 48,
                "relative_humidity_2m": [70.0] * 48,
                "cloud_cover": [40.0] * 48,
            },
            "daily": {
                "time": ["2026-09-19", "2026-09-20"],
                "temperature_2m_max": [23.0, 24.0],
                "temperature_2m_min": [13.0, 14.0],
                "precipitation_sum": [2.0, 0.0],
                "precipitation_probability_max": [70, 30],
                "wind_speed_10m_max": [16.0, 14.0],
                "weather_code": [61, 0],
            },
            "timezone": "Asia/Kolkata",
            "elevation": 300.0,
        }
        for i in range(lat_count)
    ]


def test_grid_samples_live(monkeypatch):
    _disable_imd(monkeypatch)

    def handler(url, params):
        count = len(params["latitude"].split(","))
        return FakeResponse(payload=_grid_payloads(count))

    _patch_http(monkeypatch, handler)

    grid = weather_service.get_grid_samples(
        north=30.8, south=30.0, east=80.0, west=78.0, step=0.5, max_points=600,
        variable="temperature_2m", day=0,
    )
    assert grid["data_status"] == "LIVE"
    assert grid["provider"] == "Open-Meteo"
    assert grid["provider_role"] == "primary"
    assert grid["variable"] == "temperature_2m"
    assert grid["unit"] == "°C"
    assert grid["points"]
    for point in grid["points"]:
        assert point["value"] is not None
        assert "latitude" in point and "longitude" in point


def test_grid_samples_daily_day(monkeypatch):
    _disable_imd(monkeypatch)

    def handler(url, params):
        count = len(params["latitude"].split(","))
        return FakeResponse(payload=_grid_payloads(count))

    _patch_http(monkeypatch, handler)

    grid = weather_service.get_grid_samples(
        north=30.3, south=30.0, east=78.5, west=78.0, step=0.3, max_points=600,
        variable="precipitation_probability", day=1,
    )
    assert grid["day"] == 1
    assert all(p["value"] == 70 for p in grid["points"])


def test_grid_humidity_not_available_on_forecast_day(monkeypatch):
    _disable_imd(monkeypatch)

    def handler(url, params):
        count = len(params["latitude"].split(","))
        return FakeResponse(payload=_grid_payloads(count))

    _patch_http(monkeypatch, handler)

    grid = weather_service.get_grid_samples(
        north=30.3, south=30.0, east=78.5, west=78.0, step=0.3, max_points=600,
        variable="relative_humidity", day=2,
    )
    # Forecast days have no humidity — every cell is honestly "no value".
    assert all(p["value"] is None for p in grid["points"])


def test_grid_clamped_to_india_returns_unavailable_outside(monkeypatch):
    _disable_imd(monkeypatch)

    def handler(url, params):
        count = len(params["latitude"].split(","))
        return FakeResponse(payload=_grid_payloads(count))

    _patch_http(monkeypatch, handler)

    # Entirely outside the India window (south of lat 6).
    grid = weather_service.get_grid_samples(
        north=5.0, south=4.0, east=70.0, west=69.0, step=0.1, max_points=600,
        variable="temperature_2m", day=0,
    )
    assert grid["data_status"] == "UNAVAILABLE"
    assert grid["points"] == []


def test_grid_cache_avoids_upstream(monkeypatch):
    _disable_imd(monkeypatch)
    calls = []

    def handler(url, params):
        calls.append(url)
        count = len(params["latitude"].split(","))
        return FakeResponse(payload=_grid_payloads(count))

    _patch_http(monkeypatch, handler)

    weather_service.get_grid_samples(
        north=30.3, south=30.0, east=78.5, west=78.0, step=0.3, max_points=600,
        variable="temperature_2m", day=0,
    )
    n_before = len(calls)
    weather_service.get_grid_samples(
        north=30.3, south=30.0, east=78.5, west=78.0, step=0.3, max_points=600,
        variable="temperature_2m", day=0,
    )
    assert len(calls) == n_before  # grid-level cache hit, zero upstream calls


def test_grid_nationwide_subsamples_evenly_across_full_extent(monkeypatch):
    _disable_imd(monkeypatch)

    def handler(url, params):
        count = len(params["latitude"].split(","))
        return FakeResponse(payload=_grid_payloads(count))

    _patch_http(monkeypatch, handler)

    grid = weather_service.get_grid_samples(
        north=37.4, south=6.0, east=98.5, west=68.0, step=0.5, max_points=600,
        variable="temperature_2m", day=0,
    )
    assert grid["data_status"] == "LIVE"
    # Whole of India must fit inside the point budget without being clipped.
    assert 0 < len(grid["points"]) <= 600
    assert all(p["value"] is not None for p in grid["points"])
    lats = sorted({p["latitude"] for p in grid["points"]})
    lngs = sorted({p["longitude"] for p in grid["points"]})
    # The grid still spans the full requested extent (never a northern-only band).
    assert abs(lats[-1] - 37.4) < 1e-5  # northern edge kept
    assert abs(lngs[-1] - 98.5) < 1e-5  # eastern edge kept
    assert lats[0] <= 6.5               # southern point retained
    assert lngs[0] <= 68.5              # western point retained


def test_grid_day0_gust_and_cloud_from_current_block(monkeypatch):
    _disable_imd(monkeypatch)

    def handler(url, params):
        count = len(params["latitude"].split(","))
        return FakeResponse(payload=_grid_payloads(count))

    _patch_http(monkeypatch, handler)

    gust = weather_service.get_grid_samples(
        north=30.3, south=30.0, east=78.5, west=78.0, step=0.3, max_points=600,
        variable="wind_gusts_10m", day=0,
    )
    assert gust["data_status"] == "LIVE"
    assert gust["unit"] == "km/h"
    assert all(p["value"] is not None for p in gust["points"])
    assert gust["points"][0]["value"] == 22.0

    cloud = weather_service.get_grid_samples(
        north=30.3, south=30.0, east=78.5, west=78.0, step=0.3, max_points=600,
        variable="cloud_cover", day=0,
    )
    assert cloud["data_status"] == "LIVE"
    assert cloud["points"][0]["value"] == 55.0


def test_grid_gust_and_cloud_unavailable_on_future_day(monkeypatch):
    _disable_imd(monkeypatch)

    def handler(url, params):
        count = len(params["latitude"].split(","))
        return FakeResponse(payload=_grid_payloads(count))

    _patch_http(monkeypatch, handler)

    grid = weather_service.get_grid_samples(
        north=30.3, south=30.0, east=78.5, west=78.0, step=0.3, max_points=600,
        variable="wind_gusts_10m", day=2,
    )
    # Gusts/clouds are a current-conditions block — future days are honestly null.
    assert all(p["value"] is None for p in grid["points"])


def test_grid_hour_intraday_uses_hourly_block(monkeypatch):
    _disable_imd(monkeypatch)
    seen_params = {}

    def handler(url, params):
        seen_params.update(params)
        count = len(params["latitude"].split(","))
        return FakeResponse(payload=_grid_payloads(count))

    _patch_http(monkeypatch, handler)

    grid = weather_service.get_grid_samples(
        north=30.3, south=30.0, east=78.5, west=78.0, step=0.3, max_points=600,
        variable="temperature_2m", hour=6,
    )
    assert grid["data_status"] == "FORECAST"
    assert grid["hour"] == 6
    assert grid["day"] == 0
    assert "hourly" in seen_params
    assert "--" not in seen_params["hourly"]
    # hourly[6] of the stub block: temperature_2m = 15.0 + 6 = 21.0
    assert all(p["value"] == 21.0 for p in grid["points"])


def test_grid_hour_accumulation_and_storm_indicator(monkeypatch):
    _disable_imd(monkeypatch)

    def handler(url, params):
        count = len(params["latitude"].split(","))
        payloads = _grid_payloads(count)
        # Row 0 -> thunderstorm code, row 1 -> violent thunderstorm code.
        for p in payloads:
            p["hourly"]["weather_code"] = [96, 99, 0] + [0] * 45
        return FakeResponse(payload=payloads)

    _patch_http(monkeypatch, handler)

    storm = weather_service.get_grid_samples(
        north=30.3, south=30.0, east=78.5, west=78.0, step=0.3, max_points=600,
        variable="storm_indicator", hour=1,
    )
    assert all(p["value"] == 2 for p in storm["points"])
    assert storm["unit"] == "index"

    accel = weather_service.get_grid_samples(
        north=30.3, south=30.0, east=78.5, west=78.0, step=0.3, max_points=600,
        variable="precipitation_accumulation", hour=3,
    )
    # hourly precipitation proxy at h3 == 3 % 4 == 3.0
    assert all(p["value"] == 3.0 for p in accel["points"])
    assert accel["unit"] == "mm"


def test_grid_hour_humidity_stays_null_per_hour(monkeypatch):
    _disable_imd(monkeypatch)

    def handler(url, params):
        count = len(params["latitude"].split(","))
        return FakeResponse(payload=_grid_payloads(count))

    _patch_http(monkeypatch, handler)

    grid = weather_service.get_grid_samples(
        north=30.3, south=30.0, east=78.5, west=78.0, step=0.3, max_points=600,
        variable="relative_humidity", hour=3,
    )
    # The hourly block has no per-hour humidity factor here by design of the
    # provider contract — cells must stay honestly null.
    assert all(p["value"] is None for p in grid["points"])


def test_grid_hour_rejects_out_of_range(monkeypatch):
    _disable_imd(monkeypatch)

    def handler(url, params):
        count = len(params["latitude"].split(","))
        return FakeResponse(payload=_grid_payloads(count))

    _patch_http(monkeypatch, handler)

    try:
        weather_service.get_grid_samples(
            north=30.3, south=30.0, east=78.5, west=78.0, step=0.3, max_points=600,
            variable="temperature_2m", hour=48,
        )
        raise AssertionError("expected ValueError for hour out of range")
    except ValueError:
        pass


def test_grid_hour_and_day_are_separate_cache_keys(monkeypatch):
    _disable_imd(monkeypatch)
    calls = []

    def handler(url, params):
        calls.append(params.get("latitude"))
        count = len(params["latitude"].split(","))
        return FakeResponse(payload=_grid_payloads(count))

    _patch_http(monkeypatch, handler)

    for variable, offline in (
        ("temperature_2m", None),
        ("temperature_2m", 3),
        ("wind_gusts_10m", None),
        ("wind_gusts_10m", 3),
    ):
        weather_service.get_grid_samples(
            north=30.1, south=30.0, east=78.2, west=78.0, step=0.3, max_points=600,
            variable=variable, hour=offline,
        )
    # Two upstream fetches total: the day variant reuses the per-point cache and
    # the hour variant reuses the raw hourly block already fetched at h+3.
    assert len(calls) == 2


# ---------------- weather & hazard map grid extensions ----------------

def _grid_payloads_with_wind(lat_count):
    payloads = _grid_payloads(lat_count)
    for i, p in enumerate(payloads):
        p["current"]["wind_direction_10m"] = 270.0
        p["current"]["apparent_temperature"] = 21.0
        p["current"]["visibility"] = 12.0
        p["hourly"]["wind_direction_10m"] = [270.0] * 48
    return payloads


def test_grid_day0_derived_wind_components(monkeypatch):
    _disable_imd(monkeypatch)

    def handler(url, params):
        count = len(params["latitude"].split(","))
        return FakeResponse(payload=_grid_payloads_with_wind(count))

    _patch_http(monkeypatch, handler)

    u = weather_service.get_grid_samples(
        north=30.3, south=30.0, east=78.5, west=78.0, step=0.3, max_points=600,
        variable="wind_u", day=0,
    )
    v = weather_service.get_grid_samples(
        north=30.3, south=30.0, east=78.5, west=78.0, step=0.3, max_points=600,
        variable="wind_v", day=0,
    )
    assert u["data_status"] == "LIVE"
    assert u["derived"] is True and v["derived"] is True
    assert u["unit"] == "m/s"
    # speed 6.0 km/h (=1.6667 m/s), direction 270° (from west).
    # u = -ws*sin(270°) = +1.6667 ; v = -ws*cos(270°) ≈ 0.
    assert abs(u["points"][0]["value"] - (6.0 / 3.6)) < 0.01
    assert abs(v["points"][0]["value"]) < 0.01
    assert u["min"] is not None and u["max"] is not None


def test_grid_hour_derived_wind_components(monkeypatch):
    _disable_imd(monkeypatch)

    def handler(url, params):
        count = len(params["latitude"].split(","))
        return FakeResponse(payload=_grid_payloads_with_wind(count))

    _patch_http(monkeypatch, handler)

    u = weather_service.get_grid_samples(
        north=30.3, south=30.0, east=78.5, west=78.0, step=0.3, max_points=600,
        variable="wind_u", hour=3,
    )
    # hourly wind_speed_10m = 8.0 km/h, direction 270° → u = +2.2222
    assert u["data_status"] == "FORECAST"
    assert abs(u["points"][0]["value"] - (8.0 / 3.6)) < 0.01
    assert u["valid_time"] == "2026-09-19T03:00"
    assert u["derived"] is True


def test_grid_day0_direction_feelslike_visibility(monkeypatch):
    _disable_imd(monkeypatch)

    def handler(url, params):
        count = len(params["latitude"].split(","))
        return FakeResponse(payload=_grid_payloads_with_wind(count))

    _patch_http(monkeypatch, handler)

    direction = weather_service.get_grid_samples(
        north=30.3, south=30.0, east=78.5, west=78.0, step=0.3, max_points=600,
        variable="wind_direction_10m", day=0,
    )
    feels = weather_service.get_grid_samples(
        north=30.3, south=30.0, east=78.5, west=78.0, step=0.3, max_points=600,
        variable="apparent_temperature", day=0,
    )
    vis = weather_service.get_grid_samples(
        north=30.3, south=30.0, east=78.5, west=78.0, step=0.3, max_points=600,
        variable="visibility", day=0,
    )
    assert direction["unit"] == "°" and all(p["value"] == 270.0 for p in direction["points"])
    assert feels["unit"] == "°C" and all(p["value"] == 21.0 for p in feels["points"])
    assert vis["unit"] == "km" and all(p["value"] == 12.0 for p in vis["points"])


def test_grid_hour_feelslike_visibility_stay_null(monkeypatch):
    _disable_imd(monkeypatch)

    def handler(url, params):
        count = len(params["latitude"].split(","))
        return FakeResponse(payload=_grid_payloads_with_wind(count))

    _patch_http(monkeypatch, handler)

    feels = weather_service.get_grid_samples(
        north=30.3, south=30.0, east=78.5, west=78.0, step=0.3, max_points=600,
        variable="apparent_temperature", hour=3,
    )
    vis = weather_service.get_grid_samples(
        north=30.3, south=30.0, east=78.5, west=78.0, step=0.3, max_points=600,
        variable="visibility", hour=3,
    )
    # These layers are current-conditions only — hourly stops stay honestly null.
    assert all(p["value"] is None for p in feels["points"])
    assert all(p["value"] is None for p in vis["points"])


def test_grid_forecast_time_resolves_to_hour_offset(monkeypatch):
    _disable_imd(monkeypatch)

    def handler(url, params):
        count = len(params["latitude"].split(","))
        return FakeResponse(payload=_grid_payloads_with_wind(count))

    _patch_http(monkeypatch, handler)

    future = datetime.now(timezone.utc) + timedelta(hours=2)
    grid = weather_service.get_grid_samples(
        north=30.3, south=30.0, east=78.5, west=78.0, step=0.3, max_points=600,
        variable="wind_u", forecast_time=future.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    assert grid["hour"] == 2
    assert grid["data_status"] == "FORECAST"


def test_grid_forecast_time_rejects_non_iso(monkeypatch):
    _disable_imd(monkeypatch)
    try:
        weather_service.get_grid_samples(
            north=30.3, south=30.0, east=78.5, west=78.0, step=0.3, max_points=600,
            variable="temperature_2m", forecast_time="not-a-timestamp",
        )
        raise AssertionError("expected ValueError for non-ISO forecast_time")
    except ValueError:
        pass


def test_grid_prefer_ecmwf_serves_ecmwf_primary(monkeypatch):
    _disable_imd(monkeypatch)

    def handler(url, params):
        if params and (params.get("models") or "").startswith("ecmwf_ifs"):
            count = len(params["latitude"].split(","))
            return FakeResponse(payload=[ECMWF_BODY for _ in range(count)])
        return FakeResponse(status_code=500, payload={})

    _patch_http(monkeypatch, handler)

    grid = weather_service.get_grid_samples(
        north=30.3, south=30.0, east=78.5, west=78.0, step=0.3, max_points=600,
        variable="temperature_2m", day=0, prefer="ecmwf",
    )
    assert grid["data_status"] == "LIVE"
    assert grid["provider"] == "ECMWF"
    assert grid["provider_role"] == "primary"
    assert grid["data_source"].startswith("ECMWF IFS HRES 0.25°")
    assert all(p["value"] == 18.9 for p in grid["points"])


# ---------------- provider cooldown / dedup / CACHED relabel ----------------

def test_provider_cooldown_gates_requests_without_network(monkeypatch):
    _disable_imd(monkeypatch)
    _PROVIDER_COOLDOWN_UNTIL.clear()
    calls = []

    def handler(url, params):
        calls.append(url)
        count = len(params["latitude"].split(","))
        return FakeResponse(payload=_grid_payloads(count))

    _patch_http(monkeypatch, handler)

    try:
        _mark_provider_cooldown("Open-Meteo", 60)
        grid = weather_service.get_grid_samples(
            north=13.4, south=13.0, east=79.4, west=79.0, step=0.2, max_points=100,
            variable="temperature_2m", day=0,
        )
        # Open-Meteo gated by cooldown → ECMWF backup served; only one call made.
        assert grid["provider"] == "ECMWF"
        assert len(calls) == 1

        _mark_provider_cooldown("ECMWF", 60)
        grid = weather_service.get_grid_samples(
            north=14.2, south=13.8, east=79.4, west=79.0, step=0.2, max_points=100,
            variable="temperature_2m", day=0,
        )
        # Both providers gated → UNAVAILABLE with zero upstream calls.
        assert grid["data_status"] == "UNAVAILABLE"
        assert len(calls) == 1
    finally:
        _PROVIDER_COOLDOWN_UNTIL.clear()


def test_cached_success_grid_served_as_cached(monkeypatch):
    _disable_imd(monkeypatch)
    calls = []

    def handler(url, params):
        calls.append(url)
        count = len(params["latitude"].split(","))
        return FakeResponse(payload=_grid_payloads(count))

    _patch_http(monkeypatch, handler)

    first = weather_service.get_grid_samples(
        north=15.2, south=14.8, east=78.4, west=78.0, step=0.2, max_points=100,
        variable="temperature_2m", day=0,
    )
    assert first["data_status"] == "LIVE"
    assert len(calls) == 1

    second = weather_service.get_grid_samples(
        north=15.2, south=14.8, east=78.4, west=78.0, step=0.2, max_points=100,
        variable="temperature_2m", day=0,
    )
    assert second["data_status"] == "CACHED"
    assert second["data_source"] == first["data_source"]
    assert len(calls) == 1


def test_cached_point_served_as_cached(monkeypatch):
    _disable_imd(monkeypatch)
    calls = []

    def handler(url, params):
        calls.append(url)
        return FakeResponse(payload=OPEN_METEO_BODY)

    _patch_http(monkeypatch, handler)

    first = weather_service.get_weather(24.0, 84.2, days=1)
    assert first["data_status"] == "LIVE"
    assert len(calls) == 1

    second = weather_service.get_weather(24.0, 84.2, days=1)
    assert second["data_status"] == "CACHED"
    assert len(calls) == 1


def test_concurrent_same_grid_dedupes_to_single_fetch(monkeypatch):
    _disable_imd(monkeypatch)
    hits = []
    entered = threading.Event()
    release = threading.Event()
    results: dict[int, dict] = {}
    errors: list[BaseException] = []

    def handler(url, params):
        hits.append(url)
        entered.set()
        # Hold the leader in-flight so the second thread has time to overlap.
        release.wait(timeout=10)
        count = len(params["latitude"].split(","))
        return FakeResponse(payload=_grid_payloads(count))

    _patch_http(monkeypatch, handler)

    def worker(idx):
        try:
            results[idx] = weather_service.get_grid_samples(
                north=16.4, south=16.0, east=78.4, west=78.0, step=0.2, max_points=100,
                variable="temperature_2m", day=0,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    first = threading.Thread(target=worker, args=(0,))
    first.start()
    assert entered.wait(timeout=10)
    second = threading.Thread(target=worker, args=(1,))
    second.start()
    time.sleep(0.3)
    release.set()
    first.join(timeout=30)
    second.join(timeout=30)

    assert not errors
    # Both threads must see a served grid and only one upstream fetch fires.
    assert all(r["data_status"] in ("LIVE", "CACHED") for r in results.values())
    assert results[0]["provider"] == results[1]["provider"] == "Open-Meteo"
    assert len(hits) == 1 and len(results) == 2


def test_grid_forecast_day_is_forecast_not_live(monkeypatch):
    _disable_imd(monkeypatch)

    def handler(url, params):
        count = len(params["latitude"].split(","))
        return FakeResponse(payload=_grid_payloads(count))

    _patch_http(monkeypatch, handler)

    grid = weather_service.get_grid_samples(
        north=17.4, south=17.0, east=78.4, west=78.0, step=0.2, max_points=100,
        variable="temperature_2m", day=1,
    )
    assert grid["day"] == 1
    assert grid["data_status"] == "FORECAST"
    assert all(p["value"] is not None for p in grid["points"])