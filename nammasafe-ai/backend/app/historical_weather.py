"""Historical weather provider — Open-Meteo ERA5 Archive (ECMWF reanalysis).

This is the *historical* weather source behind the "year" selection on the
weather maps:

  * Real ECMWF ERA5 reanalysis served by Open-Meteo's archive API — no API key,
    no fabricated values. Completed months only.
  * The current year is served strictly up to its *last completed month*
    (e.g. today 2026-09-26 -> months 01..08). A requested current/future month
    is returned honestly as UNAVAILABLE — never forecast, never fabricated.
  * Every payload is labelled `data_status: HISTORICAL` with explicit
    provenance (source, dataset, year, period, aggregation) so a historical
    monthly total can never be mistaken for a live observation.
  * Aggregations are computed server-side from the archive's *daily* block
    (monthly_total for precipitation, monthly_mean for temperature/pressure,
    monthly_mean_of_daily_max for wind, day counts for rain/thunderstorm).
    Grid requests can also target a *single completed day* (day in 1..N of the
    month) so the map can animate real day-by-day reanalysis — precipitation is
    then that day's total, rain accumulation is the real month-to-date
    cumulative sum, and wind_direction_10m / wind_u / wind_v are only served
    per-day (a bare vector mean over a month would be dishonest).
    Variables the daily archive does not expose (relative humidity, visibility,
    precipitation probability) are marked `available: False` with a reason —
    never substituted.
  * The same rate-limit guards as the live chain (concurrency semaphore,
    429 cooldown with Retry-After) keep the archive API from being hammered.

Persistence: validated historical samples are cached to the
`historical_weather_samples` table (rounded cell / year / month / variable /
aggregation). The cache is best-effort — if the table is missing or locked the
provider still honours the request from the upstream archive.
"""

from __future__ import annotations

import logging

import math
import threading
import time
from calendar import monthrange
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from sqlalchemy.orm import Session

from app import config
from app import weather_platform
from app.cache import TTLCache
from app.http_client import HttpFetchError, http_get

# ---------------------------------------------------------------------------
# Reuse the live chain's shared rate-limit guards (they are keyed per provider
# name, so the archive has its own cooldown slot).
# ---------------------------------------------------------------------------
from app.weather_service import (  # noqa: E402
    _PROVIDER_HTTP_SEMAPHORE,
    _inflight_acquire,
    _inflight_done,
    _inflight_wait,
    _mark_provider_cooldown,
    _provider_in_cooldown,
    _retry_after_seconds,
)

HISTORICAL_PROVIDER_NAME = "Open-Meteo ERA5 Archive"
HISTORICAL_SOURCE = "Open-Meteo ERA5 Archive"
HISTORICAL_DATASET = "ECMWF ERA5 reanalysis (0.25°, daily aggregations)"

_INCOMPLETE_MONTH_REASON = (
    "Month is not yet completed: historical ERA5 reanalysis is only served for "
    "completed months so nothing is invented for a partial month."
)

# Daily archive columns we request. Every supported historical variable is
# derived from this single daily block, so one request per cell chunk per month
# covers the whole map layer set.
_DAILY_COLUMNS = (
    "temperature_2m_max",
    "temperature_2m_min",
    "temperature_2m_mean",
    "apparent_temperature_mean",
    "precipitation_sum",
    "rain_sum",
    "snowfall_sum",
    "precipitation_hours",
    "weather_code",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
    "wind_direction_10m_dominant",
    "surface_pressure_mean",
    "cloud_cover_mean",
)

# Grid variable -> (daily column, aggregation, unit)
GRID_AGGREGATES: Dict[str, Tuple[str, str, str]] = {
    "temperature_2m": ("temperature_2m_mean", "monthly_mean", "°C"),
    "apparent_temperature": ("apparent_temperature_mean", "monthly_mean", "°C"),
    "precipitation": ("precipitation_sum", "monthly_total", "mm"),
    "precipitation_accumulation": ("precipitation_sum", "monthly_total", "mm"),
    "wind_speed_10m": ("wind_speed_10m_max", "monthly_mean_of_daily_max", "km/h"),
    "wind_gusts_10m": ("wind_gusts_10m_max", "monthly_mean_of_daily_max", "km/h"),
    "pressure_msl": ("surface_pressure_mean", "monthly_mean", "hPa"),
    "storm_indicator": ("weather_code", "thunderstorm_days", "index"),
    "cloud_cover": ("cloud_cover_mean", "monthly_mean", "%"),
}

# Variables the ERA5 *daily* archive does not expose. Reported as unavailable
# for historical mode (never substituted).
GRID_UNAVAILABLE_VARIABLES = {
    "precipitation_probability",
    "relative_humidity",
    "visibility",
}

# Per-day-only grid variables: only asked for a single day. A monthly value
# would be a fabricated/lossy construct (e.g. the vector mean of wind
# direction), so monthly mode honestly answers UNAVAILABLE.
PER_DAY_ONLY_GRID_VARIABLES = {
    "wind_direction_10m",
    "wind_u",
    "wind_v",
}

# Day-mode aggregation labels per variable (provenance honesty).
_DAY_AGGREGATION: Dict[str, str] = {
    "temperature_2m": "day_value",
    "apparent_temperature": "day_value",
    "precipitation": "daily_total",
    "precipitation_accumulation": "month_to_date_total",
    "wind_speed_10m": "daily_max",
    "wind_gusts_10m": "daily_max",
    "pressure_msl": "day_value",
    "storm_indicator": "day_indicator",
    "cloud_cover": "day_value",
    "wind_direction_10m": "day_value",
    "wind_u": "derived",
    "wind_v": "derived",
}

_DAY_ONLY_UNITS = {
    "wind_direction_10m": "°",
    "wind_u": "m/s",
    "wind_v": "m/s",
}

_POINT_UNITS: Dict[str, str] = {
    "temperature_2m": "°C",
    "apparent_temperature": "°C",
    "temperature_max_2m": "°C",
    "temperature_min_2m": "°C",
    "precipitation": "mm",
    "precipitation_accumulation": "mm",
    "rain_days": "days",
    "precipitation_hours": "hours",
    "wind_speed_10m": "km/h",
    "wind_gusts_10m": "km/h",
    "pressure_msl": "hPa",
    "storm_days": "days",
    "thunderstorm_days": "days",
    "cloud_cover": "%",
}

_THUNDERSTORM_CODES = {95, 96, 99}

# Every variable a historical grid accepts (aggregated, per-day, honestly-unavailable).
HISTORICAL_GRID_VARIABLES = sorted(
    {*GRID_AGGREGATES, *GRID_UNAVAILABLE_VARIABLES, *PER_DAY_ONLY_GRID_VARIABLES}
)


def _round6(value: float) -> float:
    return round(value, 6)


def _round2(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(float(value), 2)


def _month_period(year: int, month: int) -> Tuple[str, str, int]:
    _, last_day = monthrange(int(year), int(month))
    start = f"{int(year)}-{int(month):02d}-01"
    end = f"{int(year)}-{int(month):02d}-{last_day:02d}"
    return start, end, last_day


def _now_utc() -> float:
    return time.time()


def current_year() -> int:
    return int(time.strftime("%Y", time.gmtime()))


def completed_through_month_for_year(year: int, now_ts: Optional[float] = None) -> int:
    """Last *completed* month of `year`. For the current year that is the month
    before this one (no partial months); for past years it is 12."""
    ts = now_ts if now_ts is not None else _now_utc()
    now_year = int(time.strftime("%Y", time.gmtime(ts)))
    now_month = int(time.strftime("%m", time.gmtime(ts)))
    if year < now_year:
        return 12
    if year > now_year:
        return 0
    return max(0, now_month - 1)


def available_periods() -> List[Dict[str, Any]]:
    """Year range surfaced by the historical weather selector. The current year
    lists only completed months; past years list all 12."""
    now_ts = _now_utc()
    year_min = min(config.HISTORICAL_YEAR_MIN, config.HISTORICAL_YEAR_MAX)
    year_max = max(config.HISTORICAL_YEAR_MIN, config.HISTORICAL_YEAR_MAX)
    now_year = current_year()
    availability: List[Dict[str, Any]] = []
    for year in range(year_min, year_max + 1):
        completed = completed_through_month_for_year(year, now_ts)
        availability.append(
            {
                "year": year,
                "completed_through_month": completed,
                "status": (
                    "FULL"
                    if completed == 12
                    else ("PARTIAL_COMPLETED" if completed > 0 else "NOT_YET_AVAILABLE")
                ),
                "label": f"{year} (Jan–{completed:02d} completed)"
                if 0 < completed < 12
                else (f"{year}" if completed == 12 else f"{year} (not yet available)"),
            }
        )
    return availability


def _assert_completed_month(year: int, month: int) -> Optional[str]:
    """Return an UNAVAILABLE reason when (year, month) has not completed."""
    y, m = int(year), int(month)
    if m < 1 or m > 12 or y < 1:
        return "Invalid month: month must be 1..12."
    completed = completed_through_month_for_year(y)
    if m > completed:
        return _INCOMPLETE_MONTH_REASON
    return None


# ---------------------------------------------------------------------------
# Raw daily fetch + aggregation
# ---------------------------------------------------------------------------


def _monthly_mean(values: List[Optional[float]]) -> Optional[float]:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def _monthly_sum(values: List[Optional[float]]) -> Optional[float]:
    present = [v for v in values if v is not None]
    return sum(present) if present else None


class HistoricalWeatherProvider:
    """ERA5 archive provider. Instance methods map 1:1 to route contracts."""

    def __init__(self, db_cache: bool = True) -> None:
        self._db_cache = db_cache and config.HISTORICAL_WEATHER_DB_CACHE
        self._cache_hits = 0
        self._cache_misses = 0
        self._grid_cache = TTLCache(
            config.HISTORICAL_WEATHER_CACHE_TTL_SEC,
            max_entries=16384,
        )
        self._block_cache = TTLCache(
            config.HISTORICAL_WEATHER_CACHE_TTL_SEC,
            max_entries=256,
        )
        self._point_cache = TTLCache(
            config.HISTORICAL_WEATHER_CACHE_TTL_SEC,
            max_entries=4096,
        )
        self._lock = threading.Lock()

    # ----------------------------- period bounds -----------------------------

    def provider_identity(self) -> Dict[str, Any]:
        return {
            "name": HISTORICAL_PROVIDER_NAME,
            "kind": "historical",
            "dataset": HISTORICAL_DATASET,
            "endpoint": config.HISTORICAL_WEATHER_BASE_URL,
            "enabled": True,
            "coverage": weather_platform.historical_provider().get("coverage", ""),
            "current_year": current_year(),
            "completed_through_month": completed_through_month_for_year(current_year()),
        }

    # ------------------------------- network ---------------------------------

    @staticmethod
    def _archive_cache_key(latitudes: List[float], longitudes: List[float], start: str, end: str) -> str:
        lat_key = ",".join(str(_round6(lat)) for lat in latitudes)
        lng_key = ",".join(str(_round6(lng)) for lng in longitudes)
        return f"archive:{start}:{end}:{lat_key}|{lng_key}"

    def _fetch_archive_block(
        self,
        latitudes: List[float],
        longitudes: List[float],
        year: int,
        month: int,
        start: str,
        end: str,
    ) -> Dict[str, Any]:
        """One multi-location archive request for an arbitrary start..end window.

        Served from a bounded in-memory cache (TTL = the standard historical
        cache TTL) with a single-flight dedupe: concurrent callers for the same
        window + cells collapse into ONE upstream request, and every waiter
        gets the leader's daily block (or re-raises the leader's error).

        Returns a dict of raw column arrays flattened per location (arrays of
        length len(latitudes) * days); empty dict when the upstream cannot
        serve this request."""
        cache_key = self._archive_cache_key(latitudes, longitudes, start, end)
        cached = self._block_cache.get(cache_key)
        if cached is not None:
            return cached

        inflight_key = f"historical:archive:{cache_key}"
        slot, is_leader = _inflight_acquire(inflight_key)
        if not is_leader:
            value = _inflight_wait(slot)
            if isinstance(value, BaseException):
                raise value
            return value

        try:
            value = self._fetch_archive_block_uncached(
                latitudes, longitudes, year, month, start, end
            )
        except BaseException as exc:
            _inflight_done(inflight_key, slot, exc)
            raise
        _inflight_done(inflight_key, slot, value)
        self._block_cache.set(cache_key, value, config.HISTORICAL_WEATHER_CACHE_TTL_SEC)
        return value

    def _fetch_archive_block_uncached(
        self,
        latitudes: List[float],
        longitudes: List[float],
        year: int,
        month: int,
        start: str,
        end: str,
    ) -> Dict[str, Any]:
        """Raw archive transport for one window: bounded 429 backoff + parse.

        On a 429 the provider cooldown is marked with an honoured Retry-After;
        a short backoff is attempted up to 3 requests, and an explicit long
        Retry-After gives up immediately instead of sleeping past our window.
        """
        provider = HISTORICAL_PROVIDER_NAME
        if _provider_in_cooldown(provider):
            raise HttpFetchError(f"{provider} throttled (429 cooldown active)")

        params = {
            "latitude": ",".join(str(_round6(lat)) for lat in latitudes),
            "longitude": ",".join(str(_round6(lng)) for lng in longitudes),
            "start_date": start,
            "end_date": end,
            "daily": ",".join(_DAILY_COLUMNS),
            "wind_speed_unit": "kmh",
            "timezone": "GMT",
        }
        url = f"{config.HISTORICAL_WEATHER_BASE_URL}/archive"
        delayed_seconds = (2.0, 4.0)
        response = None
        for attempt in range(3):
            try:
                with _PROVIDER_HTTP_SEMAPHORE:
                    response = http_get(
                        url,
                        params=params,
                        timeout=config.HISTORICAL_WEATHER_TIMEOUT_SEC,
                    )
            except HttpFetchError as exc:
                raise
            if response.status_code != 429:
                break
            headers = getattr(response, "headers", None) or {}
            retry_after = _retry_after_seconds(headers, config.HISTORICAL_WEATHER_COOLDOWN_SEC)
            _mark_provider_cooldown(provider, retry_after)
            if attempt >= 2:
                raise HttpFetchError(f"{provider} rate limited (429)")
            delay = delayed_seconds[min(attempt, 1)]
            raw = headers.get("retry-after") or headers.get("Retry-After")
            if raw:
                try:
                    wait_sec = float(str(raw).strip())
                except (TypeError, ValueError):
                    wait_sec = float(retry_after)
                if wait_sec > delay + 1.0:
                    raise HttpFetchError(
                        f"{provider} rate limited (429, Retry-After {raw}s)"
                    )
                delay = min(delay, wait_sec)
            time.sleep(delay)
        if response is None:  # pragma: no cover - defensive
            raise HttpFetchError(f"{provider} did not answer for {start}..{end}")
        if response.status_code >= 400:
            raise HttpFetchError(f"{provider} rejected request ({response.status_code}) for {start}..{end}")
        try:
            payload = response.json()
        except Exception as exc:  # pragma: no cover - non-JSON upstream
            raise HttpFetchError(f"{provider} non-JSON response") from exc
        if isinstance(payload, dict):
            daily = payload.get("daily") or {}
        elif isinstance(payload, list):
            # Open-Meteo's archive answers multi-location requests (the grid
            # batches up to HISTORICAL_WEATHER_BATCH cells) with an ARRAY — one
            # record per requested coordinate, in the same order as the
            # latitudes/longitudes. This is the normal, valid payload: flatten
            # every daily column across the records so cell `i` reads
            # arrays[i*days:(i+1)*days] further down. (The legacy single-point
            # code assumed a dict and turned this valid response into a 500.)
            if len(payload) != len(latitudes):
                raise HttpFetchError(
                    f"{provider} returned unexpected response shape (list of {len(payload)}) "
                    f"for {start}..{end} — expected {len(latitudes)} location records"
                )
            daily = {}
            for record in payload:
                record_daily = record.get("daily") if isinstance(record, dict) else None
                if not isinstance(record_daily, dict):
                    raise HttpFetchError(
                        f"{provider} returned an invalid location record for {start}..{end}"
                    )
                record_times = record_daily.get("time")
                if not isinstance(record_times, list) or not record_times:
                    raise HttpFetchError(
                        f"{provider} returned a location record without daily rows for {start}..{end}"
                    )
                record_days = len(record_times)
                for col, values in record_daily.items():
                    if values is None:
                        continue
                    if isinstance(values, list) and len(values) != record_days:
                        # Ragged record — a column shorter than `time` would
                        # silently blend neighbouring cells/days into every
                        # value. Refuse it honestly instead of minting wrong
                        # (cacheable) HISTORICAL numbers.
                        raise HttpFetchError(
                            f"{provider} returned ragged daily data "
                            f"(record {col}: {len(values)} values vs {record_days} days) for {start}..{end}"
                        )
                    daily.setdefault(col, []).extend(
                        values if isinstance(values, list) else [values]
                    )
        else:
            raise HttpFetchError(
                f"{provider} returned an unexpected response shape "
                f"({type(payload).__name__}) for {start}..{end}"
            )
        if not daily.get("time"):
            raise HttpFetchError(f"{provider} returned no daily rows for {start}..{end}")
        return dict(daily)

    def _fetch_month_daily(
        self,
        latitudes: List[float],
        longitudes: List[float],
        year: int,
        month: int,
    ) -> Dict[str, Any]:
        """Full completed-month daily block (arrays of len(latitudes) * days)."""
        start, end, _last_day = _month_period(year, month)
        return self._fetch_archive_block(latitudes, longitudes, int(year), int(month), start, end)

    def _fetch_day_daily(
        self,
        latitudes: List[float],
        longitudes: List[float],
        year: int,
        month: int,
        day: int,
    ) -> Dict[str, Any]:
        """Single completed-day daily block (arrays of length len(latitudes), the
        per-day grid source for the playback animation)."""
        start = end = f"{int(year)}-{int(month):02d}-{int(day):02d}"
        return self._fetch_archive_block(latitudes, longitudes, int(year), int(month), start, end)

    # -------------------------------- grid ----------------------------------

    def _grid_cells(
        self, north: float, south: float, east: float, west: float, step: float, max_points: int
    ) -> Tuple[List[Dict[str, float]], Dict[str, float]]:
        """Build the India-clamped cell list (mirrors the live grid cell keying)."""
        actual_bounds = {
            "north": min(float(north), 37.4),
            "south": max(float(south), 6.0),
            "east": min(float(east), 98.5),
            "west": max(float(west), 68.0),
        }
        bl = actual_bounds["south"]
        br = actual_bounds["west"]
        tl = actual_bounds["north"]
        tr = actual_bounds["east"]
        cells: List[Dict[str, float]] = []
        lat = bl
        while lat <= tl - 1e-9 and len(cells) < int(max_points):
            lng = br
            while lng <= tr - 1e-9 and len(cells) < int(max_points):
                cells.append({"latitude": round(lat, 5), "longitude": round(lng, 5)})
                lng = round(lng + float(step), 5)
            lat = round(lat + float(step), 5)
        return cells, actual_bounds

    def _aggregate_rows(
        self, dates: List[str], flattened: Dict[str, Any], index: int, days: int
    ) -> Dict[str, Any]:
        """Per-cell daily block -> per-variable monthly aggregates."""
        offset = index * days
        rows = {
            col: flattened.get(col, [])[offset : offset + days]
            if len(flattened.get(col, [])) >= offset + days
            else []
            for col in _DAILY_COLUMNS
        }
        cell_dates = dates[offset : offset + days] if len(dates) >= offset + days else []
        t_mean = _monthly_mean(rows["temperature_2m_mean"])
        t_max_vals = rows["temperature_2m_max"]
        t_min_vals = rows["temperature_2m_min"]
        apparent = _monthly_mean(rows["apparent_temperature_mean"])
        cloud = _monthly_mean(rows["cloud_cover_mean"])
        precip = _monthly_sum(rows["precipitation_sum"])
        precip_max = max([v for v in rows["precipitation_sum"] if v is not None], default=None)
        rain_days = sum(
            1 for v in rows["precipitation_sum"] if v is not None and float(v) >= 1.0
        )
        precip_hours = _monthly_sum(rows["precipitation_hours"])
        wind_max = _monthly_mean(rows["wind_speed_10m_max"])
        gusts = _monthly_mean(rows["wind_gusts_10m_max"])
        pressure = _monthly_mean(rows["surface_pressure_mean"])
        thunderstorm_days = sum(
            1 for code in rows["weather_code"] if code is not None and int(code) in _THUNDERSTORM_CODES
        )

        aggregates: Dict[str, Any] = {
            "temperature_2m": {"value": _round2(t_mean), "aggregation": "monthly_mean"},
            "temperature_max_2m": {
                "value": _round2(_monthly_mean(t_max_vals)),
                "aggregation": "monthly_mean_of_daily_max",
            },
            "temperature_min_2m": {
                "value": _round2(_monthly_mean(t_min_vals)),
                "aggregation": "monthly_mean_of_daily_min",
            },
            "apparent_temperature": {"value": _round2(apparent), "aggregation": "monthly_mean"},
            "cloud_cover": {"value": _round2(cloud), "aggregation": "monthly_mean"},
            "precipitation": {"value": _round2(precip), "aggregation": "monthly_total"},
            "precipitation_accumulation": {"value": _round2(precip), "aggregation": "monthly_total"},
            "rain_days": {"value": float(rain_days), "aggregation": "days"},
            "precipitation_hours": {"value": _round2(precip_hours), "aggregation": "hours"},
            "wind_speed_10m": {"value": _round2(wind_max), "aggregation": "monthly_mean_of_daily_max"},
            "wind_gusts_10m": {"value": _round2(gusts), "aggregation": "monthly_mean_of_daily_max"},
            "pressure_msl": {"value": _round2(pressure), "aggregation": "monthly_mean"},
            "storm_days": {"value": float(thunderstorm_days), "aggregation": "days"},
            "thunderstorm_days": {"value": float(thunderstorm_days), "aggregation": "days"},
        }
        if precip_max is not None:
            aggregates["top_rain_day_mm"] = {"value": _round2(precip_max), "aggregation": "max_daily"}
        return {"aggregates": aggregates, "dates": cell_dates, "rows": rows}

    # ------------------------------ cache -----------------------------------

    def _grid_cell_key(self, lat: float, lng: float) -> str:
        return f"{round(lat, 5)}|{round(lng, 5)}"

    def _grid_cache_key(self, variable: str, year: int, month: int, day: int, lat: float, lng: float) -> str:
        return f"{variable}|{int(year)}|{int(month)}|{int(day)}|{self._grid_cell_key(lat, lng)}"

    def _read_cached_grid_values(
        self,
        session: Optional[Session],
        cells: List[Dict[str, float]],
        variable: str,
        aggregation: str,
        year: int,
        month: int,
        day: int,
    ) -> Dict[str, Any]:
        """Served grid sample values for the request, merging the persistent
        DB cache and the in-memory TTL cache. {cell_key: value}. Best-effort:
        swallows DB errors so the upstream always wins on a cold cache."""
        values: Dict[str, Any] = self._read_db_grid_values(
            session, cells, variable, aggregation, int(year), int(month), int(day)
        )
        for cell in cells:
            mem = self._grid_cache.get(
                self._grid_cache_key(variable, int(year), int(month), int(day), cell["latitude"], cell["longitude"])
            )
            if mem is not None:
                values[self._grid_cell_key(cell["latitude"], cell["longitude"])] = mem
        return values

    def _read_db_grid_values(
        self,
        session: Optional[Session],
        cells: List[Dict[str, float]],
        variable: str,
        aggregation: str,
        year: int,
        month: int,
        day: int,
    ) -> Dict[str, Any]:
        if session is None or not self._db_cache or not cells:
            return {}
        try:
            from sqlalchemy import tuple_

            from app.models import HistoricalWeatherSample

            rows = (
                session.query(HistoricalWeatherSample)
                .filter(
                    HistoricalWeatherSample.data_year == int(year),
                    HistoricalWeatherSample.data_month == int(month),
                    HistoricalWeatherSample.data_day == int(day),
                    HistoricalWeatherSample.variable == variable,
                    HistoricalWeatherSample.aggregation == aggregation,
                    HistoricalWeatherSample.data_source == HISTORICAL_SOURCE,
                    tuple_(
                        HistoricalWeatherSample.latitude,
                        HistoricalWeatherSample.longitude,
                    ).in_(
                        [(round(c["latitude"], 5), round(c["longitude"], 5)) for c in cells]
                    ),
                )
                .all()
            )
        except Exception:
            return {}
        out: Dict[str, Any] = {}
        for row in rows:
            if row.value is None:  # type: ignore[attr-defined]
                continue
            key = self._grid_cell_key(float(row.latitude), float(row.longitude))  # type: ignore[attr-defined]
            out[key] = row.value  # type: ignore[attr-defined]
        return out

    def _write_cached_grid_value(
        self,
        session: Optional[Session],
        lat: float,
        lng: float,
        variable: str,
        aggregation: str,
        value: float,
        year: int,
        month: int,
        day: int,
    ) -> None:
        """Store ONE served grid sample in the in-memory TTL cache and (when the
        DB cache is enabled) upsert it to the persistent table. Best-effort."""
        self._grid_cache.set(self._grid_cache_key(variable, int(year), int(month), int(day), lat, lng), value)
        if session is None or not self._db_cache or value is None:
            return
        try:
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            from app.models import HistoricalWeatherSample

            lng = round(lng, 5)
            lat = round(lat, 5)
            now = datetime.utcnow()
            stmt = sqlite_insert(HistoricalWeatherSample).values(
                latitude=lat,
                longitude=lng,
                data_year=int(year),
                data_month=int(month),
                data_day=int(day),
                variable=variable,
                aggregation=aggregation,
                value=float(value),
                data_source=HISTORICAL_SOURCE,
                dataset=HISTORICAL_DATASET,
                provider=HISTORICAL_PROVIDER_NAME,
                data_status="HISTORICAL",
                computed_at=now,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    "latitude",
                    "longitude",
                    "data_year",
                    "data_month",
                    "data_day",
                    "variable",
                    "aggregation",
                    "data_source",
                ],
                set_={"value": float(value), "computed_at": now},
            )
            session.execute(stmt)
            session.commit()
        except Exception:
            try:
                if session is not None:
                    session.rollback()
            except Exception:
                pass
            logger.exception(
                "historical cache write failed (%s %s %s-%s-%s) — values still served, "
                "DB cache degraded",
                variable,
                aggregation,
                year,
                month,
                day,
            )

    def _cached_grid_point(
        self, cell: Dict[str, float], value: Optional[float], reason: Optional[str] = None
    ) -> Dict[str, Any]:
        return {
            "latitude": cell["latitude"],
            "longitude": cell["longitude"],
            "value": value,
            "data_status": "HISTORICAL" if value is not None else "UNAVAILABLE",
            "provider": HISTORICAL_PROVIDER_NAME,
            "provider_role": "historical",
            "reason": reason,
        }

    # ------------------------------ point month ------------------------------

    def fetch_point_month(self, latitude: float, longitude: float, year: int, month: int) -> Dict[str, Any]:
        """Monthly historical summary for one point (HistoricalWeatherResponse)."""
        reason = _assert_completed_month(year, month)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        start, end, _last_day = _month_period(year, month)
        lat = _round6(latitude)
        lng = _round6(longitude)
        if reason:
            return {
                "latitude": lat,
                "longitude": lng,
                "data_status": "UNAVAILABLE",
                "data_source": HISTORICAL_SOURCE,
                "provider": HISTORICAL_PROVIDER_NAME,
                "provider_role": "historical",
                "dataset": HISTORICAL_DATASET,
                "is_historical": True,
                "year": int(year),
                "month": int(month),
                "period": f"{start}/{end}",
                "variables": {},
                "top_rain_day": None,
                "daily": [],
                "computed_at": now,
                "reason": reason,
            }

        point_key = f"point:{lat}:{lng}:{int(year)}:{int(month)}"
        cached_point = self._point_cache.get(point_key)
        if cached_point is not None:
            return cached_point

        try:
            daily = self._fetch_month_daily([lat], [lng], int(year), int(month))
        except HttpFetchError as exc:
            return {
                "latitude": lat,
                "longitude": lng,
                "data_status": "UNAVAILABLE",
                "data_source": HISTORICAL_SOURCE,
                "provider": HISTORICAL_PROVIDER_NAME,
                "provider_role": "historical",
                "dataset": HISTORICAL_DATASET,
                "is_historical": True,
                "year": int(year),
                "month": int(month),
                "period": f"{start}/{end}",
                "variables": {},
                "top_rain_day": None,
                "daily": [],
                "computed_at": now,
                "reason": f"Historical archive unavailable — {exc}",
            }

        dates = daily.get("time") or []
        bundled = self._aggregate_rows(dates, daily, 0, len(dates))
        aggregates = bundled["aggregates"]
        rows = bundled["rows"]
        cell_dates = bundled["dates"]

        variables: Dict[str, Dict[str, Any]] = {}
        for variable, item in aggregates.items():
            variables[variable] = {
                "value": item.get("value"),
                "unit": _POINT_UNITS.get(variable),
                "aggregation": item.get("aggregation"),
                "available": True,
                "reason": None,
            }
        for variable in ("relative_humidity", "visibility"):
            variables[variable] = {
                "value": None,
                "unit": None,
                "aggregation": None,
                "available": False,
                "reason": "Not exposed by the ERA5 daily archive — reported honestly as not available.",
            }

        daily_rows: List[Dict[str, Optional[Any]]] = []
        for idx, day_date in enumerate(cell_dates):
            def _v(col: str, default: Optional[float] = None) -> Optional[float]:
                values = rows.get(col, [])
                return values[idx] if idx < len(values) else default

            daily_rows.append(
                {
                    "date": day_date,
                    "temperature_2m_max": _round2(_v("temperature_2m_max")),
                    "temperature_2m_min": _round2(_v("temperature_2m_min")),
                    "temperature_2m_mean": _round2(_v("temperature_2m_mean")),
                    "precipitation_mm": _round2(_v("precipitation_sum")),
                    "weather_code": _v("weather_code"),
                    "wind_speed_10m_max": _round2(_v("wind_speed_10m_max")),
                    "wind_gusts_10m_max": _round2(_v("wind_gusts_10m_max")),
                    "surface_pressure_mean": _round2(_v("surface_pressure_mean")),
                    "wind_direction_10m_dominant": _round2(_v("wind_direction_10m_dominant")),
                }
            )

        top_rain = None
        top_val = aggregates.get("top_rain_day_mm")
        if top_val and top_val.get("value") is not None:
            precip_vals = rows.get("precipitation_sum") or []
            top_idx = None
            top_v: Optional[float] = None
            for idx, v in enumerate(precip_vals):
                if v is None:
                    continue
                if top_v is None or float(v) > top_v:
                    top_v = float(v)
                    top_idx = idx
            # Only name a wettest day when rain actually fell; a dry month has
            # no wettest day (honest None rather than an arbitrary "day 1, 0 mm").
            if top_v is not None and top_v > 0 and top_idx is not None and top_idx < len(cell_dates):
                top_rain = {"date": cell_dates[top_idx], "mm": top_val.get("value")}

        payload = {
            "latitude": lat,
            "longitude": lng,
            "data_status": "HISTORICAL",
            "data_source": HISTORICAL_SOURCE,
            "provider": HISTORICAL_PROVIDER_NAME,
            "provider_role": "historical",
            "dataset": HISTORICAL_DATASET,
            "is_historical": True,
            "year": int(year),
            "month": int(month),
            "period": f"{start}/{end}",
            "variables": variables,
            "top_rain_day": None if top_rain is None else {"date": top_rain["date"], "mm": top_rain["mm"]},
            "daily": daily_rows,
            "computed_at": now,
            "reason": None,
        }
        self._point_cache.set(point_key, payload, config.HISTORICAL_WEATHER_CACHE_TTL_SEC)
        return payload

    # -------------------------------- grid ----------------------------------

    def fetch_grid(
        self,
        north: float,
        south: float,
        east: float,
        west: float,
        step: float,
        max_points: int,
        variable: str,
        year: int,
        month: int,
        day: int = 0,
        session: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Historical grid layer for one variable over a completed month — or,
        when `day` is 1..N, that single day of that month.

        Returns a WeatherGridResponse-shaped payload (data_status HISTORICAL
        with provenance) so the frontend can render it identically to a live
        grid. `day == 0` (the default) is the monthly aggregate grid."""
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        d = int(day)
        if d < 0:
            raise ValueError("day must be 0 (monthly) or 1..N (per-day).")
        is_day = d > 0
        if is_day:
            _, day_last = monthrange(int(year), int(month))
            if d > day_last:
                raise ValueError(
                    f"day {d} out of range for {int(year)}-{int(month):02d} (1..{day_last})"
                )

        if variable in GRID_UNAVAILABLE_VARIABLES:
            points: List[Dict[str, Any]] = []
            cells_unavail, bounds = self._grid_cells(north, south, east, west, step, max_points)
            for cell in cells_unavail:
                points.append(
                    {
                        "latitude": cell["latitude"],
                        "longitude": cell["longitude"],
                        "value": None,
                        "data_status": "UNAVAILABLE",
                        "provider": HISTORICAL_PROVIDER_NAME,
                        "provider_role": "historical",
                        "reason": "Variable not exposed by the ERA5 daily archive.",
                    }
                )
            return {
                "data_status": "UNAVAILABLE",
                "data_source": HISTORICAL_SOURCE,
                "provider": HISTORICAL_PROVIDER_NAME,
                "provider_role": "historical",
                "model": "ERA5 daily reanalysis",
                "variable": variable,
                "day": 0,
                "hour": None,
                "unit": None,
                "bounds": bounds,
                "steps": {"latitude": round(float(step), 5), "longitude": round(float(step), 5)},
                "resolution": {"latitude": round(float(step), 5), "longitude": round(float(step), 5)},
                "valid_time": now,
                "min": None,
                "max": None,
                "derived": False,
                "points": points,
                "computed_at": now,
                "generated_at": now,
                "assumption": "No ERA5 daily field for this variable — not substituted.",
                "reason": "Variable not available for historical mode.",
                "year": int(year),
                "month": int(month),
                "is_historical": True,
                "data_provenance": {
                    "source": HISTORICAL_SOURCE,
                    "dataset": HISTORICAL_DATASET,
                    "year": int(year),
                    "month": int(month),
                    "period": "/".join(_month_period(year, month)[:2]),
                    "aggregation": "n/a",
                },
            }

        if not is_day and variable in PER_DAY_ONLY_GRID_VARIABLES:
            cells_pd, bounds_pd = self._grid_cells(north, south, east, west, step, max_points)
            reason = (
                "Wind direction and wind U-V components are only available "
                "per-day (not as a monthly aggregate)."
            )
            return {
                **self._historical_grid_base(variable, step, bounds_pd, now, int(year), int(month)),
                "data_status": "UNAVAILABLE",
                "reason": reason,
                "points": [
                    {
                        "latitude": cell["latitude"],
                        "longitude": cell["longitude"],
                        "value": None,
                        "data_status": "UNAVAILABLE",
                        "provider": HISTORICAL_PROVIDER_NAME,
                        "provider_role": "historical",
                        "reason": reason,
                    }
                    for cell in cells_pd
                ],
                "min": None,
                "max": None,
            }

        if variable not in GRID_AGGREGATES and variable not in PER_DAY_ONLY_GRID_VARIABLES:
            raise ValueError(
                f"variable must be one of {HISTORICAL_GRID_VARIABLES}"
            )

        reason_month = _assert_completed_month(year, month)
        cells, bounds = self._grid_cells(north, south, east, west, step, max_points)
        if not cells:
            return {
                **self._historical_grid_base(variable, step, bounds, now, int(year), int(month)),
                "data_status": "UNAVAILABLE",
                "reason": "No India grid cells after bounds clamping.",
                "points": [],
                "min": None,
                "max": None,
            }
        if reason_month:
            return {
                **self._historical_grid_base(variable, step, bounds, now, int(year), int(month)),
                "data_status": "UNAVAILABLE",
                "reason": reason_month,
                "points": [
                    {
                        "latitude": cell["latitude"],
                        "longitude": cell["longitude"],
                        "value": None,
                        "data_status": "UNAVAILABLE",
                        "provider": HISTORICAL_PROVIDER_NAME,
                        "provider_role": "historical",
                        "reason": reason_month,
                    }
                    for cell in cells
                ],
                "min": None,
                "max": None,
            }

        if is_day:
            return self._fetch_grid_day(
                variable, int(year), int(month), d, cells, bounds, step, now, session
            )

        col, aggregation, unit = GRID_AGGREGATES[variable]
        # The served monthly grid sample (in-memory + persistent) cache row.
        aggregation_row = "thunderstorm_days" if variable == "storm_indicator" else aggregation
        cached = self._read_cached_grid_values(
            session, cells, variable, aggregation_row, int(year), int(month), 0
        )
        batch = max(1, min(1000, config.HISTORICAL_WEATHER_BATCH))
        points_by_key: Dict[str, Dict[str, Any]] = {}
        failures: List[str] = []
        missing = [
            c for c in cells if self._grid_cell_key(c["latitude"], c["longitude"]) not in cached
        ]
        for cell in cells:
            point_key = self._grid_cell_key(cell["latitude"], cell["longitude"])
            if point_key in cached:
                points_by_key[point_key] = self._cached_grid_point(cell, cached[point_key])
        for chunk_start in range(0, len(missing), batch):
            chunk = missing[chunk_start : chunk_start + batch]
            lats = [c["latitude"] for c in chunk]
            lngs = [c["longitude"] for c in chunk]
            try:
                daily = self._fetch_month_daily(lats, lngs, int(year), int(month))
            except HttpFetchError as exc:
                failures.append(str(exc))
                for cell in chunk:
                    point_key = self._grid_cell_key(cell["latitude"], cell["longitude"])
                    points_by_key[point_key] = self._cached_grid_point(
                        cell, None, f"Historical archive unavailable — {exc}"
                    )
                continue
            dates = daily.get("time") or []
            days = len(dates) // len(chunk) if dates else 0
            for index, cell in enumerate(chunk):
                point_key = self._grid_cell_key(cell["latitude"], cell["longitude"])
                bundled = self._aggregate_rows(dates, daily, index, days)
                aggregates = bundled["aggregates"]
                value = None
                if variable == "storm_indicator":
                    value = aggregates.get("thunderstorm_days", {}).get("value")
                else:
                    item = aggregates.get(variable)
                    value = item.get("value") if item else None
                if value is not None:
                    self._write_cached_grid_value(
                        session,
                        cell["latitude"],
                        cell["longitude"],
                        variable,
                        aggregation_row,
                        float(value),
                        int(year),
                        int(month),
                        0,
                    )
                points_by_key[point_key] = self._cached_grid_point(
                    cell,
                    value,
                    None if value is not None else "Archive returned no value for this cell.",
                )
        points = [points_by_key[self._grid_cell_key(c["latitude"], c["longitude"])] for c in cells]

        values = [p["value"] for p in points if p["value"] is not None]
        payload = self._historical_grid_base(variable, step, bounds, now, int(year), int(month))
        payload["unit"] = unit
        payload["min"] = round(min(values), 5) if values else None
        payload["max"] = round(max(values), 5) if values else None
        payload["points"] = points
        payload["valid_time"] = f"{int(year)}-{int(month):02d}"
        if values:
            payload["data_status"] = "HISTORICAL"
            payload["reason"] = (
                None if not failures else "Some cells unavailable: " + "; ".join(failures) + "."
            )
        else:
            payload["data_status"] = "UNAVAILABLE"
            payload["reason"] = (
                "All archive requests failed for this grid: " + "; ".join(failures) + "."
                if failures
                else "Archive returned no values for any cell in this grid."
            )
        payload["assumption"] = f"ERA5 daily {col} aggregated as {aggregation}."
        payload["generated_at"] = now
        payload["data_provenance"] = {
            "source": HISTORICAL_SOURCE,
            "dataset": HISTORICAL_DATASET,
            "year": int(year),
            "month": int(month),
            "period": "/".join(_month_period(year, month)[:2]),
            "aggregation": aggregation,
        }
        return payload

    def _fetch_grid_day(
        self,
        variable: str,
        year: int,
        month: int,
        day: int,
        cells: List[Dict[str, float]],
        bounds: Dict[str, float],
        step: float,
        now: str,
        session: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Per-day grid layer: each cell uses that single day's real ERA5 value.

        Rain accumulation on day N is the real month-to-date cumulative total
        (computed from the full completed-month block, never invented);
        wind_u/wind_v are derived from that day's speed + direction exactly as
        the live map does (km/h -> m/s, u = -speed·sin(dir)). Served samples
        are written to the in-memory + persistent cache keyed on data_day."""
        batch = max(1, min(1000, config.HISTORICAL_WEATHER_BATCH))
        aggregation = _DAY_AGGREGATION.get(variable, "day_value")
        unit = GRID_AGGREGATES[variable][2] if variable in GRID_AGGREGATES else _DAY_ONLY_UNITS[variable]
        derived = variable in ("wind_u", "wind_v")
        cached = self._read_cached_grid_values(
            session, cells, variable, aggregation, int(year), int(month), int(day)
        )
        points_by_key: Dict[str, Dict[str, Any]] = {}
        failures: List[str] = []
        missing = [
            c for c in cells if self._grid_cell_key(c["latitude"], c["longitude"]) not in cached
        ]
        for cell in cells:
            point_key = self._grid_cell_key(cell["latitude"], cell["longitude"])
            if point_key in cached:
                points_by_key[point_key] = self._cached_grid_point(cell, cached[point_key])
        for chunk_start in range(0, len(missing), batch):
            chunk = missing[chunk_start : chunk_start + batch]
            lats = [c["latitude"] for c in chunk]
            lngs = [c["longitude"] for c in chunk]
            try:
                if variable == "precipitation_accumulation":
                    daily = self._fetch_month_daily(lats, lngs, int(year), int(month))
                    dates = daily.get("time") or []
                    days_in = len(dates) // len(chunk) if dates else 0
                else:
                    daily = self._fetch_day_daily(lats, lngs, int(year), int(month), day)
                    dates = daily.get("time") or []
                    days_in = 1
            except HttpFetchError as exc:
                failures.append(str(exc))
                for cell in chunk:
                    point_key = self._grid_cell_key(cell["latitude"], cell["longitude"])
                    points_by_key[point_key] = self._day_cell_unavailable(
                        cell, f"Historical archive unavailable — {exc}"
                    )
                continue
            for index, cell in enumerate(chunk):
                point_key = self._grid_cell_key(cell["latitude"], cell["longitude"])
                value = self._day_cell_value(variable, daily, dates, days_in, index, int(day))
                if value is not None:
                    self._write_cached_grid_value(
                        session,
                        cell["latitude"],
                        cell["longitude"],
                        variable,
                        aggregation,
                        float(value),
                        int(year),
                        int(month),
                        int(day),
                    )
                points_by_key[point_key] = self._cached_grid_point(
                    cell,
                    value,
                    None if value is not None else "Archive returned no value for this cell.",
                )
        points = [points_by_key[self._grid_cell_key(c["latitude"], c["longitude"])] for c in cells]

        values = [p["value"] for p in points if p["value"] is not None]
        payload = self._historical_grid_base(variable, step, bounds, now, int(year), int(month))
        payload["day"] = int(day)
        payload["valid_time"] = f"{int(year)}-{int(month):02d}-{int(day):02d}"
        payload["unit"] = unit
        payload["derived"] = derived
        payload["min"] = round(min(values), 5) if values else None
        payload["max"] = round(max(values), 5) if values else None
        payload["points"] = points
        if values:
            payload["data_status"] = "HISTORICAL"
            payload["reason"] = (
                None if not failures else "Some cells unavailable: " + "; ".join(failures) + "."
            )
        else:
            payload["data_status"] = "UNAVAILABLE"
            payload["reason"] = (
                "All archive requests failed for this grid: " + "; ".join(failures) + "."
                if failures
                else "Archive returned no values for any cell in this grid."
            )
        payload["assumption"] = f"ERA5 daily {variable} for {int(year)}-{int(month):02d}-{int(day):02d}."
        payload["generated_at"] = now
        payload["data_provenance"] = {
            "source": HISTORICAL_SOURCE,
            "dataset": HISTORICAL_DATASET,
            "year": int(year),
            "month": int(month),
            "period": f"{int(year)}-{int(month):02d}-{int(day):02d}",
            "aggregation": aggregation,
        }
        return payload

    @staticmethod
    def _day_cell_unavailable(cell: Dict[str, float], reason: str) -> Dict[str, Any]:
        return {
            "latitude": cell["latitude"],
            "longitude": cell["longitude"],
            "value": None,
            "data_status": "UNAVAILABLE",
            "provider": HISTORICAL_PROVIDER_NAME,
            "provider_role": "historical",
            "reason": reason,
        }

    def _day_cell_value(
        self,
        variable: str,
        daily: Dict[str, Any],
        dates: List[str],
        days_in: int,
        index: int,
        day: int,
    ) -> Optional[float]:
        if variable == "precipitation_accumulation":
            rows = {
                col: daily.get(col, [])[index * days_in : (index + 1) * days_in]
                for col in _DAILY_COLUMNS
            }
            prec = rows.get("precipitation_sum") or []
            return _round2(_monthly_sum(prec[:day]))

        def _col(name: str) -> Optional[float]:
            vals = daily.get(name) or []
            return vals[index] if index < len(vals) else None

        speed = _col("wind_speed_10m_max")
        if variable in ("wind_u", "wind_v"):
            direction = _col("wind_direction_10m_dominant")
            if speed is None or direction is None:
                return None
            rad = math.radians(float(direction))
            ws_ms = float(speed) / 3.6
            if variable == "wind_u":
                return _round2(-ws_ms * math.sin(rad))
            return _round2(-ws_ms * math.cos(rad))

        if variable == "wind_direction_10m":
            return _round2(_col("wind_direction_10m_dominant"))

        bundled = self._aggregate_rows(dates, daily, index, 1)
        aggregates = bundled["aggregates"]
        if variable == "storm_indicator":
            return aggregates.get("thunderstorm_days", {}).get("value")
        item = aggregates.get(variable)
        return item.get("value") if item else None

    def _historical_grid_base(
        self, variable: str, step: float, bounds: Dict[str, float], now: str, year: int, month: int
    ) -> Dict[str, Any]:
        return {
            "data_status": "UNAVAILABLE",
            "data_source": HISTORICAL_SOURCE,
            "provider": HISTORICAL_PROVIDER_NAME,
            "provider_role": "historical",
            "model": "ERA5 daily reanalysis",
            "variable": variable,
            "day": 0,
            "hour": None,
            "unit": None,
            "bounds": bounds,
            "steps": {"latitude": round(float(step), 5), "longitude": round(float(step), 5)},
            "resolution": {"latitude": round(float(step), 5), "longitude": round(float(step), 5)},
            "valid_time": None,
            "min": None,
            "max": None,
            "derived": False,
            "points": [],
            "computed_at": now,
            "generated_at": now,
            "assumption": None,
            "reason": None,
            "year": int(year),
            "month": int(month),
            "is_historical": True,
            "data_provenance": {
                "source": HISTORICAL_SOURCE,
                "dataset": HISTORICAL_DATASET,
                "year": int(year),
                "month": int(month),
                "period": "/".join(_month_period(year, month)[:2]),
                "aggregation": "n/a",
            },
        }


historical_weather = HistoricalWeatherProvider()