"""Official historical-data providers — India-WRIS, IMD and KSDMA.

This module is the single source of truth for *what the Historical Data panel
claims about each provider*. Two rules drive the whole design:

1. **Never fabricate.** A provider is only ever reported ``LIVE``/``HISTORICAL``
   after a real upstream call actually succeeded. Everything else is reported as
   ``NOT_CONFIGURED`` (no credential), ``UNAVAILABLE`` (no usable official
   source) or ``ERROR`` (the call was attempted and failed).
2. **Never raise into the status path.** These functions back a dashboard, so a
   dead upstream must degrade to an honest status row, never a 500.

The provider clients are real and functional: they light up the moment an
operator supplies credentials or an upstream service recovers, with no code
change. Today only ERA5 (keyless, in ``app/weather_platform.py``) serves data.

Upstream references
-------------------
* IMD  — https://api.imd.gov.in/public/api_reference.html (Ministry of Earth
  Sciences). API key required; the transport carrying the key is published only
  behind an account login, hence ``IMD_API_KEY_IN``/``_HEADER``/``_PARAM``.
* India-WRIS — https://arc.indiawris.gov.in/server/rest/services (Central Water
  Commission / Ministry of Jal Shakti) ArcGIS REST services.
* KSDMA — https://sdma.kerala.gov.in. Publishes HTML/PDF bulletins and
  social/app pushes; documents no machine-readable API, so there is nothing to
  integrate and the status stays ``UNAVAILABLE`` rather than faked.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional

from app import config
from app.cache import TTLCache
from app.http_client import HttpFetchError, http_get

# Status vocabulary shared with the frontend ``DataLayerStatus`` union.
STATUS_LIVE = "LIVE"
STATUS_HISTORICAL = "HISTORICAL"
STATUS_CACHED = "CACHED"
STATUS_NOT_CONFIGURED = "NOT_CONFIGURED"
STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_ERROR = "ERROR"

# Provider identifiers — also the ``provider`` value surfaced to the UI.
PROVIDER_ERA5 = "era5"
PROVIDER_IMD = "imd"
PROVIDER_INDIAWRIS = "indiawris"
PROVIDER_KSDMA = "ksdma"

# Smallest documented IMD endpoint used purely to prove reachability + auth.
# Operator-overridable so the probe can target whichever feed they actually use.
IMD_STATUS_PATH_DEFAULT = "/districtwarning"

# India-WRIS service probed to prove the official catalogue serves *data* (not
# just a directory listing). Rainfall stations are the relevant layer for this
# platform; override if an operator prefers a different official service.
INDIAWRIS_PROBE_SERVICE_DEFAULT = "NWIC/rf_station:MapServer"

# Probe results are cached briefly so the dashboard does not hammer a government
# host on every page load; failures expire faster so recovery is prompt.
_PROBE_CACHE = TTLCache(
    default_ttl_seconds=config.HISTORICAL_PROVIDER_CACHE_TTL_SEC,
    max_entries=128,
)
_PROBE_LOCK = threading.Lock()


@dataclass
class ProviderStatus:
    """Honest, uniform status for one upstream provider."""

    provider: str
    status: str
    source: str
    available: bool = False
    cached: bool = False
    last_updated: Optional[str] = None
    period: Optional[str] = None
    error: Optional[str] = None
    coverage: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "status": self.status,
            "source": self.source,
            "available": self.available,
            "cached": self.cached,
            "last_updated": self.last_updated,
            "period": self.period,
            "error": self.error,
            "coverage": self.coverage,
        }


@dataclass
class _Probe:
    """Internal result of a probe, carrying whether the TTL cache served it."""

    status: ProviderStatus
    from_cache: bool = field(default=False)


# ---------------------------------------------------------------------------
# ERA5 (existing, keyless) — preserved exactly as shipped
# ---------------------------------------------------------------------------

def era5_status() -> ProviderStatus:
    """ERA5 reanalysis via the existing provider registry.

    Deliberately makes **no network call**: the registry already reports the
    archive as enabled and keyless, so a probe here would only add load.
    """
    from app.weather_platform import historical_provider

    entry = historical_provider()
    if not entry.get("enabled"):
        return ProviderStatus(
            provider=PROVIDER_ERA5,
            status=STATUS_UNAVAILABLE,
            source="Open-Meteo ERA5 Archive (ECMWF reanalysis)",
            error="No enabled historical weather provider is registered.",
            coverage="India (ERA5 reanalysis 0.25 hourly)",
        )
    return ProviderStatus(
        provider=PROVIDER_ERA5,
        status=STATUS_HISTORICAL,
        # The registry name already carries "(ECMWF reanalysis)"; do not repeat it.
        source=entry.get("name") or "Open-Meteo ERA5 Archive (ECMWF reanalysis)",
        available=True,
        coverage=entry.get("coverage") or "India (ERA5 reanalysis 0.25 hourly)",
        period="Completed months only (reanalysis is immutable once published)",
    )


# ---------------------------------------------------------------------------
# IMD — official API Management platform
# ---------------------------------------------------------------------------

def _imd_auth() -> tuple[Dict[str, str], Dict[str, Any]]:
    """Split the configured credential into (extra headers, extra params).

    IMD publishes the key's transport only behind an account login, so both
    shapes are supported and selected by config rather than guessed.
    """
    key = (config.IMD_API_KEY or "").strip()
    if not key:
        return {}, {}
    if (config.IMD_API_KEY_IN or "header").strip().lower() == "query":
        return {}, {config.IMD_API_KEY_PARAM or "api_key": key}
    return {config.IMD_API_KEY_HEADER or "api-key": key}, {}


def _imd_status_path() -> str:
    return config.IMD_STATUS_PATH or IMD_STATUS_PATH_DEFAULT


def imd_request(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """GET a documented IMD endpoint with the configured credential.

    Returns the decoded JSON payload. Raises ``HttpFetchError`` on transport
    failure, non-2xx, or a non-JSON body — callers decide how to surface that.
    """
    headers, auth_params = _imd_auth()
    query = dict(params or {})
    query.update(auth_params)
    url = f"{(config.IMD_API_BASE_URL or '').rstrip('/')}/{path.lstrip('/')}"
    response = http_get(
        url,
        params=query or None,
        timeout=config.IMD_TIMEOUT_SEC,
        headers=headers or None,
        max_retries=config.HISTORICAL_PROVIDER_MAX_RETRIES,
    )
    if response.status_code >= 400:
        raise HttpFetchError(f"IMD rejected the request (HTTP {response.status_code})")
    return response.json()


def _imd_probe() -> ProviderStatus:
    base = (config.IMD_API_BASE_URL or "").rstrip("/")
    if not (config.IMD_API_KEY or "").strip():
        return ProviderStatus(
            provider=PROVIDER_IMD,
            status=STATUS_NOT_CONFIGURED,
            source="IMD official API (api.imd.gov.in)",
            error="IMD_API_KEY is not set. Register at api.imd.gov.in to obtain a key.",
            coverage="India (IMD observations, rainfall, forecasts and warnings)",
        )
    if not base:
        return ProviderStatus(
            provider=PROVIDER_IMD,
            status=STATUS_NOT_CONFIGURED,
            source="IMD official API (api.imd.gov.in)",
            error="IMD_API_BASE_URL is not set.",
            coverage="India (IMD observations, rainfall, forecasts and warnings)",
        )

    headers, auth_params = _imd_auth()
    url = f"{base}/{_imd_status_path().lstrip('/')}"
    try:
        response = http_get(
            url,
            params=auth_params or None,
            timeout=config.IMD_TIMEOUT_SEC,
            headers=headers or None,
            max_retries=config.HISTORICAL_PROVIDER_MAX_RETRIES,
        )
    except HttpFetchError as exc:
        return ProviderStatus(
            provider=PROVIDER_IMD,
            status=STATUS_ERROR,
            source="IMD official API (api.imd.gov.in)",
            error=f"IMD is unreachable: {exc}",
            coverage="India (IMD observations, rainfall, forecasts and warnings)",
        )

    if response.status_code in (401, 403):
        return ProviderStatus(
            provider=PROVIDER_IMD,
            status=STATUS_ERROR,
            source="IMD official API (api.imd.gov.in)",
            error=(
                f"IMD rejected the configured credential (HTTP {response.status_code}). "
                "Check IMD_API_KEY and the IMD_API_KEY_IN/IMD_API_KEY_HEADER settings."
            ),
            coverage="India (IMD observations, rainfall, forecasts and warnings)",
        )
    if response.status_code == 429:
        return ProviderStatus(
            provider=PROVIDER_IMD,
            status=STATUS_ERROR,
            source="IMD official API (api.imd.gov.in)",
            error="IMD rate-limited the probe (HTTP 429). Retrying later.",
            coverage="India (IMD observations, rainfall, forecasts and warnings)",
        )
    if response.status_code >= 400:
        return ProviderStatus(
            provider=PROVIDER_IMD,
            status=STATUS_ERROR,
            source="IMD official API (api.imd.gov.in)",
            error=f"IMD returned HTTP {response.status_code} for {_imd_status_path()}.",
            coverage="India (IMD observations, rainfall, forecasts and warnings)",
        )

    return ProviderStatus(
        provider=PROVIDER_IMD,
        status=STATUS_LIVE,
        source="IMD official API (api.imd.gov.in)",
        available=True,
        coverage="India (IMD observations, rainfall, forecasts and warnings)",
        period="Near-real-time observations and forecasts as published by IMD",
    )


def fetch_imd_district_rainfall(district_id: Optional[str] = None) -> Any:
    """District-wise rainfall (documented endpoint ``/districtrainfall``)."""
    params = {"id": str(district_id)} if district_id else None
    return imd_request("/districtrainfall", params)


def fetch_imd_current_wx(station_id: Optional[str] = None) -> Any:
    """Current weather observations (documented endpoint ``/current_wx``)."""
    params = {"id": str(station_id)} if station_id else None
    return imd_request("/current_wx", params)


def fetch_imd_district_warning(district_id: Optional[str] = None) -> Any:
    """District-wise warnings (documented endpoint ``/districtwarning``)."""
    params = {"id": str(district_id)} if district_id else None
    return imd_request("/districtwarning", params)


# ---------------------------------------------------------------------------
# India-WRIS — official ArcGIS REST services
# ---------------------------------------------------------------------------

def _indiawris_probe_service() -> str:
    return config.INDIAWRIS_PROBE_SERVICE or INDIAWRIS_PROBE_SERVICE_DEFAULT


def indiawris_query(
    service: str,
    layer_id: int = 0,
    where: str = "1=1",
    out_fields: str = "*",
    *,
    result_record_count: int = 100,
    geometry: Optional[Dict[str, Any]] = None,
    geometry_type: Optional[str] = None,
    spatial_rel: str = "esriSpatialRelIntersects",
    time: Optional[str] = None,
) -> Any:
    """Query an official India-WRIS ArcGIS layer.

    Only endpoints advertised by the official catalogue are reachable; no
    scraping, and no invented paths. Raises ``HttpFetchError`` on failure.
    """
    base = (config.INDIAWRIS_ARCGIS_BASE_URL or "").rstrip("/")
    params: Dict[str, Any] = {
        "where": where,
        "outFields": out_fields,
        "f": "json",
        "returnGeometry": "false",
        "resultRecordCount": int(result_record_count),
    }
    if geometry is not None:
        params["geometry"] = geometry
        params["geometryType"] = geometry_type or "esriGeometryEnvelope"
        params["spatialRel"] = spatial_rel
        if time:
            params["time"] = time
    url = f"{base}/{service}/{int(layer_id)}/query"
    response = http_get(
        url,
        params=params,
        timeout=config.INDIAWRIS_TIMEOUT_SEC,
        max_retries=config.HISTORICAL_PROVIDER_MAX_RETRIES,
    )
    if response.status_code >= 400:
        raise HttpFetchError(f"India-WRIS rejected the request (HTTP {response.status_code})")
    return response.json()


def _indiawris_catalogue_reachable() -> Optional[bool]:
    """True/False when the catalogue answered, None when the host is unreachable."""
    base = (config.INDIAWRIS_ARCGIS_BASE_URL or "").rstrip("/")
    try:
        response = http_get(
            f"{base}/",
            params={"f": "json"},
            timeout=config.INDIAWRIS_TIMEOUT_SEC,
            max_retries=0,
        )
    except HttpFetchError:
        return None
    return response.status_code < 400


def _indiawris_probe() -> ProviderStatus:
    source = "India-WRIS / National Water Data Portal (ArcGIS REST)"
    coverage = "India (rainfall, rivers, reservoirs, groundwater, flood)"

    if not config.INDIAWRIS_ENABLED:
        return ProviderStatus(
            provider=PROVIDER_INDIAWRIS,
            status=STATUS_NOT_CONFIGURED,
            source=source,
            error="India-WRIS integration is disabled (INDIAWRIS_ENABLED=off).",
            coverage=coverage,
        )

    base = (config.INDIAWRIS_ARCGIS_BASE_URL or "").rstrip("/")
    if not base:
        return ProviderStatus(
            provider=PROVIDER_INDIAWRIS,
            status=STATUS_NOT_CONFIGURED,
            source=source,
            error="INDIAWRIS_ARCGIS_BASE_URL is not set.",
            coverage=coverage,
        )

    service = _indiawris_probe_service()
    try:
        response = http_get(
            f"{base}/{service}",
            params={"f": "json"},
            timeout=config.INDIAWRIS_TIMEOUT_SEC,
            max_retries=config.HISTORICAL_PROVIDER_MAX_RETRIES,
        )
    except HttpFetchError as exc:
        catalogue = _indiawris_catalogue_reachable()
        detail = (
            "official services host is unreachable"
            if catalogue is None
            else "official services are listed in the catalogue but the host refused the connection"
        )
        return ProviderStatus(
            provider=PROVIDER_INDIAWRIS,
            status=STATUS_ERROR,
            source=source,
            error=f"India-WRIS {detail}: {exc}",
            coverage=coverage,
        )

    if response.status_code >= 400:
        catalogue = _indiawris_catalogue_reachable()
        detail = (
            "the official ArcGIS host is unreachable"
            if catalogue is False
            else "the official catalogue lists the service but its endpoint is not serving data"
        )
        return ProviderStatus(
            provider=PROVIDER_INDIAWRIS,
            status=STATUS_ERROR,
            source=source,
            error=(
                f"India-WRIS {detail} (HTTP {response.status_code} for {service}). "
                "No fallback or synthetic data is substituted."
            ),
            coverage=coverage,
        )

    return ProviderStatus(
        provider=PROVIDER_INDIAWRIS,
        status=STATUS_LIVE,
        source=source,
        available=True,
        coverage=coverage,
        period="As published by the official India-WRIS services",
    )


# ---------------------------------------------------------------------------
# KSDMA — evaluated, no machine-readable source exists
# ---------------------------------------------------------------------------

def ksdma_status() -> ProviderStatus:
    """KSDMA has no documented machine-readable API, so nothing is fetched.

    Reported honestly as ``UNAVAILABLE`` with the reason, rather than scraping
    the HTML/PDF bulletins or inventing an endpoint.
    """
    source = "Kerala State Disaster Management Authority (sdma.kerala.gov.in)"
    coverage = "Kerala (state disaster alerts, rainfall and warnings)"
    if not config.KSDMA_ENABLED:
        return ProviderStatus(
            provider=PROVIDER_KSDMA,
            status=STATUS_NOT_CONFIGURED,
            source=source,
            error="KSDMA source is disabled (KSDMA_ENABLED=off).",
            coverage=coverage,
        )
    return ProviderStatus(
        provider=PROVIDER_KSDMA,
        status=STATUS_UNAVAILABLE,
        source=source,
        error=(
            "KSDMA publishes warnings as HTML/PDF bulletins and social/app pushes and "
            "documents no machine-readable API, so no data is fetched. Data is sourced "
            "from IMD for Kerala instead."
        ),
        coverage=coverage,
    )


def fetch_ksdma() -> Dict[str, Any]:
    """KSDMA has no official API — return the honest payload, never fabricated rows."""
    status = ksdma_status()
    return {
        "provider": PROVIDER_KSDMA,
        "data_status": status.status,
        "data_source": status.source,
        "available": False,
        "error": status.error,
        "records": [],
    }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _cached_probe(key: str, probe) -> _Probe:
    """Run ``probe`` through the TTL cache; failures expire faster."""
    cached = _PROBE_CACHE.get(key)
    if cached is not None:
        return _Probe(status=cached, from_cache=True)

    status = probe()
    ttl = (
        config.HISTORICAL_PROVIDER_CACHE_TTL_SEC
        if status.status in (STATUS_LIVE, STATUS_HISTORICAL)
        else config.HISTORICAL_PROVIDER_FAILURE_CACHE_TTL_SEC
    )
    with _PROBE_LOCK:
        _PROBE_CACHE.set(key, status, ttl)
    return _Probe(status=status, from_cache=False)


# provider -> probe callable. Every probe returns a _Probe. ERA5 and KSDMA are
# resolved from configuration/registry without any network I/O.
_PROBES = {
    PROVIDER_ERA5: lambda: _Probe(era5_status()),
    PROVIDER_IMD: lambda: _cached_probe("imd", _imd_probe),
    PROVIDER_INDIAWRIS: lambda: _cached_probe("indiawris", _indiawris_probe),
    PROVIDER_KSDMA: lambda: _Probe(ksdma_status()),
}


def provider_status(provider: str) -> ProviderStatus:
    """Status for a single provider. Never raises."""
    probe = _PROBES.get(provider)
    if probe is None:
        return ProviderStatus(
            provider=provider,
            status=STATUS_UNAVAILABLE,
            source="Unknown provider",
            error=f"No probe is registered for provider '{provider}'.",
        )
    try:
        result = probe()
    except Exception as exc:  # pragma: no cover - defensive: dashboard must not 500
        return ProviderStatus(
            provider=provider,
            status=STATUS_ERROR,
            source="Provider status probe failed",
            error=f"{type(exc).__name__}: {exc}",
        )

    status = result.status
    if result.from_cache:
        # Copy before annotating: the TTL cache holds this exact instance, so
        # mutating it in place would retroactively rewrite the cached entry and
        # make the first (fresh) result claim to be cached too.
        status = replace(status)
        status.cached = True
        if status.status == STATUS_LIVE:
            status.status = STATUS_CACHED
    return status


def provider_statuses() -> List[ProviderStatus]:
    """Status for every official provider, in stable display order."""
    return [provider_status(name) for name in (PROVIDER_ERA5, PROVIDER_IMD, PROVIDER_INDIAWRIS, PROVIDER_KSDMA)]


def clear_probe_cache() -> None:
    """Drop cached probe results (used by tests and admin refresh paths)."""
    _PROBE_CACHE.clear()