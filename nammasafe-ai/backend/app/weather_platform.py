"""Weather provider registry — the single switchboard for weather data sources.

Design (per the Change-3 spec):
  * A fresh deployment ships with the *live* weather chain DISABLED. The weather
    map therefore reports `API NOT ADDED` for live views until an operator sets
    `WEATHER_LIVE_ENABLED=on` and adds the provider credentials. We never fake a
    live reading to paper over a missing provider.
  * The *historical* ERA5 archive provider is enabled by default and needs no
    key, so completed-month historical weather works out of the box.

Every entry uses the schema requested by the operator: {name, kind, endpoint,
api_key, enabled, coverage, adapter, update_interval_sec, auth}. The registry is
config-driven (env-seeded) so a future live provider is a config flip — no UI
redesign.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app import config

# Kind constants kept as module literals to avoid string drift.
KIND_LIVE = "live"
KIND_HISTORICAL = "historical"


def _live_enabled_flag() -> bool:
    """True when the operator has explicitly opted in to live weather calls."""
    return config.WEATHER_LIVE_ENABLED


def registered_providers() -> List[Dict[str, Any]]:
    """The full provider registry (config-driven, factual — no secrets leaked)."""
    return [
        {
            "name": "Open-Meteo (ECMWF HRES / GFS)",
            "kind": KIND_LIVE,
            "endpoint": config.OPEN_METEO_BASE_URL,
            "api_key": "",  # upstream requires no key
            "enabled": _live_enabled_flag(),
            "coverage": "India (global numerical weather prediction, hourly up to 7 d)",
            "adapter": "openmeteo_forecast",
            "update_interval_sec": config.WEATHER_CACHE_TTL_SEC,
            "auth": {"type": "none"},
        },
        {
            "name": "ECMWF via Open-Meteo (IFS 0.25) — backup",
            "kind": KIND_LIVE,
            "endpoint": config.ECMWF_BASE_URL,
            "api_key": "",
            "enabled": _live_enabled_flag(),
            "coverage": "India (ECMWF IFS HRES 0.25, hourly up to 7 d)",
            "adapter": "openmeteo_forecast_ecmwf",
            "update_interval_sec": config.WEATHER_CACHE_TTL_SEC,
            "auth": {"type": "none"},
        },
        {
            "name": "IMD Mausam Current Weather (optional)",
            "kind": KIND_LIVE,
            "endpoint": config.IMD_MAUSAM_BASE_URL,
            "api_key": config.IMD_MAUSAM_TOKEN,
            "enabled": bool(config.IMD_MAUSAM_BASE_URL and config.IMD_MAUSAM_TOKEN),
            "coverage": "India (IMD current observations)",
            "adapter": "imd_mausam",
            "update_interval_sec": config.WEATHER_CACHE_TTL_SEC,
            "auth": {"type": "token", "in": "query"},
        },
        {
            "name": "Open-Meteo ERA5 Archive (ECMWF reanalysis)",
            "kind": KIND_HISTORICAL,
            "endpoint": config.HISTORICAL_WEATHER_BASE_URL,
            "api_key": "",  # archive API requires no key
            "enabled": True,
            "coverage": "India (ERA5 reanalysis 0.25 hourly, 1940–2025; daily aggregations 2022–2026)",
            "adapter": "openmeteo_era5_archive",
            # The archive is static reanalysis — no upstream refresh cadence.
            "update_interval_sec": 0,
            "auth": {"type": "none"},
        },
    ]


def live_weather_enabled() -> bool:
    """Short-circuits every live-weather entry point before any network I/O."""
    return _live_enabled_flag()


def historical_provider() -> Dict[str, Any]:
    """The enabled historical provider entry (default: ERA5 archive)."""
    return next(
        (p for p in registered_providers() if p["kind"] == KIND_HISTORICAL and p["enabled"]),
        {
            "name": "None configured",
            "kind": KIND_HISTORICAL,
            "enabled": False,
            "coverage": "n/a",
            "adapter": None,
        },
    )


def live_providers() -> List[Dict[str, Any]]:
    return [p for p in registered_providers() if p["kind"] == KIND_LIVE and p["enabled"]]


def weather_api_status(role: str = "") -> str:
    """Machine-readable status used by the UI ribbon and honest UNAVAILABLE paths.

    Every role holds the read-only Historical Weather Map permission
    (weather.history.read); live weather stays optional and disabled by default.

    Returns one of:
      * "API_NOT_ADDED" — live weather requested but no live provider enabled
      * "LIVE"          — live provider enabled
      * "UNAVAILABLE"   — providers exist but recently failed (resolver decides)
    """
    _ = role
    if not live_weather_enabled():
        return "API_NOT_ADDED"
    return "LIVE"