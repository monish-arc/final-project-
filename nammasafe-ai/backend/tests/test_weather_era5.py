"""
Tests for the historical ERA5 weather provider and the new Phase A/B API
surface:

  * completed-month gating (the current year only serves finished months —
    "nothing is invented for a partial month"),
  * honest UNAVAILABLE paths (archive unreachable, variable not exposed,
    month not completed) — never fabricated values,
  * the weather_access gate: every weather/rainfall endpoint is reachable by
    every role (weather.history.read is granted role-wide, citizens included),
  * API_NOT_ADDED live payloads when the live weather API is disabled,
  * the historical flood-risk overlay (ERA5 + SRTM) computed from real inputs,
  * the real-data catalog surface.

Upstream archive + terrain transports are stubbed (as transports, never as
user-facing measurements) so no network escapes the test run.
"""

from calendar import monthrange, timegm
from typing import Dict, Optional

import pytest

from app import config
from app import historical_weather as historical_weather_mod
from app.historical_weather import (
    HISTORICAL_PROVIDER_NAME,
    HISTORICAL_SOURCE,
    _DAILY_COLUMNS,
    _INCOMPLETE_MONTH_REASON,
    available_periods,
    completed_through_month_for_year,
)

SEP_2026_UTC = timegm((2026, 9, 26, 0, 0, 0))


def _era5_daily_stub(latitudes, longitudes, year, month):
    """Synthetic ERA5 *transport* response: flattened daily block arrays of
    length len(latitudes) * days (index = cell * days + day)."""
    days = monthrange(int(year), int(month))[1]
    n = len(latitudes)
    rows = {col: [] for col in [*_DAILY_COLUMNS, "time"]}
    for i in range(n):
        for d in range(1, days + 1):
            rows["time"].append(f"{int(year)}-{int(month):02d}-{d:02d}")
            rows["temperature_2m_mean"].append(18.0 + i + (d % 5))
            rows["temperature_2m_max"].append(24.0 + i + (d % 5))
            rows["temperature_2m_min"].append(12.0 + i)
            rows["precipitation_sum"].append(0.0 if d % 3 == 0 else 2.0)
            rows["rain_sum"].append(0.0 if d % 3 == 0 else 2.0)
            rows["snowfall_sum"].append(0.0)
            rows["precipitation_hours"].append(0.0 if d % 3 == 0 else 4.0)
            rows["weather_code"].append(95 if d == 10 else 0)
            rows["wind_speed_10m_max"].append(20.0 + i)
            rows["wind_gusts_10m_max"].append(30.0 + i)
            rows["wind_direction_10m_dominant"].append(270.0)
            rows["surface_pressure_mean"].append(1012.0 + i)
            rows["apparent_temperature_mean"].append(20.0 + i + (d % 5))
            rows["cloud_cover_mean"].append(50.0 + i)
    return rows


def _era5_day_stub(latitudes, longitudes, year, month, day):
    """Synthetic ERA5 transport response for ONE completed day (per-day grid):
    flattened daily arrays of length len(latitudes), index = cell."""
    n = len(latitudes)
    rows = {col: [] for col in [*_DAILY_COLUMNS, "time"]}
    for i in range(n):
        rows["time"].append(f"{int(year)}-{int(month):02d}-{int(day):02d}")
        rows["temperature_2m_mean"].append(18.0 + i + (int(day) % 5))
        rows["temperature_2m_max"].append(24.0 + i + (int(day) % 5))
        rows["temperature_2m_min"].append(12.0 + i)
        rows["precipitation_sum"].append(0.0 if int(day) % 3 == 0 else 2.0)
        rows["rain_sum"].append(0.0 if int(day) % 3 == 0 else 2.0)
        rows["snowfall_sum"].append(0.0)
        rows["precipitation_hours"].append(0.0 if int(day) % 3 == 0 else 4.0)
        rows["weather_code"].append(95 if int(day) == 10 else 0)
        rows["wind_speed_10m_max"].append(20.0 + i)
        rows["wind_gusts_10m_max"].append(30.0 + i)
        rows["wind_direction_10m_dominant"].append(270.0)
        rows["surface_pressure_mean"].append(1012.0 + i)
        rows["apparent_temperature_mean"].append(20.0 + i + (int(day) % 5))
        rows["cloud_cover_mean"].append(50.0 + i)
    return rows


@pytest.fixture
def era5_freezer(monkeypatch):
    """Freeze 'now' at 2026-09-26 and stub the archive transport."""
    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    monkeypatch.setattr(
        historical_weather_mod.historical_weather,
        "_fetch_month_daily",
        _era5_daily_stub,
    )
    return historical_weather_mod.historical_weather


# ---------------- completed-month gating (service level) ----------------

def test_completed_through_month_for_fixed_now():
    assert completed_through_month_for_year(2024, SEP_2026_UTC) == 12
    assert completed_through_month_for_year(2025, SEP_2026_UTC) == 12
    assert completed_through_month_for_year(2026, SEP_2026_UTC) == 8
    assert completed_through_month_for_year(2027, SEP_2026_UTC) == 0


def test_available_periods_surfaces_current_partial_year(era5_freezer):
    availability = available_periods()
    years = [a["year"] for a in availability]
    assert years == list(range(config.HISTORICAL_YEAR_MIN, config.HISTORICAL_YEAR_MAX + 1))
    by_year = {a["year"]: a for a in availability}
    assert by_year[2025]["completed_through_month"] == 12
    assert by_year[2025]["status"] == "FULL"
    assert by_year[2026]["completed_through_month"] == 8
    assert by_year[2026]["status"] == "PARTIAL_COMPLETED"
    assert "Jan–08 completed" in by_year[2026]["label"]


# ---------------- point month ----------------

def test_fetch_point_month_completed_is_historical(era5_freezer):
    payload = historical_weather_mod.historical_weather.fetch_point_month(30.42, 79.35, 2025, 6)
    assert payload["data_status"] == "HISTORICAL"
    assert payload["is_historical"] is True
    assert payload["year"] == 2025 and payload["month"] == 6
    assert payload["provider_role"] == "historical"
    assert payload["dataset"].startswith("ECMWF ERA5")
    # June has 30 days; d%3==0 is dry, so 20 wet days at 2.0mm -> 40.0mm total.
    assert payload["variables"]["precipitation"]["value"] == 40.0
    assert payload["variables"]["precipitation"]["aggregation"] == "monthly_total"
    assert payload["variables"]["rain_days"]["value"] == 20
    assert payload["variables"]["thunderstorm_days"]["value"] == 1
    assert len(payload["daily"]) == 30
    assert payload["top_rain_day"]["mm"] == 2.0
    assert payload["top_rain_day"]["date"] == "2025-06-01"
    # The ERA5 daily archive exposes mean daily temperature, apparent
    # temperature and cloud cover — monthly means are honest real values.
    # Only humidity and visibility are not exposed and stay unavailable.
    assert payload["variables"]["apparent_temperature"]["available"] is True
    assert payload["variables"]["apparent_temperature"]["value"] == 22.0
    assert payload["variables"]["cloud_cover"]["available"] is True
    assert payload["variables"]["cloud_cover"]["value"] == 50.0
    for missing in ("relative_humidity", "visibility"):
        assert payload["variables"][missing]["available"] is False
        assert payload["variables"][missing]["reason"]


def test_fetch_point_month_incomplete_current_month_is_unavailable(era5_freezer):
    payload = historical_weather_mod.historical_weather.fetch_point_month(30.42, 79.35, 2026, 9)
    assert payload["data_status"] == "UNAVAILABLE"
    assert payload["variables"] == {}
    assert payload["daily"] == []
    assert _INCOMPLETE_MONTH_REASON in payload["reason"]


def test_fetch_point_month_past_year_full_12(era5_freezer):
    payload = historical_weather_mod.historical_weather.fetch_point_month(30.42, 79.35, 2025, 12)
    assert payload["data_status"] == "HISTORICAL"
    assert len(payload["daily"]) == 31


def test_fetch_point_month_top_rain_day_is_real_date(monkeypatch):
    """The wettest day's date must be the actual wettest day (mid-month here),
    not a hard-coded first-of-month."""
    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    provider = historical_weather_mod.HistoricalWeatherProvider(db_cache=False)
    base = _era5_daily_stub([30.42], [79.35], 2025, 6)
    precip = [5.0 if d == 17 else 0.0 for d in range(1, 31)]
    base["precipitation_sum"] = precip
    base["rain_sum"] = list(precip)
    monkeypatch.setattr(
        provider,
        "_fetch_month_daily",
        lambda latitudes, longitudes, year, month: base,
    )
    payload = provider.fetch_point_month(30.42, 79.35, 2025, 6)
    assert payload["top_rain_day"]["mm"] == 5.0
    assert payload["top_rain_day"]["date"] == "2025-06-17"


def test_fetch_point_month_dry_month_has_no_top_rain(monkeypatch):
    """A month with no rain has no wettest day (honest None, not 'day 1, 0 mm')."""
    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    provider = historical_weather_mod.HistoricalWeatherProvider(db_cache=False)
    base = _era5_daily_stub([30.42], [79.35], 2025, 6)
    base["precipitation_sum"] = [0.0] * 30
    base["rain_sum"] = [0.0] * 30
    monkeypatch.setattr(
        provider,
        "_fetch_month_daily",
        lambda latitudes, longitudes, year, month: base,
    )
    payload = provider.fetch_point_month(30.42, 79.35, 2025, 6)
    assert payload["top_rain_day"] is None
    assert payload["data_status"] == "HISTORICAL"
    assert payload["variables"]["precipitation"]["value"] == 0.0


# ---------------- grid ----------------

def test_fetch_grid_historical_variable(era5_freezer):
    grid = historical_weather_mod.historical_weather.fetch_grid(
        north=30.6, south=30.0, east=80.0, west=78.0,
        step=0.5, max_points=600, variable="precipitation",
        year=2025, month=6,
    )
    assert grid["data_status"] == "HISTORICAL"
    assert grid["is_historical"] is True
    assert grid["year"] == 2025 and grid["month"] == 6
    assert grid["unit"] == "mm"
    assert all(p["data_status"] == "HISTORICAL" for p in grid["points"])
    assert all(p["value"] == 40.0 for p in grid["points"])
    assert grid["min"] == 40.0 and grid["max"] == 40.0
    assert grid["data_provenance"]["source"] == HISTORICAL_SOURCE
    assert grid["data_provenance"]["year"] == 2025
    assert grid["data_provenance"]["aggregation"] == "monthly_total"


def test_fetch_grid_unavailable_variable_is_honest_no_network(monkeypatch):
    calls = {"n": 0}
    def boom(latitudes, longitudes, year, month):
        calls["n"] += 1
        raise AssertionError("unavailable variables must not be fetched")
    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    monkeypatch.setattr(historical_weather_mod.historical_weather, "_fetch_month_daily", boom)
    for variable in ("relative_humidity", "visibility", "precipitation_probability"):
        grid = historical_weather_mod.historical_weather.fetch_grid(
            north=30.6, south=30.0, east=80.0, west=78.0,
            step=0.5, max_points=600, variable=variable,
            year=2025, month=6,
        )
        assert grid["data_status"] == "UNAVAILABLE"
        assert calls["n"] == 0
        assert all(p["reason"] for p in grid["points"])


def test_fetch_grid_incomplete_month_is_unavailable_no_network(monkeypatch):
    calls = {"n": 0}
    def boom(latitudes, longitudes, year, month):
        calls["n"] += 1
        raise AssertionError("incomplete months must not be fetched")
    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    monkeypatch.setattr(historical_weather_mod.historical_weather, "_fetch_month_daily", boom)
    grid = historical_weather_mod.historical_weather.fetch_grid(
        north=30.6, south=30.0, east=80.0, west=78.0,
        step=0.5, max_points=600, variable="precipitation",
        year=2026, month=9,
    )
    assert grid["data_status"] == "UNAVAILABLE"
    assert calls["n"] == 0
    assert _INCOMPLETE_MONTH_REASON in grid["reason"]


# ---------------- grid: per-day playback ----------------

def test_fetch_grid_day_uses_that_days_value(monkeypatch):
    """Changing `day` changes the served raster — the grid endpoint is per-day."""
    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    calls: Dict[str, Optional[int]] = {"day": None}
    def day_stub(latitudes, longitudes, year, month, day):
        calls["day"] = int(day)
        return _era5_day_stub(latitudes, longitudes, int(year), int(month), int(day))
    monkeypatch.setattr(historical_weather_mod.historical_weather, "_fetch_day_daily", day_stub)
    grid = historical_weather_mod.historical_weather.fetch_grid(
        north=30.6, south=30.0, east=80.0, west=78.0,
        step=0.5, max_points=600, variable="precipitation",
        year=2025, month=6, day=13,
    )
    assert calls["day"] == 13
    assert grid["data_status"] == "HISTORICAL"
    assert grid["is_historical"] is True
    assert grid["day"] == 13
    assert grid["valid_time"] == "2025-06-13"
    assert grid["unit"] == "mm"
    assert grid["data_provenance"]["period"] == "2025-06-13"
    assert grid["data_provenance"]["aggregation"] == "daily_total"
    assert all(p["data_status"] == "HISTORICAL" for p in grid["points"])
    assert all(p["value"] == 2.0 for p in grid["points"])
    assert grid["min"] == 2.0 and grid["max"] == 2.0


def test_fetch_grid_day_temperature_value(monkeypatch):
    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    monkeypatch.setattr(
        historical_weather_mod.historical_weather, "_fetch_day_daily", _era5_day_stub
    )
    grid = historical_weather_mod.historical_weather.fetch_grid(
        north=30.6, south=30.0, east=80.0, west=78.0,
        step=0.5, max_points=600, variable="temperature_2m",
        year=2025, month=6, day=12,
    )
    # cell (30.0, 78.0): 18 + 0 + (12 % 5 = 2) -> 20.0
    assert grid["points"][0]["value"] == 20.0
    assert grid["unit"] == "°C"
    assert grid["data_provenance"]["aggregation"] == "day_value"


def test_fetch_grid_day_apparent_temperature_and_cloud_cover(monkeypatch):
    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    monkeypatch.setattr(
        historical_weather_mod.historical_weather, "_fetch_day_daily", _era5_day_stub
    )
    for variable, expected, unit in (
        ("apparent_temperature", 22.0, "°C"),
        ("cloud_cover", 50.0, "%"),
    ):
        grid = historical_weather_mod.historical_weather.fetch_grid(
            north=30.6, south=30.0, east=80.0, west=78.0,
            step=0.5, max_points=600, variable=variable,
            year=2025, month=6, day=7,
        )
        assert grid["data_status"] == "HISTORICAL"
        assert grid["points"][0]["value"] == expected
        assert grid["unit"] == unit


def test_fetch_grid_day_wind_u_v_derived_and_direction(monkeypatch):
    """wind_u/wind_v mirror the live map's derivation: km/h -> m/s, then
    u = -speed·sin(dir), v = -speed·cos(dir). speed=20 km/h @ 270° -> u=+5.5556, v=0."""
    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    monkeypatch.setattr(
        historical_weather_mod.historical_weather, "_fetch_day_daily", _era5_day_stub
    )
    u = historical_weather_mod.historical_weather.fetch_grid(
        north=30.6, south=30.0, east=80.0, west=78.0,
        step=0.5, max_points=600, variable="wind_u",
        year=2025, month=6, day=12,
    )
    assert u["derived"] is True
    assert u["unit"] == "m/s"
    # u = -(20/3.6)·sin(270°) = +5.5556, rounded to 2dp per backend convention.
    assert u["points"][0]["value"] == 5.56
    assert u["data_provenance"]["aggregation"] == "derived"

    v = historical_weather_mod.historical_weather.fetch_grid(
        north=30.6, south=30.0, east=80.0, west=78.0,
        step=0.5, max_points=600, variable="wind_v",
        year=2025, month=6, day=12,
    )
    assert v["derived"] is True
    assert v["unit"] == "m/s"
    assert v["points"][0]["value"] == pytest.approx(0.0, abs=1e-6)

    direction = historical_weather_mod.historical_weather.fetch_grid(
        north=30.6, south=30.0, east=80.0, west=78.0,
        step=0.5, max_points=600, variable="wind_direction_10m",
        year=2025, month=6, day=12,
    )
    assert direction["derived"] is False
    assert direction["unit"] == "°"
    assert direction["points"][0]["value"] == 270.0


def test_fetch_grid_day_accumulation_is_month_to_date(monkeypatch):
    """Rain accumulation on day N is the REAL month-to-date cumulative sum
    (days 1..N), computed from the full completed-month block."""
    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    monkeypatch.setattr(
        historical_weather_mod.historical_weather, "_fetch_month_daily", _era5_daily_stub
    )
    grid = historical_weather_mod.historical_weather.fetch_grid(
        north=30.6, south=30.0, east=80.0, west=78.0,
        step=0.5, max_points=600, variable="precipitation_accumulation",
        year=2025, month=6, day=13,
    )
    # Wet days 1..13 where d % 3 != 0: {1,2,4,5,7,8,10,11,13} = 9 days * 2.0 = 18.0
    assert grid["data_status"] == "HISTORICAL"
    assert grid["valid_time"] == "2025-06-13"
    assert grid["unit"] == "mm"
    assert grid["data_provenance"]["aggregation"] == "month_to_date_total"
    assert all(p["value"] == 18.0 for p in grid["points"])


def test_fetch_grid_day_out_of_range_rejected(monkeypatch):
    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    for month, day in ((2, 30), (4, 31), (6, 31)):
        with pytest.raises(ValueError):
            historical_weather_mod.historical_weather.fetch_grid(
                north=30.6, south=30.0, east=80.0, west=78.0,
                step=0.5, max_points=600, variable="precipitation",
                year=2025, month=month, day=day,
            )


def test_fetch_grid_direction_variables_are_per_day_only(monkeypatch):
    """Wind direction / U-V have no honest monthly meaning — monthly mode must
    answer UNAVAILABLE without touching the network, not fudge a vector mean."""
    calls = {"n": 0}
    def boom(latitudes, longitudes, year, month):
        calls["n"] += 1
        raise AssertionError("per-day-only variables must not be fetched monthly")
    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    monkeypatch.setattr(historical_weather_mod.historical_weather, "_fetch_month_daily", boom)
    for variable in ("wind_direction_10m", "wind_u", "wind_v"):
        grid = historical_weather_mod.historical_weather.fetch_grid(
            north=30.6, south=30.0, east=80.0, west=78.0,
            step=0.5, max_points=600, variable=variable,
            year=2025, month=6,
        )
        assert grid["data_status"] == "UNAVAILABLE"
        assert "per-day" in grid["reason"]
        assert all(p["reason"] for p in grid["points"])
    assert calls["n"] == 0


def test_fetch_grid_day_incomplete_month_unavailable_no_network(monkeypatch):
    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    calls = {"n": 0}
    def boom(latitudes, longitudes, year, month, day):
        calls["n"] += 1
        raise AssertionError("incomplete months must not be fetched per-day")
    monkeypatch.setattr(historical_weather_mod.historical_weather, "_fetch_day_daily", boom)
    grid = historical_weather_mod.historical_weather.fetch_grid(
        north=30.6, south=30.0, east=80.0, west=78.0,
        step=0.5, max_points=600, variable="precipitation",
        year=2026, month=9, day=5,
    )
    assert grid["data_status"] == "UNAVAILABLE"
    assert calls["n"] == 0
    assert _INCOMPLETE_MONTH_REASON in grid["reason"]


# ---------------- cache: in-memory + persistent (day-aware) ----------------

def test_fetch_grid_in_memory_cache_serves_repeat_without_upstream(monkeypatch):
    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    provider = historical_weather_mod.HistoricalWeatherProvider()
    calls = {"n": 0}
    def counting_day(latitudes, longitudes, year, month, day):
        calls["n"] += 1
        return _era5_day_stub(latitudes, longitudes, int(year), int(month), int(day))
    monkeypatch.setattr(provider, "_fetch_day_daily", counting_day)
    opts = dict(
        north=30.6, south=30.0, east=80.0, west=78.0, step=0.5, max_points=600,
        variable="precipitation", year=2025, month=6, day=13,
    )
    first = provider.fetch_grid(**opts)
    second = provider.fetch_grid(**opts)
    assert calls["n"] == 1
    assert [p["value"] for p in first["points"]] == [p["value"] for p in second["points"]]
    assert all(p["data_status"] == "HISTORICAL" for p in second["points"])


def test_fetch_grid_in_memory_cache_day_variant_distinct(monkeypatch):
    """The in-memory cache key includes the day — day 13 and day 14 are
    distinct entries (each costs one upstream fetch, repeat hits stay cached)."""
    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    provider = historical_weather_mod.HistoricalWeatherProvider()
    calls = {"n": 0}
    def counting_day(latitudes, longitudes, year, month, day):
        calls["n"] += 1
        return _era5_day_stub(latitudes, longitudes, int(year), int(month), int(day))
    monkeypatch.setattr(provider, "_fetch_day_daily", counting_day)
    base = dict(
        north=30.6, south=30.0, east=80.0, west=78.0, step=0.5, max_points=600,
        variable="precipitation", year=2025, month=6,
    )
    first_13 = provider.fetch_grid(**{**base, "day": 13})
    first_12 = provider.fetch_grid(**{**base, "day": 12})
    again_13 = provider.fetch_grid(**{**base, "day": 13})
    assert calls["n"] == 2
    assert first_13["valid_time"] == "2025-06-13"
    assert first_12["valid_time"] == "2025-06-12"
    # day 13 is wet (2.0mm) in the stub, day 12 is dry (0.0mm) — must differ.
    assert first_12["points"][0]["value"] != first_13["points"][0]["value"]
    assert first_13["points"][0]["value"] == 2.0
    assert first_12["points"][0]["value"] == 0.0
    assert [p["value"] for p in again_13["points"]] == [p["value"] for p in first_13["points"]]


def test_fetch_archive_block_rejects_ragged_records(monkeypatch):
    """A ragged upstream block (a column shorter than `time` for one location)
    is refused, never blended into misattributed HISTORICAL cache values."""
    from app.http_client import HttpFetchError

    class FakeResponse:
        status_code: int
        payload: list

        def __init__(self, payload):
            self.status_code = 200
            self.payload = payload

        def json(self):
            return self.payload

    time30 = [f"2025-06-{d:02d}" for d in range(1, 31)]
    good = {"daily": {"time": list(time30), "precipitation_sum": [2.0] * 30}}
    ragged = {"daily": {"time": list(time30), "precipitation_sum": [2.0] * 29}}
    payload = [good, ragged]
    monkeypatch.setattr(
        historical_weather_mod,
        "http_get",
        lambda url, params, timeout: FakeResponse(payload),
    )
    provider = historical_weather_mod.HistoricalWeatherProvider()
    with pytest.raises(HttpFetchError, match="ragged"):
        provider._fetch_archive_block(
            [30.0, 30.5], [79.0, 79.5], 2025, 6, "2025-06-01", "2025-06-30"
        )


def test_fetch_grid_db_cache_serves_day_after_in_memory_clear(db_ctx, monkeypatch):
    """Day-mode samples persist to the DB (data_day set); after the in-memory
    cache is cleared the DB serves the 2nd request — one upstream fetch total."""
    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    provider = historical_weather_mod.HistoricalWeatherProvider()
    calls = {"n": 0}
    def counting_day(latitudes, longitudes, year, month, day):
        calls["n"] += 1
        return _era5_day_stub(latitudes, longitudes, int(year), int(month), int(day))
    monkeypatch.setattr(provider, "_fetch_day_daily", counting_day)
    session = db_ctx["session_factory"]()
    try:
        opts = dict(
            north=30.6, south=30.0, east=80.0, west=78.0, step=0.5, max_points=600,
            variable="precipitation", year=2025, month=6, day=13, session=session,
        )
        first = provider.fetch_grid(**opts)
        provider._grid_cache.clear()
        second = provider.fetch_grid(**opts)
    finally:
        session.close()
    assert calls["n"] == 1
    assert [p["value"] for p in second["points"]] == [p["value"] for p in first["points"]]
    assert all(p["data_status"] == "HISTORICAL" for p in second["points"])


def test_fetch_grid_db_cache_serves_monthly_after_in_memory_clear(db_ctx, monkeypatch):
    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    provider = historical_weather_mod.HistoricalWeatherProvider()
    calls = {"n": 0}
    def counting_month(latitudes, longitudes, year, month):
        calls["n"] += 1
        return _era5_daily_stub(latitudes, longitudes, int(year), int(month))
    monkeypatch.setattr(provider, "_fetch_month_daily", counting_month)
    session = db_ctx["session_factory"]()
    try:
        opts = dict(
            north=30.6, south=30.0, east=80.0, west=78.0, step=0.5, max_points=600,
            variable="precipitation", year=2025, month=6, session=session,
        )
        first = provider.fetch_grid(**opts)
        provider._grid_cache.clear()
        second = provider.fetch_grid(**opts)
    finally:
        session.close()
    assert calls["n"] == 1
    assert all(p["value"] == 40.0 for p in second["points"])
    assert first["points"][0]["value"] == 40.0


def test_citizen_can_read_historical_weather(db_ctx, auth_headers, era5_freezer):
    """The Citizen portal now has the read-only Historical Weather Map:
    every weather/rainfall read endpoint is reachable (weather.history.read)."""
    client = db_ctx["client"]
    historical = [
        ("/api/historical/weather/years", None),
        ("/api/weather/30.5/79.5/historical?year=2025&month=6", "HISTORICAL"),
        (
            "/api/weather/grid?bounds=30.5,30.0,80.0,79.0&year=2025&month=6&variable=precipitation",
            "HISTORICAL",
        ),
    ]
    for url, expected_status in historical:
        res = client.get(url, headers=auth_headers)
        assert res.status_code == 200, f"{url} -> {res.status_code} {res.text}"
        if expected_status:
            assert res.json()["data_status"] == expected_status, url

    for url in ("/api/rainfall/30.5/79.5", "/api/rainfall-grid?bounds=30.5,30.0,80.0,79.0"):
        res = client.get(url, headers=auth_headers)
        assert res.status_code == 200, f"{url} -> {res.status_code} {res.text}"


def test_citizen_live_point_is_honest_not_403(db_ctx, auth_headers, monkeypatch):
    """Live weather stays off for citizens too — but it is an honest
    API_NOT_ADDED payload, never a 403 portal gate."""
    monkeypatch.setattr(config, "WEATHER_LIVE_ENABLED", False)
    res = db_ctx["client"].get("/api/weather/30.5/79.5", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["data_status"] == "API_NOT_ADDED"
    assert body["current"] is None and body["forecast"] == []
    assert "WEATHER_LIVE_ENABLED" in body["reason"]


def test_officer_can_read_years_route(db_ctx, officer_headers):
    res = db_ctx["client"].get("/api/historical/weather/years", headers=officer_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["provider"]["name"] == HISTORICAL_PROVIDER_NAME
    assert body["provenance"].startswith("Historical weather is ERA5 reanalysis")
    assert body["completed_through_month"] <= 11


def test_officer_historical_point_route(db_ctx, officer_headers, era5_freezer):
    res = db_ctx["client"].get(
        "/api/weather/30.5/79.5/historical?year=2025&month=6", headers=officer_headers
    )
    assert res.status_code == 200
    body = res.json()
    assert body["data_status"] == "HISTORICAL"
    assert body["is_historical"] is True
    assert body["variables"]["precipitation"]["value"] == 40.0


def test_officer_historical_grid_route(db_ctx, officer_headers, era5_freezer):
    res = db_ctx["client"].get(
        "/api/weather/grid?bounds=30.5,30.0,80.0,79.0&step=0.5&variable=precipitation&year=2025&month=6",
        headers=officer_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["data_status"] == "HISTORICAL"
    assert body["is_historical"] is True
    assert body["month"] == 6
    assert body["data_provenance"]["year"] == 2025
    assert body["data_provenance"]["source"] == HISTORICAL_SOURCE


def test_officer_historical_grid_incomplete_month(db_ctx, officer_headers, era5_freezer):
    res = db_ctx["client"].get(
        "/api/weather/grid?bounds=30.5,30.0,80.0,79.0&step=0.5&variable=precipitation&year=2026&month=9",
        headers=officer_headers,
    )
    assert res.status_code == 200
    assert res.json()["data_status"] == "UNAVAILABLE"
    assert _INCOMPLETE_MONTH_REASON in res.json()["reason"]


def test_grid_requires_month_with_year(db_ctx, officer_headers):
    res = db_ctx["client"].get(
        "/api/weather/grid?bounds=30.5,30.0,80.0,79.0&variable=precipitation&year=2025",
        headers=officer_headers,
    )
    assert res.status_code == 400
    assert "month is required" in res.json()["detail"]


def test_officer_historical_grid_day_route(db_ctx, officer_headers, era5_freezer, monkeypatch):
    """The grid endpoint serves a single completed day (playback)."""
    monkeypatch.setattr(
        historical_weather_mod.historical_weather, "_fetch_day_daily", _era5_day_stub
    )
    # Clear the singleton's process-wide TTL cache so this test genuinely
    # exercises the transport (an identical earlier grid could otherwise mask it).
    historical_weather_mod.historical_weather._grid_cache.clear()
    res = db_ctx["client"].get(
        "/api/weather/grid?bounds=30.5,30.0,80.0,79.0&step=0.5&variable=precipitation"
        "&year=2025&month=6&day=13",
        headers=officer_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["data_status"] == "HISTORICAL"
    assert body["day"] == 13
    assert body["valid_time"] == "2025-06-13"
    assert body["data_provenance"]["aggregation"] == "daily_total"
    assert all(p["value"] == 2.0 for p in body["points"])


def test_officer_historical_grid_day_out_of_month_400(db_ctx, officer_headers, era5_freezer):
    res = db_ctx["client"].get(
        "/api/weather/grid?bounds=30.5,30.0,80.0,79.0&step=0.5&variable=precipitation"
        "&year=2026&month=2&day=30",
        headers=officer_headers,
    )
    assert res.status_code == 400
    assert "out of range" in res.json()["detail"]


def test_officer_live_grid_day_above_7_rejected(db_ctx, officer_headers):
    """Live forecast grids still only accept day 0..7 even though the shared
    `day` query bound widens to 31 for historical per-day grids."""
    res = db_ctx["client"].get(
        "/api/weather/grid?bounds=30.5,30.0,80.0,79.0&step=0.5&variable=temperature_2m&day=8",
        headers=officer_headers,
    )
    assert res.status_code == 400
    assert "0..7" in res.json()["detail"]


# ---------------- API: live API_NOT_ADDED when disabled ----------------

def test_live_point_api_not_added_when_disabled(db_ctx, officer_headers, monkeypatch):
    monkeypatch.setattr(config, "WEATHER_LIVE_ENABLED", False)
    res = db_ctx["client"].get("/api/weather/30.5/79.5", headers=officer_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["data_status"] == "API_NOT_ADDED"
    assert body["current"] is None and body["forecast"] == []
    assert "WEATHER_LIVE_ENABLED" in body["reason"]


def test_live_grid_api_not_added_when_disabled(db_ctx, officer_headers, monkeypatch):
    monkeypatch.setattr(config, "WEATHER_LIVE_ENABLED", False)
    res = db_ctx["client"].get(
        "/api/weather/grid?bounds=30.5,30.0,80.0,79.0&variable=temperature_2m",
        headers=officer_headers,
    )
    assert res.status_code == 200
    assert res.json()["data_status"] == "API_NOT_ADDED"


# ---------------- transport hardening ----------------

def _archive_list_body(latitudes, longitudes, year, month):
    """Simulate Open-Meteo's REAL multi-location answer: a JSON *array* with
    one record per requested coordinate, in request order (index = cell)."""
    days = monthrange(int(year), int(month))[1]
    full = _era5_daily_stub(latitudes, longitudes, int(year), int(month))
    records = []
    for i, (lat, lng) in enumerate(zip(latitudes, longitudes)):
        block = slice(i * days, (i + 1) * days)
        records.append(
            {
                "latitude": round(lat, 6),
                "longitude": round(lng, 6),
                "daily": {col: (vals[block] if isinstance(vals, list) else vals) for col, vals in full.items()},
            }
        )
    return records


class _FakeArchiveResponse:
    def __init__(self, body):
        self.status_code = 200
        self.headers = {}
        self._body = body

    def json(self):
        return self._body


def test_archive_multi_location_list_payload_flattened_in_cell_order(monkeypatch):
    """Open-Meteo's archive answers multi-location grids with a JSON *array*
    (one record per coordinate). That is the normal payload — cells must carry
    real HISTORICAL values, never 'unexpected response shape (list)'."""
    from app import historical_weather as hw

    lats = [30.42, 30.44, 30.46]
    lngs = [79.35, 79.37, 79.39]

    def listy_http_get(url, params=None, timeout=None):
        n = len(str((params or {}).get("latitude", "") or "").split(","))
        res_lats = [round(30.42 + 0.02 * i, 6) for i in range(max(n, 1))]
        res_lngs = [round(79.35 + 0.02 * i, 6) for i in range(max(n, 1))]
        return _FakeArchiveResponse(_archive_list_body(res_lats, res_lngs, 2025, 6))

    monkeypatch.setattr(hw, "http_get", listy_http_get)
    provider = hw.HistoricalWeatherProvider(db_cache=False)

    flattened = provider._fetch_month_daily(lats, lngs, 2025, 6)
    days = monthrange(2025, 6)[1]
    assert len(flattened["time"]) == len(lats) * days
    # Cell order preserved: cell i occupies arrays[i*days:(i+1)*days].
    assert flattened["temperature_2m_mean"][0] == 18.0 + 0 + (1 % 5)            # cell 0, day 1
    assert flattened["temperature_2m_mean"][days] == 18.0 + 1 + (1 % 5)          # cell 1, day 1
    assert flattened["temperature_2m_mean"][2 * days] == 18.0 + 2 + (1 % 5)      # cell 2, day 1

    point = provider.fetch_point_month(30.42, 79.35, 2025, 6)
    assert point["data_status"] == "HISTORICAL"
    assert point["variables"]["temperature_2m"]["value"] == pytest.approx(20.0)


def test_archive_dict_payload_still_accepted(monkeypatch):
    """A single-location archive request answers with a dict — unchanged path."""
    from app import historical_weather as hw

    def dicty_http_get(url, params=None, timeout=None):
        return _FakeArchiveResponse({"daily": _era5_daily_stub([30.42], [79.35], 2025, 6)})

    monkeypatch.setattr(hw, "http_get", dicty_http_get)
    provider = hw.HistoricalWeatherProvider(db_cache=False)
    flattened = provider._fetch_month_daily([30.42], [79.35], 2025, 6)
    assert len(flattened["time"]) == monthrange(2025, 6)[1]
    assert flattened["temperature_2m_mean"][0] == 18.0 + (1 % 5)


def test_archive_genuinely_bad_shape_is_honest_unavailable(monkeypatch):
    """A truly malformed archive body (wrong record count / empty / non-object /
    record missing the daily block) stays an honest UNAVAILABLE — never a 500."""
    from app.http_client import HttpFetchError
    from app import historical_weather as hw

    bad_bodies = [
        ["error", "reason inline"],            # record count != requested locations
        [],                                    # empty list (no records at all)
        "plain string",                        # not an object/array
        [{"latitude": 30.42, "daily": None}],  # record missing the daily block
    ]

    provider = hw.HistoricalWeatherProvider(db_cache=False)
    for body in bad_bodies:
        class _BadBodyResponse:
            status_code = 200
            headers = {}

            @staticmethod
            def json():
                return body

        monkeypatch.setattr(hw, "http_get", lambda *a, **k: _BadBodyResponse())

        with pytest.raises(HttpFetchError):
            provider._fetch_month_daily([30.42], [79.35], 2025, 6)

        point = provider.fetch_point_month(30.42, 79.35, 2025, 6)
        assert point["data_status"] == "UNAVAILABLE"
        assert "unavailable" in point["reason"].lower()


# ---------------- historical flood-risk overlay ----------------

def test_historical_flood_overlay_calculated_from_era5_and_srtm(
    db_ctx, auth_headers, officer_headers, era5_freezer, monkeypatch
):
    from app.terrain_service import terrain_service

    def fake_terrain_grid(north, south, east, west, step, max_points):
        terrain_service_mod = historical_weather_mod
        cells, _bounds = terrain_service_mod.historical_weather._grid_cells(
            north, south, east, west, step, max_points
        )
        return {
            "data_status": "LIVE",
            "points": [
                {
                    "latitude": c["latitude"],
                    "longitude": c["longitude"],
                    "elevation_m": 1500.0 + (i % 5) * 100.0,
                    "slope_percent": 8.0 + (i % 3),
                    "slope_category": "MODERATE",
                    "data_status": "LIVE",
                }
                for i, c in enumerate(cells)
            ],
        }

    monkeypatch.setattr(terrain_service, "get_terrain_grid", fake_terrain_grid)

    url = "/api/flood-risk-grid?bounds=30.5,30.0,80.0,79.0&step=0.5&year=2025&month=6"
    for headers in (auth_headers, officer_headers):
        res = db_ctx["client"].get(url, headers=headers)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["data_status"] == "CALCULATED"
        assert body["points"]
        factors = body["points"][0]["contributing_factors"]
        assert any("historical_precipitation" in f and "ERA5" in f for f in factors)
        assert any("elevation" in f and "SRTM" in f for f in factors)
        assert body["valid_time"].endswith("(completed month, HISTORICAL)")


# ---------------- real-data catalog ----------------

def test_data_catalog_surface(db_ctx, auth_headers, officer_headers):
    client = db_ctx["client"]
    for headers in (auth_headers, officer_headers):
        res = client.get("/api/data-catalog", headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert len(body["entries"]) >= 15
        keys = {d["key"] for d in body["entries"]}
        assert "historical_weather" in keys
        assert "weather_forecast" in keys and "srtm_elevation" in keys
        assert body["live_weather_enabled"] in (True, False)


# ---------------- archive resilience (block cache, single-flight, 429) ----------------

class FakeJsonResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _isolate_shared_guards(monkeypatch):
    """Reset the cross-provider inflight + cooldown guards for every test so
    one test can never leak a cooldown or a half-finished single-flight slot."""
    monkeypatch.setattr("app.weather_service._INFLIGHT", {})
    monkeypatch.setattr("app.weather_service._PROVIDER_COOLDOWN_UNTIL", {})


def _archive_daily_body(params):
    lats = [float(x) for x in str(params["latitude"]).split(",")]
    lngs = [float(x) for x in str(params["longitude"]).split(",")]
    return {"daily": _era5_daily_stub(lats, lngs, 2025, 6)}


def test_archive_block_cache_serves_repeat_without_upstream(monkeypatch):
    """Repeating the same archive window + cells is served from the block cache:
    exactly ONE upstream request total."""
    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    provider = historical_weather_mod.HistoricalWeatherProvider(db_cache=False)
    calls = {"n": 0}

    def intercept(url, params=None, timeout=None):
        calls["n"] += 1
        return FakeJsonResponse(200, _archive_daily_body(params))

    monkeypatch.setattr(historical_weather_mod, "http_get", intercept)
    first = provider._fetch_month_daily([30.42], [79.35], 2025, 6)
    second = provider._fetch_month_daily([30.42], [79.35], 2025, 6)
    assert calls["n"] == 1
    assert first == second


def test_archive_block_single_flight_dedups_concurrent(monkeypatch):
    """Six concurrent callers of the same archive window collapse into ONE
    upstream request; every waiter gets the same daily payload."""
    import threading
    import time

    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    provider = historical_weather_mod.HistoricalWeatherProvider(db_cache=False)
    calls = {"n": 0}

    def intercept(url, params=None, timeout=None):
        calls["n"] += 1
        time.sleep(0.1)
        return FakeJsonResponse(200, _archive_daily_body(params))

    monkeypatch.setattr(historical_weather_mod, "http_get", intercept)
    barrier = threading.Barrier(6)
    results, errors = [], []

    def worker():
        barrier.wait()
        try:
            results.append(provider._fetch_month_daily([30.42], [79.35], 2025, 6))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(results) == 6
    assert calls["n"] == 1


def test_archive_429_retries_then_succeeds(monkeypatch):
    """A 429 is retried once with a bounded backoff; the request succeeds."""
    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    monkeypatch.setattr(historical_weather_mod.time, "sleep", lambda _: None)
    provider = historical_weather_mod.HistoricalWeatherProvider(db_cache=False)
    calls = {"n": 0}

    def throttled_then_ok(url, params=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeJsonResponse(429, None, headers={"retry-after": "2"})
        return FakeJsonResponse(200, _archive_daily_body(params))

    monkeypatch.setattr(historical_weather_mod, "http_get", throttled_then_ok)
    daily = provider._fetch_month_daily([30.42], [79.35], 2025, 6)
    assert calls["n"] == 2
    assert len(daily["time"]) == 30


def test_archive_429_long_retry_after_gives_up(monkeypatch):
    """An explicit long Retry-After is honored: give up immediately instead of
    sleeping past our own bounded backoff window."""
    from app.http_client import HttpFetchError

    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    provider = historical_weather_mod.HistoricalWeatherProvider(db_cache=False)
    calls = {"n": 0}

    def throttled(url, params=None, timeout=None):
        calls["n"] += 1
        return FakeJsonResponse(429, None, headers={"retry-after": "45"})

    monkeypatch.setattr(historical_weather_mod, "http_get", throttled)
    with pytest.raises(HttpFetchError):
        provider._fetch_month_daily([30.42], [79.35], 2025, 6)
    assert calls["n"] == 1


def test_point_month_cache_serves_repeat_without_refetch(monkeypatch):
    """Repeated point-month reads for the same cell + month skip the archive."""
    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    provider = historical_weather_mod.HistoricalWeatherProvider(db_cache=False)
    calls = {"n": 0}

    def counting(latitudes, longitudes, year, month):
        calls["n"] += 1
        return _era5_daily_stub(latitudes, longitudes, year, month)

    monkeypatch.setattr(provider, "_fetch_month_daily", counting)
    first = provider.fetch_point_month(30.42, 79.35, 2025, 6)
    second = provider.fetch_point_month(30.42, 79.35, 2025, 6)
    assert first["data_status"] == "HISTORICAL"
    assert second["data_status"] == "HISTORICAL"
    assert calls["n"] == 1


def test_fetch_grid_all_chunks_fail_is_unavailable(monkeypatch):
    """A monthly grid whose every upstream request fails is UNAVAILABLE — it
    must NOT be masked as a successful HISTORICAL grid."""
    from app.http_client import HttpFetchError

    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    provider = historical_weather_mod.HistoricalWeatherProvider(db_cache=False)

    def boom(latitudes, longitudes, year, month):
        raise HttpFetchError("upstream exploded")

    monkeypatch.setattr(provider, "_fetch_month_daily", boom)
    grid = provider.fetch_grid(
        north=30.6, south=30.0, east=80.0, west=78.0,
        step=0.5, max_points=600,
        variable="precipitation", year=2025, month=6,
    )
    assert grid["data_status"] == "UNAVAILABLE"
    assert grid["reason"]
    assert grid["min"] is None and grid["max"] is None
    assert all(p["data_status"] == "UNAVAILABLE" for p in grid["points"])
    assert all(p["value"] is None for p in grid["points"])


def test_fetch_grid_day_all_fail_is_unavailable(monkeypatch):
    """Same honesty for a per-day grid: zero real values => UNAVAILABLE."""
    from app.http_client import HttpFetchError

    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    provider = historical_weather_mod.HistoricalWeatherProvider(db_cache=False)

    def boom(latitudes, longitudes, year, month, day):
        raise HttpFetchError("upstream exploded")

    monkeypatch.setattr(provider, "_fetch_day_daily", boom)
    grid = provider.fetch_grid(
        north=30.6, south=30.0, east=80.0, west=78.0,
        step=0.5, max_points=600,
        variable="precipitation", year=2025, month=6, day=13,
    )
    assert grid["data_status"] == "UNAVAILABLE"
    assert grid["min"] is None and grid["max"] is None
    assert all(p["data_status"] == "UNAVAILABLE" for p in grid["points"])


def test_fetch_grid_partial_failure_is_historical_with_unavailable_cells(monkeypatch):
    """When SOME chunks succeed, the grid stays HISTORICAL but the failed cells
    are honestly marked UNAVAILABLE and listed in the reason."""
    from app.http_client import HttpFetchError

    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    provider = historical_weather_mod.HistoricalWeatherProvider(db_cache=False)
    calls = {"n": 0}

    def flaky(latitudes, longitudes, year, month):
        calls["n"] += 1
        if calls["n"] in (2, 3):
            raise HttpFetchError("chunk exploded")
        return _era5_daily_stub(latitudes, longitudes, year, month)

    monkeypatch.setattr(provider, "_fetch_month_daily", flaky)
    grid = provider.fetch_grid(
        north=30.6, south=30.0, east=80.0, west=78.0,
        step=0.05, max_points=600,
        variable="precipitation", year=2025, month=6,
    )
    assert grid["data_status"] == "HISTORICAL"
    assert "Some cells unavailable" in grid["reason"]
    statuses = {p["data_status"] for p in grid["points"]}
    assert "HISTORICAL" in statuses and "UNAVAILABLE" in statuses
    assert grid["min"] is not None


def test_point_month_throttled_is_honest_unavailable(monkeypatch):
    """While the archive provider is in 429 cooldown, the point read answers
    UNAVAILABLE with a reason and does NOT touch the network."""
    from app.weather_service import _mark_provider_cooldown

    monkeypatch.setattr(historical_weather_mod, "_now_utc", lambda: SEP_2026_UTC)
    provider = historical_weather_mod.HistoricalWeatherProvider(db_cache=False)
    _mark_provider_cooldown(HISTORICAL_PROVIDER_NAME, 60.0)

    def no_network(url, params=None, timeout=None):
        raise AssertionError("must not hit the network while in cooldown")

    monkeypatch.setattr(historical_weather_mod, "http_get", no_network)
    payload = provider.fetch_point_month(30.42, 79.35, 2025, 6)
    assert payload["data_status"] == "UNAVAILABLE"
    assert payload["reason"]