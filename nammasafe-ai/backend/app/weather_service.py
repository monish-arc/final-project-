"""Live weather service with Open-Meteo as the primary provider, the free
ECMWF (IFS 0.25°, via Open-Meteo) model as the always-present backup, and IMD
(Mausam) retained as a LEGACY opt-in provider for backward compatibility.

Provider chain (default config):
    primary: Open-Meteo (keyless, https://api.open-meteo.com/v1)
    backup : ECMWF via Open-Meteo /ecmwf (IFS 0.25°)
    legacy : IMD Mausam "Current Weather" — ONLY when BOTH IMD_MAUSAM_BASE_URL
             and IMD_MAUSAM_TOKEN are configured (then it becomes the first
             provider tried; Open-Meteo is used only if IMD is unusable).

Every response carries an explicit status so callers can never mistake fallback
"data not available" output for real observations and data providers label
themselves on every payload:
  LIVE          -> real current/forecast weather for the requested point
  UNAVAILABLE   -> upstream unreachable/no usable data (no fabricated values)
  provider      -> which provider actually served the payload
  provider_role -> primary | backup | legacy

The API exposes a point endpoint (get_weather) and a nationwide grid endpoint
(get_grid_samples) that reuses the per-point payloads via a coarse rounded-cell
cache so repeated views never hammer the upstream.
"""

from __future__ import annotations

import math
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional

from app import config
from app import weather_platform
from app.cache import TTLCache
from app.http_client import HttpFetchError, http_get

# ECMWF (IFS 0.25°) does not provide every variable Open-Meteo does. These are
# the variables the grid layer offers that are genuinely absent from ECMWF.
ECMWF_MISSING_CURRENT = ("relative_humidity", "pressure_msl")

# Grid layer variables accepted by /api/weather/grid. Names match the Open-Meteo
# variable vocabulary so the frontend can label units directly. The intraday
# timeline (now..+47h) is served through the `hour` parameter (hour offset from
# "now", 0..47) reading the hourly block of the serving provider; the daily
# stops (+2d..+7d) reuse the `day` parameter.
#
# Provenance notes (nothing here is invented):
#   * wind_u / wind_v are DERIVED deterministically from the provider-reported
#     wind_speed_10m + wind_direction_10m (meteorological convention:
#     u = -ws*sin(dir), v = -ws*cos(dir), ws in m/s). The payload states this
#     in `assumption`/`derived` — the provider itself does not expose u/v.
#   * apparent_temperature / visibility come from the current-conditions block
#     only (the hourly block of the backup provider does not carry them), so
#     those layers are served for the "now" stop and honestly empty elsewhere.
GRID_VARIABLES: tuple[str, ...] = (
    "temperature_2m",
    "precipitation",
    "precipitation_probability",
    "wind_speed_10m",
    "wind_gusts_10m",
    "cloud_cover",
    "precipitation_accumulation",
    "storm_indicator",
    "relative_humidity",
    "pressure_msl",
    "wind_direction_10m",
    "wind_u",
    "wind_v",
    "apparent_temperature",
    "visibility",
)

# Open-Meteo caps a single multi-location request; keep chunks under that.
BATCH_SIZE = max(1, min(1000, config.WEATHER_BATCH_SIZE))

# ---------------- upstream rate-limit + concurrency guards ----------------

# After a provider answers HTTP 429 we park calls to it until the cooldown
# expires (Retry-After wins when present). This is what stops a scrubbing
# timeline from hammering api.open-meteo.com into a sustained burst limit.
_PROVIDER_COOLDOWN_UNTIL: Dict[str, float] = {}
_PROVIDER_COOLDOWN_LOCK = threading.Lock()

# Upper bound on simultaneous upstream HTTP calls across all providers, so a
# multi-chunk grid view never fires a burst that trips free-tier limiters.
_PROVIDER_HTTP_SEMAPHORE = threading.Semaphore(max(1, config.WEATHER_MAX_CONCURRENT))

# In-flight request deduplication: concurrent identical grid requests share one
# provider fetch instead of issuing duplicate upstream calls.
_INFLIGHT: Dict[str, Dict[str, Any]] = {}
_INFLIGHT_LOCK = threading.Lock()


def _provider_in_cooldown(provider_name: str) -> bool:
    with _PROVIDER_COOLDOWN_LOCK:
        return time.monotonic() < _PROVIDER_COOLDOWN_UNTIL.get(provider_name, 0.0)


def _mark_provider_cooldown(provider_name: str, seconds: float) -> None:
    with _PROVIDER_COOLDOWN_LOCK:
        _PROVIDER_COOLDOWN_UNTIL[provider_name] = time.monotonic() + max(1.0, float(seconds))


def _retry_after_seconds(headers: Any, default_seconds: int) -> int:
    """Respect Retry-After (integer seconds or HTTP-date) when provided."""
    try:
        raw = headers.get("retry-after") or headers.get("Retry-After")
        if not raw:
            return max(1, int(default_seconds))
        value = str(raw).strip()
        if value.isdigit():
            return max(1, min(60, int(value)))
        parsed = parsedate_to_datetime(value)
        remaining = int((parsed.timestamp() - time.time()))
        return max(1, min(60, remaining))
    except Exception:
        return max(1, int(default_seconds))


# Single-flight helpers: one leader computes, concurrent waiters share it.
def _inflight_acquire(key: str) -> tuple[Dict[str, Any], bool]:
    with _INFLIGHT_LOCK:
        slot = _INFLIGHT.get(key)
        if slot is not None:
            return slot, False
        slot = {"event": threading.Event(), "value": None}
        _INFLIGHT[key] = slot
        return slot, True


def _inflight_wait(slot: Dict[str, Any], timeout: float = 120.0) -> Any:
    slot["event"].wait(timeout=timeout)
    return slot["value"]


def _inflight_done(key: str, slot: Dict[str, Any], value: Any) -> None:
    with _INFLIGHT_LOCK:
        slot["value"] = value
        if _INFLIGHT.get(key) is slot:
            _INFLIGHT.pop(key, None)
    slot["event"].set()


def _imd_configured() -> bool:
    """IMD (Mausam) is opted-in only when both base URL and token exist."""
    return bool(config.IMD_MAUSAM_BASE_URL and config.IMD_MAUSAM_TOKEN)


def _imd_fetch(latitude: float, longitude: float) -> Dict[str, Any]:
    """IMD Mausam 'current weather' lookup; raises HttpFetchError when unusable."""
    url = config.IMD_MAUSAM_BASE_URL.rstrip("/") + "/currweather/location"
    params = {"lat": latitude, "lon": longitude, "token": config.IMD_MAUSAM_TOKEN}
    response = http_get(url, params=params, timeout=config.IMD_MAUSAM_TIMEOUT_SEC)
    if response.status_code >= 400:
        raise HttpFetchError(f"IMD Mausam rejected ({response.status_code})")
    try:
        body = response.json()
    except (ValueError, TypeError):
        raise HttpFetchError("Non-JSON response from IMD Mausam")
    current = _extract_imd_current(body)
    if current is None:
        raise HttpFetchError("IMD Mausam response had no usable current weather")
    return current

# WMO weather codes -> human-readable description + a coarse rain intensity.
_WMO_CODES: Dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}

_missing: Dict[str, Any] = {}


def _rain_intensity(precip_mm: Optional[float], weather_code: Optional[int]) -> str:
    """Coarse IMD-style intensity band from precipitation + weather code."""
    if precip_mm is not None:
        if precip_mm <= 0.0:
            return "NONE"
        if precip_mm < 2.5:
            return "LIGHT"
        if precip_mm < 7.6:
            return "MODERATE"
        if precip_mm < 50.0:
            return "HEAVY"
        return "VIOLENT"
    code = weather_code if weather_code is not None else -1
    if code in (65, 67, 82, 95, 96, 99):
        return "HEAVY"
    if code in (63, 66, 81, 80):
        return "MODERATE"
    if code in (51, 53, 55, 56, 57, 61):
        return "LIGHT"
    return "NONE"


def _describe(code: Optional[int]) -> str:
    if code is None:
        return "Unknown"
    return _WMO_CODES.get(code, f"WMO code {code}")


def _rain_intensity_from_text(text: Optional[str]) -> str:
    """Coarse IMD-style intensity band derived from free-text weather conditions."""
    if not text:
        return "NONE"
    t = text.lower()
    if any(k in t for k in ("violent", "extremely heavy", "very heavy")):
        return "VIOLENT"
    if any(k in t for k in ("heavy", "thunderstorm", "storm", "squall")):
        return "HEAVY"
    if any(k in t for k in ("moderate", "showers")):
        return "MODERATE"
    if any(k in t for k in ("drizzle", "light rain")):
        return "LIGHT"
    if "rain" in t or "wet" in t:
        return "LIGHT"
    return "NONE"


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _wind_component(component: str, speed_kmh: float, direction_deg: float) -> float:
    """Meteorological u/v wind components (m/s) from speed (km/h) + direction (°).

    The provider reports wind as speed + the direction the wind comes FROM
    (degrees clockwise from north). Standard conversion to eastward u and
    northward v (in m/s, using the convention returned by the forecast API):
        u = -ws * sin(theta)
        v = -ws * cos(theta)
    with ws converted to m/s. The result advects particles downwind, matching
    how flow fields are drawn on wind maps.
    """
    ws = max(0.0, float(speed_kmh)) / 3.6
    theta = math.radians(float(direction_deg % 360.0))
    if component == "wind_u":
        return round(-ws * math.sin(theta), 5)
    return round(-ws * math.cos(theta), 5)


def _imd_search(node: Any, keys: tuple[str, ...]) -> Any:
    """Depth-first search for the first non-empty value under any of `keys`."""
    if isinstance(node, dict):
        for key in keys:
            if key in node and node[key] not in (None, ""):
                return node[key]
        for child in node.values():
            found = _imd_search(child, keys)
            if found is not None:
                return found
    elif isinstance(node, list):
        for child in node:
            found = _imd_search(child, keys)
            if found is not None:
                return found
    return None


def _extract_imd_current(body: Any) -> Optional[Dict[str, Any]]:
    """Tolerantly pull current-weather fields out of an IMD Mausam response.

    No value is invented: if no numeric temperature can be located the whole
    response is treated as unusable and the caller falls back to Open-Meteo.
    """
    temp_raw = _imd_search(body, ("temp", "temperature_c", "temp_c", "temperatureC", "t"))
    temp_c = _to_float(temp_raw)
    if temp_c is None:
        return None
    humidity = _to_float(_imd_search(body, ("humidity", "relative_humidity", "rh")))
    wind = _to_float(
        _imd_search(body, ("windSpeed", "wind_speed_kmh", "windSpeedKmh", "windspeed", "wind_kmh"))
    )
    description = _imd_search(
        body,
        ("weatherDesc", "weather_desc", "condition", "description", "wx", "weather", "weatherText"),
    )
    observed_at = _imd_search(
        body, ("time", "datetime", "date_time", "observedAt", "observeTime", "updatedAt")
    )
    return {
        "temperature_c": temp_c,
        "relative_humidity_percent": humidity,
        "wind_speed_kmh": wind,
        "weather_description": str(description) if description is not None else None,
        "observed_at": str(observed_at) if observed_at is not None else None,
    }


def _point_key(latitude: float, longitude: float, days: int) -> str:
    return f"weather:{round(latitude, 4)}:{round(longitude, 4)}:{int(days)}"


class WeatherProvider:
    """Open-Meteo-style forecast endpoint (primary: Open-Meteo, backup: ECMWF).

    Both are served from the same /forecast contract so one parser handles
    either; only the base URL, model hint and variable availability differ.
    """

    name = "Open-Meteo"
    role = "primary"
    dataset = "Open-Meteo Global Forecast (GFS Seamless + ICON)"
    model_hint: Optional[str] = None
    _base_url = config.OPEN_METEO_BASE_URL
    _timeout = config.WEATHER_TIMEOUT_SEC
    _models: Dict[str, Any] = {}

    def configured(self) -> bool:
        """A provider is usable under the current configuration."""
        return True

    def status(self) -> str:
        return "LIVE" if self.configured() else "NOT_CONFIGURED"

    # ---------------- provider-adapter contract ----------------
    # Each provider implements the 4 adapter methods below. The grid/point
    # services call fetch/fetch_many; the adapter methods exist so any consumer
    # (e.g. a dedicated weather-map provider chain) can treat every provider
    # uniformly: get_current (now), get_forecast (daily), get_grid (bounds
    # sampling) and get_available_times (hourly + daily timestamps actually
    # returned). No value is invented — unavailable stops simply come back empty.

    def get_current(self, latitude: float, longitude: float) -> Dict[str, Any]:
        payload = self.fetch(latitude, longitude, days=1)
        return {
            "time": (payload.get("current") or {}).get("time"),
            "data": payload.get("current") or {},
            "provider": self.name,
            "role": self.role,
            "model": payload.get("model"),
            "data_status": "LIVE" if payload.get("current") else "UNAVAILABLE",
        }

    def get_forecast(self, latitude: float, longitude: float, days: int = 7) -> Dict[str, Any]:
        payload = self.fetch(latitude, longitude, days=days)
        return {
            "daily": payload.get("daily") or {},
            "hourly": payload.get("hourly") or {},
            "provider": self.name,
            "role": self.role,
            "model": payload.get("model"),
            "data_status": "LIVE" if payload.get("daily") else "UNAVAILABLE",
        }

    def get_available_times(
        self, latitude: float, longitude: float, days: int = 7
    ) -> Dict[str, Any]:
        payload = self.fetch(latitude, longitude, days=days)
        hourly = payload.get("hourly") or {}
        daily = payload.get("daily") or {}
        return {
            "hours": hourly.get("time") or [],
            "days": daily.get("time") or [],
            "provider": self.name,
            "role": self.role,
            "model": payload.get("model"),
            "data_status": "LIVE" if hourly.get("time") or daily.get("time") else "UNAVAILABLE",
        }

    def get_grid(
        self,
        north: float,
        south: float,
        east: float,
        west: float,
        *,
        step: float = 0.25,
        max_points: int = 600,
        variable: str = "wind_u",
        hour: Optional[int] = None,
        day: int = 0,
        days: int = 7,
    ) -> Dict[str, Any]:
        """Sample the grid for THIS provider alone (no fallback).

        Used by the weather-map pipeline to honour an explicit provider
        preference. Raises HttpFetchError when the provider is unusable so the
        caller can fall back honestly.
        """
        from datetime import datetime as _dt

        cells = _provider_grid_cells(north, south, east, west, step, max_points)
        if not cells:
            return {
                "data_status": "UNAVAILABLE",
                "provider": self.name,
                "variable": variable,
                "points": [],
                "reason": "No India grid cells after bounds clamping.",
            }
        coords = [(c["latitude"], c["longitude"]) for c in cells]
        indices = list(range(len(cells)))
        if not self.configured():
            raise HttpFetchError(f"{self.name} is not configured")
        if hour is not None:
            raw = self.fetch_many(coords, indices, days=days, include_hourly=True)
            points = _hour_cell_points(cells, raw, variable, int(hour))
        else:
            raw = self.fetch_many(coords, indices, days=days, include_hourly=False)
            points = _day_cell_points(cells, raw, variable, int(day))
        values = [float(v) for p in points for v in [p.get("value")] if v is not None]
        return {
            "data_status": "LIVE" if values else "UNAVAILABLE",
            "provider": self.name,
            "provider_role": self.role,
            "model": None,
            "variable": variable,
            "day": int(day) if hour is None else 0,
            "hour": hour,
            "unit": _GRID_UNITS.get(variable),
            "bounds": _actual_bounds_cells(north, south, east, west),
            "steps": {"latitude": round(step, 5), "longitude": round(step, 5)},
            "resolution": {"latitude": round(step, 5), "longitude": round(step, 5)},
            "valid_time": None,
            "min": round(float(min(values)), 5) if values else None,
            "max": round(float(max(values)), 5) if values else None,
            "derived": variable in ("wind_u", "wind_v"),
            "points": points,
            "computed_at": _dt.utcnow().isoformat(),
            "generated_at": _dt.utcnow().isoformat(),
            "assumption": "Grid sampled from this provider only (no fallback).",
            "reason": None,
        }

    #: Variables expected in the current + daily blocks. Backups (ECMWF) do not
    #: provide every one of them; missing values stay None on the payload.
    _current_vars = (
        "temperature_2m,relative_humidity_2m,precipitation,weather_code,"
        "wind_speed_10m,wind_gusts_10m,pressure_msl,surface_pressure,cloud_cover,"
        "apparent_temperature,dew_point_2m,wind_direction_10m,uv_index,visibility"
    )
    _daily_vars = (
        "temperature_2m_max,temperature_2m_min,precipitation_sum,"
        "precipitation_probability_max,wind_speed_10m_max,weather_code"
    )
    _hourly_vars = (
        "temperature_2m,precipitation,precipitation_probability,weather_code,"
        "wind_speed_10m,wind_direction_10m,wind_gusts_10m,relative_humidity_2m,cloud_cover"
    )

    def params(self, days: int, include_hourly: bool = True) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "current": self._current_vars,
            "daily": self._daily_vars,
            "forecast_days": max(1, min(10, int(days))),
        }
        if include_hourly:
            params["hourly"] = self._hourly_vars
        if self._models:
            params["models"] = ",".join(self._models)
        return params

    def fetch(self, latitude: float, longitude: float, days: int = 7) -> Dict[str, Any]:
        if _provider_in_cooldown(self.name):
            raise HttpFetchError(f"{self.name} throttled (429 cooldown active)")
        params = self.params(days)
        params["latitude"] = latitude
        params["longitude"] = longitude
        params["timezone"] = "auto"
        return self._request(params)

    def fetch_many(
        self,
        points: List[tuple[float, float]],
        indices: List[int],
        days: int = 7,
        include_hourly: bool = True,
    ) -> Dict[int, Any]:
        """Multi-location request (Open-Meteo comma-separated lat/lon arrays).

        Returns {requested_index: raw JSON item} aligned with `indices`. The
        caller decides caching; provider failures raise HttpFetchError.
        """
        if _provider_in_cooldown(self.name):
            raise HttpFetchError(f"{self.name} throttled (429 cooldown active)")
        base_params = self.params(days, include_hourly=include_hourly)
        result: Dict[int, Any] = {}
        for offset in range(0, len(indices), BATCH_SIZE):
            chunk = indices[offset : offset + BATCH_SIZE]
            lats = ",".join(f"{points[i][0]:.5f}" for i in chunk)
            lons = ",".join(f"{points[i][1]:.5f}" for i in chunk)
            params = dict(base_params)
            params["latitude"] = lats
            params["longitude"] = lons
            params["timezone"] = "UTC"
            body = self._request(params)
            items = body if isinstance(body, list) else [body]
            for cell_index, item in zip(chunk, items):
                if isinstance(item, dict) and item.get("error"):
                    result[cell_index] = None
                    continue
                result[cell_index] = item
        return result

    def _request(self, params: Dict[str, Any]) -> Any:
        # A provider that recently answered 429 is skipped entirely (no network
        # call) until its cooldown lapses, so a scrubbing timeline never hammers
        # a throttled upstream. On a live 429 we park the provider using
        # Retry-After when the upstream supplies it.
        if _provider_in_cooldown(self.name):
            raise HttpFetchError(f"{self.name} throttled (429 cooldown active)")
        for attempt, backoff in enumerate((0.0, 2.0, 5.0)):
            if backoff:
                time.sleep(backoff)
                if _provider_in_cooldown(self.name):
                    raise HttpFetchError(f"{self.name} throttled (429 cooldown active)")
            with _PROVIDER_HTTP_SEMAPHORE:
                response = http_get(
                    f"{self._base_url}/forecast", params=params, timeout=self._timeout
                )
            if response.status_code == 429:
                _mark_provider_cooldown(
                    self.name, _retry_after_seconds(response.headers, config.WEATHER_PROVIDER_COOLDOWN_SEC)
                )
                if attempt < 2:
                    continue
            if response.status_code >= 400:
                raise HttpFetchError(f"{self.name} rejected ({response.status_code})")
            try:
                return response.json()
            except (ValueError, TypeError):
                raise HttpFetchError(f"Non-JSON response from {self.name}")
        raise HttpFetchError(f"{self.name} rejected (429)")  # pragma: no cover


class ECMWFFProvider(WeatherProvider):
    """ECMWF IFS 0.25° served through the Open-Meteo /ecmwf endpoint.

    This is the honest backup: it cannot provide relative humidity, pressure or
    precipitation probability, so those payload fields stay null when ECMWF is
    serving. Only variables the model actually exposes are requested — never
    asked for variables, so the request cannot be rejected wholesale.
    temperature / precipitation / wind / cloud / weather-code are fully covered.
    """

    name = "ECMWF"
    role = "backup"
    dataset = "ECMWF IFS HRES 0.25° (via Open-Meteo)"
    _base_url = config.ECMWF_BASE_URL
    _models = {"ecmwf_ifs025": None}
    _current_vars = (
        "temperature_2m,precipitation,weather_code,"
        "wind_speed_10m,wind_gusts_10m,cloud_cover,visibility,wind_direction_10m"
    )
    _daily_vars = "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max,weather_code"
    _hourly_vars = "temperature_2m,precipitation,weather_code,wind_speed_10m,wind_direction_10m,wind_gusts_10m,cloud_cover"


class IMDProvider(WeatherProvider):
    """IMD Mausam 'Current Weather' as a first-class weather provider.

    Tier-1 preferred India source: when IMD_MAUSAM_BASE_URL and IMD_MAUSAM_TOKEN
    are BOTH configured, this provider is tried first in the single-point chain
    (IMD -> Open-Meteo -> ECMWF) and otherwise reports NOT_CONFIGURED — never a
    fabricated observation. It serves current conditions only, so the forecast
    and hourly arrays stay empty and the payload keeps provider_role=legacy for
    backward compatibility with existing consumers. IMD exposes no batched grid
    endpoint, so fetch_many raises and the grid path never touches it.
    """

    name = "IMD"
    role = "legacy"
    dataset = "IMD Mausam (Current Weather)"

    def configured(self) -> bool:
        return _imd_configured()

    def fetch(self, latitude: float, longitude: float, days: int = 7) -> Dict[str, Any]:
        return _imd_fetch(latitude, longitude)

    def fetch_many(
        self,
        points: List[tuple[float, float]],
        indices: List[int],
        days: int = 7,
        include_hourly: bool = True,
    ) -> Dict[int, Any]:
        raise HttpFetchError("IMD does not expose a batched grid endpoint")


class WeatherService:
    def __init__(self, base_url: Optional[str] = None) -> None:
        self._provider_imd = IMDProvider()
        self._provider_primary = WeatherProvider()
        self._provider_backup = ECMWFFProvider()
        self._cache = TTLCache(config.WEATHER_CACHE_TTL_SEC)
        self._grid_cache = TTLCache(config.WEATHER_GRID_CACHE_TTL_SEC)
        self._provider_chain: tuple[WeatherProvider, ...] = (
            self._provider_imd,
            self._provider_primary,
            self._provider_backup,
        )

    # ---------------- upstream reads ----------------

    def _fetch(self, latitude: float, longitude: float, days: int, provider: WeatherProvider) -> Dict[str, Any]:
        response = provider.fetch(latitude, longitude, days=days)
        return response if isinstance(response, dict) else {}

    # ---------------- payload builders ----------------

    def _build_imd_payload(
        self,
        latitude: float,
        longitude: float,
        current: Dict[str, Any],
        provider: Optional[WeatherProvider] = None,
    ) -> Dict[str, Any]:
        source = provider or self._provider_imd
        description = current.get("weather_description")
        return {
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "data_status": "LIVE",
            "data_source": "IMD · Mausam (Current Weather)",
            "provider": source.name,
            "provider_role": source.role,
            "dataset": source.dataset,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model": None,
            "generationtime_ms": None,
            "elevation_actual": None,
            "timezone": None,
            "units": {},
            "observed_at": current.get("observed_at"),
            "current": {
                "temperature_c": current.get("temperature_c"),
                "relative_humidity_percent": current.get("relative_humidity_percent"),
                "precipitation_mm": None,
                "rain_intensity": _rain_intensity_from_text(description),
                "weather_code": None,
                "weather_description": description,
                "wind_speed_kmh": current.get("wind_speed_kmh"),
                "wind_gusts_kmh": None,
                "pressure_hpa": None,
                "cloud_cover_percent": None,
                "wind_direction_deg": None,
                "apparent_temperature_c": None,
                "dewpoint_c": None,
                "uv_index": None,
                "visibility_km": None,
            },
            "hourly": [],
            "forecast": [],
            "reason": None,
        }

    def _build_payload(
        self,
        latitude: float,
        longitude: float,
        data: Dict[str, Any],
        provider_name: str,
        provider_role: str,
        model: Optional[str],
        days: int,
        dataset: Optional[str] = None,
    ) -> Dict[str, Any]:
        current = data.get("current", {}) or {}
        daily = data.get("daily", {}) or {}
        hourly = data.get("hourly", {}) or {}

        forecast: list[Dict[str, Any]] = []
        dates = daily.get("time", []) or []
        for idx, day in enumerate(dates):
            probability = None
            if daily.get("precipitation_probability_max"):
                probability = daily["precipitation_probability_max"][idx]
            code = None
            if daily.get("weather_code"):
                code = daily["weather_code"][idx]
            forecast.append(
                {
                    "date": day,
                    "max_temp_c": daily.get("temperature_2m_max", [None,])[idx] if daily.get("temperature_2m_max") else None,
                    "min_temp_c": daily.get("temperature_2m_min", [None,])[idx] if daily.get("temperature_2m_min") else None,
                    "precipitation_mm": daily.get("precipitation_sum", [None,])[idx] if daily.get("precipitation_sum") else None,
                    "precipitation_probability_percent": probability,
                    "wind_speed_kmh": daily.get("wind_speed_10m_max", [None,])[idx] if daily.get("wind_speed_10m_max") else None,
                    "weather_code": code,
                    "weather_description": _describe(code),
                }
            )

        hourly_rows: list[Dict[str, Any]] = []
        times = hourly.get("time", []) or []
        for idx, ts in enumerate(times):
            code = hourly.get("weather_code", [None,])[idx] if hourly.get("weather_code") else None
            hourly_rows.append(
                {
                    "time": ts,
                    "temperature_c": hourly.get("temperature_2m", [None,])[idx] if hourly.get("temperature_2m") else None,
                    "precipitation_mm": hourly.get("precipitation", [None,])[idx] if hourly.get("precipitation") else None,
                    "precipitation_probability_percent": hourly.get("precipitation_probability", [None,])[idx] if hourly.get("precipitation_probability") else None,
                    "weather_code": code,
                    "weather_description": _describe(code),
                    "wind_speed_kmh": hourly.get("wind_speed_10m", [None,])[idx] if hourly.get("wind_speed_10m") else None,
                    "wind_direction_deg": hourly.get("wind_direction_10m", [None,])[idx] if hourly.get("wind_direction_10m") else None,
                    "relative_humidity_percent": hourly.get("relative_humidity_2m", [None,])[idx] if hourly.get("relative_humidity_2m") else None,
                    "wind_gusts_kmh": hourly.get("wind_gusts_10m", [None,])[idx] if hourly.get("wind_gusts_10m") else None,
                    "cloud_cover_percent": hourly.get("cloud_cover", [None,])[idx] if hourly.get("cloud_cover") else None,
                }
            )

        code = current.get("weather_code")
        precip = current.get("precipitation")
        return {
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "data_status": "LIVE",
            "data_source": provider_name,
            "provider": provider_name,
            "provider_role": provider_role,
            "dataset": dataset,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model": data.get("model") or model,
            "generationtime_ms": data.get("generationtime_ms"),
            "elevation_actual": _to_float(data.get("elevation")),
            "timezone": data.get("timezone"),
            "units": dict(data.get("current_units") or {}),
            "observed_at": current.get("time"),
            "current": {
                "temperature_c": current.get("temperature_2m"),
                "relative_humidity_percent": current.get("relative_humidity_2m"),
                "precipitation_mm": precip,
                "rain_intensity": _rain_intensity(precip, code),
                "weather_code": code,
                "weather_description": _describe(code),
                "wind_speed_kmh": current.get("wind_speed_10m"),
                "wind_gusts_kmh": current.get("wind_gusts_10m"),
                "pressure_hpa": current.get("pressure_msl") or current.get("surface_pressure"),
                "cloud_cover_percent": current.get("cloud_cover"),
                "wind_direction_deg": current.get("wind_direction_10m"),
                "apparent_temperature_c": current.get("apparent_temperature"),
                "dewpoint_c": current.get("dew_point_2m"),
                "uv_index": current.get("uv_index"),
                "visibility_km": current.get("visibility"),
            },
            "hourly": hourly_rows,
            "forecast": forecast,
            "reason": None,
        }

    # ---------------- public point lookup ----------------

    def get_weather(self, latitude: float, longitude: float, days: Optional[int] = None) -> Dict[str, Any]:
        if not weather_platform.live_weather_enabled():
            return self._live_disabled_point(latitude, longitude)
        resolved_days = self._resolve_days(days)
        cache_key = _point_key(latitude, longitude, resolved_days)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return self._serve_cached_point(cached)

        failures: list[str] = []

        # 1) IMD provider — tier-1 preferred India source when explicitly
        #    configured; skipped entirely (with no probe) when NOT_CONFIGURED.
        imd_failure: Optional[str] = None
        if self._provider_imd.configured():
            try:
                payload = self._build_imd_payload(
                    latitude, longitude, self._provider_imd.fetch(latitude, longitude)
                )
                self._cache.set(cache_key, payload)
                return payload
            except HttpFetchError as exc:
                imd_failure = str(exc)
                failures.append(f"IMD primary unavailable ({imd_failure})")

        # 2) Open-Meteo primary.
        try:
            payload = self._build_payload(
                latitude,
                longitude,
                self._fetch(latitude, longitude, resolved_days, self._provider_primary),
                self._provider_primary.name,
                self._provider_primary.role,
                self._provider_primary.model_hint,
                resolved_days,
                self._provider_primary.dataset,
            )
        except HttpFetchError as exc:
            failures.append(f"Open-Meteo primary unavailable ({exc})")
        else:
            if imd_failure:
                payload["data_source"] = "Open-Meteo (IMD fallback)"
                payload["reason"] = f"IMD primary unavailable — {imd_failure}"
            self._cache.set(cache_key, payload)
            return payload

        # 3) ECMWF backup.
        try:
            payload = self._build_payload(
                latitude,
                longitude,
                self._fetch(latitude, longitude, resolved_days, self._provider_backup),
                self._provider_backup.name,
                self._provider_backup.role,
                self._provider_backup.model_hint,
                resolved_days,
                self._provider_backup.dataset,
            )
            payload["data_source"] = "ECMWF (Open-Meteo backup)"
            payload["reason"] = (
                "Open-Meteo primary unavailable — ECMWF backup serving. "
                "ECMWF does not provide relative humidity or pressure; "
                "those values are reported as not available."
            )
            self._cache.set(cache_key, payload)
            return payload
        except HttpFetchError as exc:
            failures.append(f"ECMWF backup unreachable ({exc})")

        # 4) Everything failed — never fabricate observations.
        preamble = "Weather upstream unreachable or rejected the request: "
        if failures:
            reason = preamble + "; ".join(failures) + "."
        else:
            reason = preamble + "no weather provider responded."
        unavailable = {
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "data_status": "UNAVAILABLE",
            "data_source": "Open-Meteo/ECMWF",
            "provider": None,
            "provider_role": None,
            "dataset": None,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model": None,
            "generationtime_ms": None,
            "elevation_actual": None,
            "timezone": None,
            "units": {},
            "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "current": None,
            "hourly": [],
            "forecast": [],
            "reason": reason,
        }
        self._cache.set(cache_key, unavailable, ttl_seconds=config.WEATHER_FAILURE_CACHE_TTL_SEC)
        return unavailable

    def _live_disabled_point(self, latitude: float, longitude: float) -> Dict[str, Any]:
        """Honest payload when the live weather API is not configured: the
        status is API_NOT_ADDED — never a fabricated current/forecast block."""
        return {
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "data_status": "API_NOT_ADDED",
            "data_source": "Open-Meteo/ECMWF",
            "provider": None,
            "provider_role": None,
            "dataset": None,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model": None,
            "generationtime_ms": None,
            "elevation_actual": None,
            "timezone": None,
            "units": {},
            "observed_at": None,
            "current": None,
            "hourly": [],
            "forecast": [],
            "reason": (
                "Live weather API not added. Set WEATHER_LIVE_ENABLED=on and register "
                "a live provider in app/weather_platform.py to serve live weather. "
                "Historical completed-month weather is available via the ERA5 archive."
            ),
        }

    def _resolve_days(self, days: Optional[int]) -> int:
        if days is None:
            return max(1, min(7, config.WEATHER_FORECAST_DAYS))
        return max(1, min(7, int(days)))

    # ---------------- public multi-point / grid lookup ----------------

    def get_weather_batch(
        self,
        points: List[tuple[float, float]],
        days: Optional[int] = None,
        include_hourly: bool = False,
        prefer: str = "auto",
    ) -> Dict[int, Dict[str, Any]]:
        """Fetch weather for every (lat, lon) pair, per-cell cached.

        Returns {index: payload}. Cells the provider did not return stay absent;
        callers render them honestly as unavailable. `prefer="ecmwf"` tries the
        ECMWF provider first (weather-map default); "auto" keeps the historical
        Open-Meteo-first behaviour.
        """
        if not weather_platform.live_weather_enabled():
            return {}
        resolved_days = self._resolve_days(days)
        results: Dict[int, Dict[str, Any]] = {}
        misses: List[int] = []

        for idx, (lat, lon) in enumerate(points):
            cached = self._cache.get(_point_key(lat, lon, resolved_days))
            if cached is not None:
                results[idx] = self._serve_cached_point(cached)
            else:
                misses.append(idx)

        if misses:
            served = False
            provider_failures: list[str] = []
            chain: tuple[WeatherProvider, ...] = (
                (self._provider_primary, self._provider_backup)
                if prefer != "ecmwf"
                else (self._provider_backup, self._provider_primary)
            )
            for provider in chain:
                try:
                    raw = provider.fetch_many(points, misses, days=resolved_days, include_hourly=include_hourly)
                except HttpFetchError as exc:
                    provider_failures.append(str(exc))
                    continue
                for idx, item in raw.items():
                    if item is None:
                        continue
                    payload = self._build_payload(
                        points[idx][0],
                        points[idx][1],
                        item,
                        provider.name,
                        provider.role,
                        item.get("model") if isinstance(item, dict) else provider.model_hint,
                        resolved_days,
                        provider.dataset,
                    )
                    if provider.role == "backup":
                        payload["data_source"] = "ECMWF (Open-Meteo backup)"
                        payload["reason"] = (
                            "Open-Meteo primary unavailable — ECMWF backup serving."
                        )
                    results[idx] = payload
                    self._cache.set(_point_key(points[idx][0], points[idx][1], resolved_days), payload)
                served = True
                break
            if not served and provider_failures:
                raise HttpFetchError("; ".join(provider_failures))
        return results

    def get_grid_samples(
        self,
        north: float,
        south: float,
        east: float,
        west: float,
        step: float = 0.25,
        max_points: int = 600,
        variable: str = "temperature_2m",
        day: int = 0,
        hour: Optional[int] = None,
        days: Optional[int] = None,
        forecast_time: Optional[str] = None,
        prefer: str = "auto",
    ) -> Dict[str, Any]:
        resolved_days = self._resolve_days(days)
        if variable not in GRID_VARIABLES:
            raise ValueError(f"variable must be one of {GRID_VARIABLES}")
        if prefer not in ("auto", "ecmwf"):
            raise ValueError("prefer must be 'auto' or 'ecmwf'")
        resolved_hour = hour
        if forecast_time is not None and resolved_hour is None:
            resolved_hour = self._hour_offset_for(forecast_time)
        if resolved_hour is not None and not (0 <= int(resolved_hour) <= 47):
            raise ValueError("hour must be an offset from now in 0..47")

        if not weather_platform.live_weather_enabled():
            return self._empty_grid(
                variable,
                int(day),
                resolved_hour,
                self._actual_bounds(north, south, east, west),
                step,
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                (
                    "Live weather API not added. Set WEATHER_LIVE_ENABLED=on and "
                    "register a live provider in app/weather_platform.py to serve live "
                    "grid layers. Historical completed-month data is served by the "
                    "ERA5 archive provider."
                ),
                assumption="No live provider registered — grid not computed.",
                data_status="API_NOT_ADDED",
            )

        bounds_key = f"{round(north,3)}:{round(south,3)}:{round(east,3)}:{round(west,3)}"
        time_key = f"h{int(resolved_hour)}" if resolved_hour is not None else f"d{int(day)}"
        cache_key = f"weather-grid:p{prefer}:{bounds_key}:{round(step,4)}:{int(max_points)}:{variable}:{time_key}"
        cached = self._grid_cache.get(cache_key)
        if cached is not None:
            return self._serve_cached_grid(cached)

        # Single-flight: concurrent identical requests (e.g. the weather-map
        # temperature layer and its wind build at the same timestep) share one
        # provider fetch instead of duplicating upstream calls.
        slot, is_leader = _inflight_acquire(cache_key)
        if not is_leader:
            value = _inflight_wait(slot)
            if value is not None:
                return value

        value = None
        try:
            if resolved_hour is not None:
                value = self._grid_for_hour(
                    north, south, east, west, step, max_points, variable,
                    int(resolved_hour), resolved_days, prefer=prefer,
                )
            else:
                value = self._grid_for_day(
                    north, south, east, west, step, max_points, variable,
                    int(day), resolved_days, prefer=prefer,
                )
            return value
        finally:
            _inflight_done(cache_key, slot, value)

    def _hour_offset_for(self, forecast_time: str) -> int:
        """Resolve an ISO `forecast_time` to an hourly offset from "now" (0..47).

        Interpreted as an absolute UTC timestamp; the nearest whole-hour offset
        from the current UTC hour is used. Never rounds backwards beyond 0.
        """
        try:
            parsed = datetime.fromisoformat(str(forecast_time).replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("forecast_time must be an ISO 8601 timestamp (e.g. 2026-09-24T23:00:00Z)")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        diff_hours = int(round((parsed - datetime.now(timezone.utc)).total_seconds() / 3600.0))
        return max(0, min(47, diff_hours))

    def _empty_grid(
        self, variable: str, day: int, hour: Optional[int], actual_bounds: Dict[str, float],
        step: float, now: str, reason: str, assumption: Optional[str],
        data_status: str = "UNAVAILABLE",
    ) -> Dict[str, Any]:
        return {
            "data_status": data_status,
            "data_source": "Open-Meteo/ECMWF",
            "provider": None,
            "provider_role": None,
            "model": None,
            "variable": variable,
            "day": day,
            "hour": hour,
            "unit": _GRID_UNITS.get(variable),
            "bounds": actual_bounds,
            "steps": {"latitude": round(step, 5), "longitude": round(step, 5)},
            "resolution": {"latitude": round(step, 5), "longitude": round(step, 5)},
            "valid_time": None,
            "min": None,
            "max": None,
            "derived": variable in ("wind_u", "wind_v"),
            "points": [],
            "computed_at": now,
            "generated_at": now,
            "assumption": assumption,
            "reason": reason,
        }

    @staticmethod
    def _serve_cached_grid(cached: Dict[str, Any]) -> Dict[str, Any]:
        """A grid payload served from cache is never labelled LIVE/FORECAST —
        it is CACHED. Failure payloads stay UNAVAILABLE."""
        if not cached or not isinstance(cached, dict):
            return cached
        status = str(cached.get("data_status") or "")
        if status in ("LIVE", "FORECAST"):
            out = dict(cached)
            out["data_status"] = "CACHED"
            out["reason"] = (
                cached.get("reason")
                or "Served from the cached provider result (no new provider call)."
            )
            return out
        return cached

    @staticmethod
    def _serve_cached_point(cached: Dict[str, Any]) -> Dict[str, Any]:
        if not cached or not isinstance(cached, dict):
            return cached
        status = str(cached.get("data_status") or "")
        if status in ("LIVE", "FORECAST"):
            out = dict(cached)
            out["data_status"] = "CACHED"
            out["reason"] = (
                cached.get("reason")
                or "Served from the cached provider result (no new provider call)."
            )
            return out
        return cached

    @staticmethod
    def _grid_summary(points: List[Dict[str, Any]]) -> tuple[Optional[float], Optional[float]]:
        values = [float(v) for p in points for v in [p.get("value")] if v is not None]
        if not values:
            return None, None
        return (round(min(values), 5), round(max(values), 5))

    @staticmethod
    def _day_valid_time(payloads: Dict[int, Dict[str, Any]], day: int) -> Optional[str]:
        """Valid time for the day-mode grid: the current observation time for
        day 0, the daily forecast date for day >= 1. Real provider timestamps;
        None when the serving provider could not express the stop."""
        for pl in payloads.values():
            if day == 0:
                current = pl.get("current") or {}
                if current.get("time"):
                    return current["time"]
            else:
                forecast = pl.get("forecast") or []
                idx = int(day) - 1
                if 0 <= idx < len(forecast) and forecast[idx].get("date"):
                    return forecast[idx]["date"]
        return None

    @staticmethod
    def _hour_valid_time(raw_items: Dict[int, Dict[str, Any]], hour: int) -> Optional[str]:
        """Valid time for the hourly grid: the serving provider's hourly block
        timestamp at the requested offset. Real provider timestamp; None when the
        provider did not include a time axis."""
        for raw in raw_items.values():
            times = (raw.get("hourly") or {}).get("time") or []
            if 0 <= hour < len(times) and times[hour]:
                return times[hour]
        return None

    def _cell_points_from_payloads(
        self, cells: List[Dict[str, float]], payloads: Dict[int, Dict[str, Any]], variable: str, day: int
    ) -> tuple[set[str], int, List[Dict[str, Any]]]:
        provider_seen: set[str] = set()
        value_count = 0
        points: List[Dict[str, Any]] = []
        for idx, cell in enumerate(cells):
            pl = payloads.get(idx)
            if pl is None:
                points.append(
                    {
                        "latitude": cell["latitude"],
                        "longitude": cell["longitude"],
                        "value": None,
                        "data_status": "UNAVAILABLE",
                        "provider": None,
                        "provider_role": None,
                        "reason": "No usable provider response for this cell.",
                    }
                )
                continue
            provider_seen.add(pl.get("provider") or "")
            value = _extract_grid_value(pl, variable, day)
            if value is not None:
                value_count += 1
            cell_status = pl.get("data_status")
            if day > 0 and value is not None:
                cell_status = "FORECAST"
            points.append(
                {
                    "latitude": cell["latitude"],
                    "longitude": cell["longitude"],
                    "value": value,
                    "data_status": cell_status,
                    "provider": pl.get("provider"),
                    "provider_role": pl.get("provider_role"),
                    "reason": pl.get("reason"),
                }
            )
        return provider_seen, value_count, points

    def _grid_for_day(
        self, north: float, south: float, east: float, west: float, step: float,
        max_points: int, variable: str, day: int, resolved_days: int, prefer: str = "auto",
    ) -> Dict[str, Any]:
        bounds_key = f"{round(north,3)}:{round(south,3)}:{round(east,3)}:{round(west,3)}"
        cache_key = f"weather-grid:p{prefer}:{bounds_key}:{round(step,4)}:{int(max_points)}:{variable}:d{int(day)}"
        cached = self._grid_cache.get(cache_key)
        if cached is not None:
            return self._serve_cached_grid(cached)

        cells = self._make_grid(north, south, east, west, step, max_points)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        actual_bounds = self._actual_bounds(north, south, east, west)

        if not cells:
            payload = self._empty_grid(
                variable, day, None, actual_bounds, step, now,
                "Request bounds outside India (lat 6–37, lon 68–98) or empty grid.",
                "Requested bounds contain no India grid cells after India clamping.",
            )
            self._grid_cache.set(cache_key, payload, ttl_seconds=config.WEATHER_FAILURE_CACHE_TTL_SEC)
            return payload

        try:
            payloads = self.get_weather_batch(
                [(c["latitude"], c["longitude"]) for c in cells],
                days=resolved_days,
                include_hourly=False,
                prefer=prefer,
            )
        except HttpFetchError as exc:
            payload = self._empty_grid(
                variable, day, None, actual_bounds, step, now,
                f"Weather providers unreachable for these grid cells ({exc}).",
                None,
            )
            self._grid_cache.set(cache_key, payload, ttl_seconds=config.WEATHER_FAILURE_CACHE_TTL_SEC)
            return payload

        provider_seen, value_count, points = self._cell_points_from_payloads(
            cells, payloads, variable, day
        )

        gmin, gmax = self._grid_summary(points)
        valid_time = self._day_valid_time(payloads, day)

        if provider_seen:
            if "ECMWF" in provider_seen and "Open-Meteo" not in provider_seen:
                if prefer == "ecmwf":
                    data_source = "ECMWF IFS HRES 0.25° (via Open-Meteo)"
                    provider_role = "primary"
                else:
                    data_source = "ECMWF (Open-Meteo backup)"
                    provider_role = "backup"
            else:
                data_source = "Open-Meteo"
                provider_role = "primary"
            model = next(
                (pl.get("model") for pl in payloads.values() if pl.get("model")), None
            )
            status = "UNAVAILABLE"
            if value_count > 0:
                status = "LIVE" if day == 0 else "FORECAST"
            reason = None
            if not value_count:
                reason = (
                    "Variable not provided by the serving provider for the requested day. "
                    "ECMWF (backup) does not provide relative humidity or pressure."
                )
        else:
            data_source = "Open-Meteo/ECMWF"
            provider_role = None
            model = None
            status = "UNAVAILABLE"
            reason = "No weather data available for these grid cells."

        payload = {
            "data_status": status,
            "data_source": data_source,
            "provider": list(provider_seen)[0] if provider_seen else None,
            "provider_role": provider_role,
            "model": model,
            "variable": variable,
            "day": day,
            "hour": None,
            "unit": _GRID_UNITS.get(variable),
            "bounds": actual_bounds,
            "steps": {"latitude": round(step, 5), "longitude": round(step, 5)},
            "resolution": {"latitude": round(step, 5), "longitude": round(step, 5)},
            "valid_time": valid_time,
            "min": gmin,
            "max": gmax,
            "derived": variable in ("wind_u", "wind_v"),
            "points": points,
            "computed_at": now,
            "generated_at": now,
            "assumption": (
                "Values sampled per {:.2f}° grid cell from the serving provider; "
                "cells with no provider value are honestly reported as unavailable.".format(step)
            ),
            "reason": reason,
        }
        self._grid_cache.set(cache_key, payload)
        return payload

    def _grid_for_hour(
        self, north: float, south: float, east: float, west: float, step: float,
        max_points: int, variable: str, hour: int, resolved_days: int, prefer: str = "auto",
    ) -> Dict[str, Any]:
        """Intraday grid: reads the serving provider's hourly block at the
        requested hour offset from now (0..47). Forecast variables the provider
        does not have per-hour stay null on each cell — never fabricated.

        The raw hourly block is cached per (bounds, hour, days) so switching
        between grid variables at the same instant reuses the same upstream
        fetch — exactly as the day path reuses its per-point cache.
        """
        bounds_key = f"{round(north,3)}:{round(south,3)}:{round(east,3)}:{round(west,3)}"
        cache_key = f"weather-grid:p{prefer}:{bounds_key}:{round(step,4)}:{int(max_points)}:{variable}:h{int(hour)}"
        cached = self._grid_cache.get(cache_key)
        if cached is not None:
            return self._serve_cached_grid(cached)

        cells = self._make_grid(north, south, east, west, step, max_points)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        actual_bounds = self._actual_bounds(north, south, east, west)

        if not cells:
            payload = self._empty_grid(
                variable, 0, hour, actual_bounds, step, now,
                "Request bounds outside India (lat 6–37, lon 68–98) or empty grid.",
                "Requested bounds contain no India grid cells after India clamping.",
            )
            self._grid_cache.set(cache_key, payload, ttl_seconds=config.WEATHER_FAILURE_CACHE_TTL_SEC)
            return payload

        raw_key = f"weather-grid-hour:p{prefer}:{bounds_key}:{round(step,4)}:{int(max_points)}:{int(hour)}:{int(resolved_days)}"
        raw_block = self._grid_cache.get(raw_key)
        if raw_block is None:
            coords = [(c["latitude"], c["longitude"]) for c in cells]
            indices = list(range(len(cells)))
            raw_items: Dict[int, Dict[str, Any]] = {}
            provider_failures: list[str] = []
            served_name: Optional[str] = None
            served_role: Optional[str] = None

            chain: tuple[WeatherProvider, ...] = (
                (self._provider_primary, self._provider_backup)
                if prefer != "ecmwf"
                else (self._provider_backup, self._provider_primary)
            )
            for provider in chain:
                try:
                    fetched = provider.fetch_many(
                        coords, indices, days=resolved_days, include_hourly=True
                    )
                except HttpFetchError as exc:
                    provider_failures.append(str(exc))
                    continue
                served_name = provider.name
                served_role = provider.role
                raw_items = {i: item for i, item in fetched.items() if item is not None}
                break

            raw_block = {
                "provider": served_name,
                "role": served_role,
                "items": raw_items,
                "error": "; ".join(provider_failures) if served_name is None else None,
            }
            # Cache even empty/failed blocks so repeated variable switches at the
            # same instant never hammer the provider. Failures expire fast so a
            # recovering provider is retried without waiting out the 10-min TTL.
            raw_ttl = (
                config.WEATHER_FAILURE_CACHE_TTL_SEC if served_name is None else None
            )
            self._grid_cache.set(raw_key, raw_block, ttl_seconds=raw_ttl)

        served_name = raw_block.get("provider")
        served_role = raw_block.get("role")
        raw_items = raw_block.get("items") or {}

        if served_name is None:
            payload = self._empty_grid(
                variable, 0, hour, actual_bounds, step, now,
                f"Weather providers unreachable for these grid cells ({raw_block.get('error')}).",
                None,
            )
            self._grid_cache.set(cache_key, payload, ttl_seconds=config.WEATHER_FAILURE_CACHE_TTL_SEC)
            return payload

        value_count = 0
        points: List[Dict[str, Any]] = []
        for idx, cell in enumerate(cells):
            raw = raw_items.get(idx)
            if raw is None:
                points.append(
                    {
                        "latitude": cell["latitude"],
                        "longitude": cell["longitude"],
                        "value": None,
                        "data_status": "UNAVAILABLE",
                        "provider": served_name,
                        "provider_role": served_role,
                        "reason": "No usable provider response for this cell.",
                    }
                )
                continue
            value = _extract_hourly_value(raw, variable, hour)
            if value is not None:
                value_count += 1
            points.append(
                {
                    "latitude": cell["latitude"],
                    "longitude": cell["longitude"],
                    "value": value,
                    "data_status": "LIVE" if value is not None else "UNAVAILABLE",
                    "provider": served_name,
                    "provider_role": served_role,
                    "reason": None,
                }
            )

        status = "UNAVAILABLE"
        if value_count > 0:
            status = "LIVE" if hour == 0 else "FORECAST"
        reason = None
        if not value_count:
            reason = (
                "Variable not provided per-hour by the serving provider at this offset. "
                "relative_humidity, pressure, apparent_temperature and visibility are "
                "current-conditions only."
            )

        gmin, gmax = self._grid_summary(points)
        valid_time = self._hour_valid_time(raw_items, hour)

        if served_role == "primary":
            data_source = "Open-Meteo"
            provider_role = "primary"
        elif prefer == "ecmwf":
            data_source = "ECMWF IFS HRES 0.25° (via Open-Meteo)"
            provider_role = "primary"
        else:
            data_source = "ECMWF (Open-Meteo backup)"
            provider_role = "backup"

        payload = {
            "data_status": status,
            "data_source": data_source,
            "provider": served_name,
            "provider_role": provider_role,
            "model": None,
            "variable": variable,
            "day": 0,
            "hour": hour,
            "unit": _GRID_UNITS.get(variable),
            "bounds": actual_bounds,
            "steps": {"latitude": round(step, 5), "longitude": round(step, 5)},
            "resolution": {"latitude": round(step, 5), "longitude": round(step, 5)},
            "valid_time": valid_time,
            "min": gmin,
            "max": gmax,
            "derived": variable in ("wind_u", "wind_v"),
            "points": points,
            "computed_at": now,
            "generated_at": now,
            "assumption": (
                "Values sampled per {:.2f}° grid cell from the serving provider's hourly "
                "block at +{:.0f}h; cells without an hourly value are honestly unavailable.".format(step, float(hour))
            ),
            "reason": reason,
        }
        self._grid_cache.set(cache_key, payload)
        return payload

    def _make_grid(
        self, north: float, south: float, east: float, west: float, step: float,
        max_points: int
    ) -> List[Dict[str, float]]:
        n = min(float(north), 37.4)
        s = max(float(south), 6.0)
        e = min(float(east), 98.5)
        w = max(float(west), 68.0)
        if n <= s or e <= w or step <= 0:
            return []
        rows = int((n - s) / step) + 1
        cols = int((e - w) / step) + 1
        if rows <= 0 or cols <= 0:
            return []
        # Sub-sample EVENLY across both dimensions when the full grid exceeds the
        # point budget, so a nationwide view stays representative instead of being
        # truncated to only the northern rows of the requested viewport. The
        # fringe rows/columns are always kept so the returned grid still spans the
        # exact requested bounds' computed extent.
        kept_rows, kept_cols = rows, cols
        if rows * cols > max_points:
            for stride_row in range(1, rows + 1):
                kept_rows = int(math.ceil(rows / stride_row))
                stride_col = max(1, int(math.ceil(kept_rows * cols / float(max_points))))
                kept_cols = int(math.ceil(cols / stride_col))
                if kept_rows * kept_cols <= max_points:
                    break
        row_index = sorted({round(int((rows - 1) * i / max(1, kept_rows - 1))) for i in range(kept_rows)})
        col_index = sorted({round(int((cols - 1) * i / max(1, kept_cols - 1))) for i in range(kept_cols)})
        cells: List[Dict[str, float]] = []
        for _r in row_index:
            lat = float(n) - _r * step
            for _c in col_index:
                lng = min(float(w) + _c * step, e)
                cells.append({"latitude": round(lat, 5), "longitude": round(lng, 5)})
        return cells

    def _actual_bounds(self, north: float, south: float, east: float, west: float) -> Dict[str, float]:
        return {
            "north": min(float(north), 37.4),
            "south": max(float(south), 6.0),
            "east": min(float(east), 98.5),
            "west": max(float(west), 68.0),
        }

    def status(self) -> Dict[str, str]:
        """Provider availability for the data-status dashboard."""
        return {
            "weather_status": self._provider_primary.status(),
            "weather_source": "Open-Meteo (primary, keyless) + ECMWF backup",
            "imd_status": self._provider_imd.status(),
        }


_GRID_UNITS: Dict[str, Optional[str]] = {
    "temperature_2m": "°C",
    "precipitation": "mm",
    "precipitation_probability": "%",
    "wind_speed_10m": "km/h",
    "wind_gusts_10m": "km/h",
    "cloud_cover": "%",
    "precipitation_accumulation": "mm",
    "storm_indicator": "index",
    "relative_humidity": "%",
    "pressure_msl": "hPa",
    "wind_direction_10m": "°",
    "wind_u": "m/s",
    "wind_v": "m/s",
    "apparent_temperature": "°C",
    "visibility": "km",
}


def _extract_grid_value(payload: Dict[str, Any], variable: str, day: int) -> Optional[float]:
    """Pull the value for `variable` from a per-cell weather payload.

    day == 0 reads the current block (live "now"); day >= 1 reads the forecast
    week. Variables the serving provider does not produce, or days it cannot
    express, return None and the caller reports the cell honestly as
    "no data" rather than inventing a value.
    """
    current = payload.get("current") or {}
    forecast = payload.get("forecast") or []

    def _at(idx: int, key: str) -> Optional[float]:
        if 0 <= idx < len(forecast) and forecast[idx].get(key) is not None:
            return forecast[idx][key]
        return None

    if variable == "temperature_2m":
        return current.get("temperature_c") if day == 0 else _at(day - 1, "max_temp_c")
    if variable == "precipitation":
        return current.get("precipitation_mm") if day == 0 else _at(day - 1, "precipitation_mm")
    if variable == "precipitation_probability":
        if day == 0:
            return _at(0, "precipitation_probability_percent")
        return _at(day - 1, "precipitation_probability_percent")
    if variable == "wind_speed_10m":
        return current.get("wind_speed_kmh") if day == 0 else _at(day - 1, "wind_speed_kmh")
    if variable == "wind_gusts_10m":
        return current.get("wind_gusts_kmh") if day == 0 else None
    if variable == "cloud_cover":
        return current.get("cloud_cover_percent") if day == 0 else None
    if variable == "precipitation_accumulation":
        return _at(day, "precipitation_mm") if day == 0 else _at(day - 1, "precipitation_mm")
    if variable == "storm_indicator":
        code = current.get("weather_code") if day == 0 else _at(day - 1, "weather_code")
        if code is None:
            return None
        return 2 if code in (96, 99) else (1 if code >= 95 else 0)
    if variable == "relative_humidity":
        return current.get("relative_humidity_percent") if day == 0 else None
    if variable == "pressure_msl":
        return current.get("pressure_hpa") if day == 0 else None
    if variable == "wind_direction_10m":
        return current.get("wind_direction_deg") if day == 0 else None
    if variable in ("wind_u", "wind_v"):
        if day != 0:
            return None
        speed_kmh = current.get("wind_speed_kmh")
        direction = current.get("wind_direction_deg")
        if speed_kmh is None or direction is None:
            return None
        return _wind_component(variable, speed_kmh, direction)
    if variable == "apparent_temperature":
        return current.get("apparent_temperature_c") if day == 0 else None
    if variable == "visibility":
        return current.get("visibility_km") if day == 0 else None
    return None


def _extract_hourly_value(raw: Dict[str, Any], variable: str, hour: int) -> Optional[float]:
    """Extract `variable` at a +`hour` offset from the serving provider's raw
    hourly block. offset 0 == the current hour (Open-Meteo hourly starts now).

    No value is invented: variables without an hourly entry (e.g. relative
    humidity / pressure for the ECMWF backup) or offsets past the hourly horizon
    come back None and the cell is labelled unavailable.
    """
    hourly = raw.get("hourly") or {}

    def _pick(key: str) -> Optional[float]:
        arr = hourly.get(key) or []
        if 0 <= hour < len(arr):
            return arr[hour]
        return None

    if variable == "storm_indicator":
        code = _pick("weather_code")
        if code is None:
            return None
        return 2 if code in (96, 99) else (1 if code >= 95 else 0)
    if variable == "precipitation_accumulation":
        return _pick("precipitation")
    if variable == "wind_direction_10m":
        return _pick("wind_direction_10m")
    if variable in ("wind_u", "wind_v"):
        speed = _pick("wind_speed_10m")
        direction = _pick("wind_direction_10m")
        if speed is None or direction is None:
            return None
        return _wind_component(variable, speed, direction)
    if variable in (
        "temperature_2m",
        "precipitation",
        "precipitation_probability",
        "wind_speed_10m",
        "wind_gusts_10m",
        "cloud_cover",
    ):
        return _pick(variable)
    return None


def _raw_day_value(raw: Dict[str, Any], variable: str, day: int) -> Optional[float]:
    """Extract `variable` for the raw (un-built) provider payload in day mode."""
    current = raw.get("current") or {}
    daily = raw.get("daily") or {}

    def _at(idx: int, key: str) -> Optional[float]:
        arr = daily.get(key) or []
        if 0 <= idx < len(arr) and arr[idx] is not None:
            try:
                return float(arr[idx])
            except (TypeError, ValueError):
                return None
        return None

    if variable == "wind_u" or variable == "wind_v":
        speed = current.get("wind_speed_10m")
        direction = current.get("wind_direction_10m")
        if day != 0 or speed is None or direction is None:
            return None
        return _wind_component(variable, speed, direction)

    if day == 0:
        if variable == "temperature_2m":
            return _as_float(current.get("temperature_2m"))
        if variable == "precipitation":
            return _as_float(current.get("precipitation"))
        if variable == "precipitation_probability":
            return _at(0, "precipitation_probability_max")
        if variable == "wind_speed_10m":
            return _as_float(current.get("wind_speed_10m"))
        if variable == "wind_gusts_10m":
            return _as_float(current.get("wind_gusts_10m"))
        if variable == "cloud_cover":
            return _as_float(current.get("cloud_cover"))
        if variable == "precipitation_accumulation":
            return _as_float(current.get("precipitation"))
        if variable == "storm_indicator":
            code = _as_float(current.get("weather_code"))
            if code is None:
                return None
            return 2 if code in (96, 99) else (1 if code >= 95 else 0)
        if variable == "relative_humidity":
            return _as_float(current.get("relative_humidity_2m"))
        if variable == "pressure_msl":
            return _as_float(current.get("pressure_msl") or current.get("surface_pressure"))
        if variable == "wind_direction_10m":
            return _as_float(current.get("wind_direction_10m"))
        if variable == "apparent_temperature":
            return _as_float(current.get("apparent_temperature"))
        if variable == "visibility":
            return _as_float(current.get("visibility"))
        return None

    idx = int(day) - 1
    if variable == "temperature_2m":
        return _at(idx, "temperature_2m_max")
    if variable == "precipitation" or variable == "precipitation_accumulation":
        return _at(idx, "precipitation_sum")
    if variable == "precipitation_probability":
        return _at(idx, "precipitation_probability_max")
    if variable == "wind_speed_10m":
        return _at(idx, "wind_speed_10m_max")
    if variable == "storm_indicator":
        code = _at(idx, "weather_code")
        if code is None:
            return None
        return 2 if code in (96, 99) else (1 if code >= 95 else 0)
    return None


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _provider_grid_cells(
    north: float, south: float, east: float, west: float, step: float, max_points: int
) -> List[Dict[str, float]]:
    n = min(float(north), 37.4)
    s = max(float(south), 6.0)
    e = min(float(east), 98.5)
    w = max(float(west), 68.0)
    if n <= s or e <= w or step <= 0:
        return []
    rows = int((n - s) / step) + 1
    cols = int((e - w) / step) + 1
    if rows <= 0 or cols <= 0:
        return []
    kept_rows, kept_cols = rows, cols
    if rows * cols > max_points:
        for stride_row in range(1, rows + 1):
            kept_rows = int(math.ceil(rows / stride_row))
            stride_col = max(1, int(math.ceil(kept_rows * cols / float(max_points))))
            kept_cols = int(math.ceil(cols / stride_col))
            if kept_rows * kept_cols <= max_points:
                break
    row_index = sorted({round(int((rows - 1) * i / max(1, kept_rows - 1))) for i in range(kept_rows)})
    col_index = sorted({round(int((cols - 1) * i / max(1, kept_cols - 1))) for i in range(kept_cols)})
    cells: List[Dict[str, float]] = []
    for _r in row_index:
        lat = float(n) - _r * step
        for _c in col_index:
            lng = min(float(w) + _c * step, e)
            cells.append({"latitude": round(lat, 5), "longitude": round(lng, 5)})
    return cells


def _actual_bounds_cells(north: float, south: float, east: float, west: float) -> Dict[str, float]:
    return {
        "north": min(float(north), 37.4),
        "south": max(float(south), 6.0),
        "east": min(float(east), 98.5),
        "west": max(float(west), 68.0),
    }


def _day_cell_points(
    cells: List[Dict[str, float]],
    raw_items: Dict[int, Dict[str, Any]],
    variable: str,
    day: int,
) -> List[Dict[str, Any]]:
    provider_seen: set[str] = set()
    points: List[Dict[str, Any]] = []
    for idx, cell in enumerate(cells):
        raw = raw_items.get(idx)
        if raw is None:
            points.append(
                {
                    "latitude": cell["latitude"],
                    "longitude": cell["longitude"],
                    "value": None,
                    "data_status": "UNAVAILABLE",
                    "provider": None,
                    "provider_role": None,
                    "reason": "No usable provider response for this cell.",
                }
            )
            continue
        provider_seen.add(str(raw.get("model") or raw.get("timezone")))
        points.append(
            {
                "latitude": cell["latitude"],
                "longitude": cell["longitude"],
                "value": _raw_day_value(raw, variable, day),
                "data_status": "LIVE",
                "provider": None,
                "provider_role": None,
                "reason": None,
            }
        )
    return points


def _hour_cell_points(
    cells: List[Dict[str, float]],
    raw_items: Dict[int, Dict[str, Any]],
    variable: str,
    hour: int,
) -> List[Dict[str, Any]]:
    points: List[Dict[str, Any]] = []
    for idx, cell in enumerate(cells):
        raw = raw_items.get(idx)
        if raw is None:
            points.append(
                {
                    "latitude": cell["latitude"],
                    "longitude": cell["longitude"],
                    "value": None,
                    "data_status": "UNAVAILABLE",
                    "provider": None,
                    "provider_role": None,
                    "reason": "No usable provider response for this cell.",
                }
            )
            continue
        value = _extract_hourly_value(raw, variable, hour)
        points.append(
            {
                "latitude": cell["latitude"],
                "longitude": cell["longitude"],
                "value": value,
                "data_status": "LIVE" if value is not None else "UNAVAILABLE",
                "provider": None,
                "provider_role": None,
                "reason": None,
            }
        )
    return points


weather_service = WeatherService()