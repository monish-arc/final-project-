"""
Flood forecast adapter.

Provides a single honest flood-forecast endpoint that either:
  * returns the real Copernicus GloFAS forecast for the requested region when a
    downloaded CEMS GloFAS NetCDF dataset is configured and readable
    (GLOFAS_DATASET_PATH or GLOPAS_DATA_DIR), reading the discharge for the
    grid cell nearest the region anchor only when that cell lies inside the
    requested region's bounding box, or
  * returns NOT_CONFIGURED when no dataset is configured, or
  * returns an explicitly-labelled UNAVAILABLE payload when the dataset cannot
    be read or does not cover the requested region (empty gauge list).

The app NEVER fabricates river levels, and it NEVER substitutes a different
region's forecast for another location: a forecast for a cell outside the
requested region's bounding box is reported as UNAVAILABLE.

There is deliberately no demo/synthetic gauge seed here: every layer on the
map is either real provider data or an honest "Data unavailable for this
location" response.
"""

import importlib.util
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.flood_service import CopernicusGloFASProvider

# Coarse state-level bounding boxes (lat_min, lat_max, lon_min, lon_max) used to
# anchor the GloFAS read and to enforce the "never substitute a region" rule:
# a dataset cell is only reported for a region whose box contains it.
_REGION_BOUNDS: Dict[str, tuple] = {
    "TAMIL NADU": (8.0, 13.6, 76.2, 80.4),
    "KERALA": (8.0, 12.8, 74.8, 77.4),
    "MAHARASHTRA": (16.0, 22.1, 72.6, 80.9),
    "ODISHA": (17.8, 22.6, 81.3, 87.5),
    "UTTARAKHAND": (28.7, 31.5, 77.6, 81.1),
    "WEST BENGAL": (21.5, 27.4, 85.8, 89.6),
    "BIHAR": (24.0, 27.5, 83.3, 88.3),
    "ASSAM": (25.9, 28.0, 89.6, 96.0),
}

_CALC_GRACE = 0.25  # tolerance when checking whether a dataset cell lies in a region box


def _netcdf4_installed() -> bool:
    try:
        import netCDF4  # type: ignore  # noqa: F401
        return True
    except ImportError:
        return False


def _region_bounds(state: Optional[str]) -> Optional[tuple]:
    if not state:
        return None
    return _REGION_BOUNDS.get(state.strip().upper())


def _unavailable(reason: str) -> Dict[str, Any]:
    return {
        "gauges": [],
        "zones": [],
        "data_status": "UNAVAILABLE",
        "data_source": reason,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


def _not_configured(reason: str) -> Dict[str, Any]:
    return {
        "gauges": [],
        "zones": [],
        "data_status": "NOT_CONFIGURED",
        "data_source": reason,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


def get_flood_forecasts(state: Optional[str] = None, district: Optional[str] = None) -> Dict[str, Any]:
    """
    Return the real GloFAS forecast reading for the nearest cell inside the
    requested region, or an honest NOT_CONFIGURED/UNAVAILABLE payload when the
    dataset is missing, unreadable, or does not cover the region.

    No region ever receives another region's forecast, and no request ever gets
    fabricated river levels.
    """
    provider = CopernicusGloFASProvider()
    dataset_path = provider._dataset_path()  # noqa: SLF001 - resolution seam for tests
    if dataset_path is None:
        return _not_configured(
            "No GloFAS dataset configured. Download a CEMS GloFAS forecast with "
            "backend/scripts/fetch_glofas_data.py and set GLOFAS_DATASET_PATH (or "
            "GLOPAS_DATA_DIR) to it."
        )

    region = _region_bounds(state)
    if region is None:
        return _unavailable(
            f"Region bounds unknown for '{state}' — cannot confirm GloFAS dataset coverage."
        )

    lat_min, lat_max, lon_min, lon_max = region
    anchor_lat = (lat_min + lat_max) / 2.0
    anchor_lon = (lon_min + lon_max) / 2.0

    try:
        payload = provider.fetch(anchor_lat, anchor_lon)
    except Exception as exc:  # pragma: no cover - defensive; fetch is guarded
        return _unavailable(f"Could not read GloFAS dataset: {exc}")

    status = (payload.get("data_status") or "").upper()
    cell_lat = payload.get("latitude")
    cell_lon = payload.get("longitude")

    if status == "FORECAST" and cell_lat is not None and cell_lon is not None:
        inside = (
            lat_min - _CALC_GRACE <= float(cell_lat) <= lat_max + _CALC_GRACE
            and lon_min - _CALC_GRACE <= float(cell_lon) <= lon_max + _CALC_GRACE
        )
        if inside:
            return {
                "gauges": [],
                "zones": [],
                "data_status": "FORECAST",
                "data_source": "Copernicus GloFAS (CEMS) forecast",
                "computed_at": datetime.now(timezone.utc).isoformat(),
                "forecast": {
                    "latitude": cell_lat,
                    "longitude": cell_lon,
                    "river_discharge_m3s": payload.get("river_discharge_m3s"),
                    "threshold_m3s": payload.get("threshold_m3s"),
                    "discharge_band": payload.get("discharge_band"),
                    "lead_time_hours": payload.get("lead_time_hours"),
                    "issue_time": payload.get("issue_time"),
                    "valid_time": payload.get("valid_time"),
                    "forecast_hours": payload.get("forecast_hours"),
                    "dataset": payload.get("dataset"),
                    "assumption": payload.get("assumption"),
                },
            }
        return _unavailable(
            f"GloFAS dataset covers cell {cell_lat},{cell_lon} outside the requested "
            f"region (no forecast for {state}) — honest UNAVAILABLE rather than cross-region data."
        )

    if status == "NOT_CONFIGURED":
        return _not_configured(payload.get("reason") or "No GloFAS dataset configured.")
    return _unavailable(payload.get("reason") or "GloFAS dataset present but unreadable for this location.")


def get_data_status() -> List[Dict[str, str]]:
    """
    Return the provenance and status of every data layer displayed on the map.
    This is consumed by the frontend DataSourceStatus component.
    """
    provider = CopernicusGloFASProvider()
    dataset_path = provider._dataset_path()  # noqa: SLF001 - cheap config probe
    if dataset_path is None:
        flood_status = "NOT_CONFIGURED"
        flood_source = "No GloFAS dataset configured (GLOFAS_DATASET_PATH / GLOPAS_DATA_DIR) — flood data unavailable"
    elif not _netcdf4_installed():
        flood_status = "UNAVAILABLE"
        flood_source = f"GloFAS dataset present ({os.path.basename(dataset_path)}) but netCDF4 not installed"
    else:
        flood_status = "FORECAST"
        flood_source = f"CEMS GloFAS forecast ({os.path.basename(dataset_path)})"

    basemap_status = "LIVE" if os.getenv("GOOGLE_MAPS_API_KEY") else "NOT_CONFIGURED"
    basemap_source = (
        "Google Maps Platform Map Tiles API (key configured)"
        if os.getenv("GOOGLE_MAPS_API_KEY")
        else "Esri fallback active (no key required)"
    )

    # Historical previous-year rainfall dataset (Kerala) — HISTORICAL when
    # imported, otherwise NOT_CONFIGURED. The panel uses the normalized
    # vocabulary ("NOT_CONFIGURED"), so legacy spaced values are mapped here.
    historical_status = "NOT_CONFIGURED"
    historical_source = "India-WRIS / IMD / KSDMA (not configured)"
    try:
        from app.database import SessionLocal
        from app.historical_data import availability

        _session = SessionLocal()
        try:
            _avail = availability(_session)
            historical_status = (_avail["status"] or "NOT_CONFIGURED").replace(" ", "_")
            if _avail["total_records"]:
                historical_source = (
                    f"{_avail['total_records']} previous-year rainfall records across "
                    f"{len([d for d in _avail['districts'] if d['records']])} Kerala districts"
                )
        finally:
            _session.close()
    except Exception:
        historical_status = "NOT_CONFIGURED"

    # SAFE_MOVE_AI live-intelligence layers. Each status reflects the current
    # configuration so the UI displays "not configured"/"unavailable" honestly.
    try:
        from app import config as _config
    except Exception:  # pragma: no cover
        _config = None

    # Status vocabulary (Phase 5 normalization):
    #   LIVE         → live upstream stream (current observations/tiles)
    #   MODEL        → model/algorithm-derived layer (returns a forecast/estimate)
    #   CALCULATED   → derived terrain product (SRTM)
    #   STATIC       → curated static inventory (survey-based)
    #   FORECAST     → live model forecast reading available
    #   NOT_CONFIGURED / UNAVAILABLE / HISTORICAL → per-layer honesty contract
    weather_configured = bool(_config and _config.OPEN_METEO_BASE_URL)
    weather_status = "MODEL" if weather_configured else "NOT_CONFIGURED"
    weather_source = (
        "Open-Meteo (primary, keyless) + ECMWF backup"
        if weather_configured
        else "Open-Meteo not configured — weather data unavailable"
    )
    gpm_status = "NOT_CONFIGURED"
    gpm_source = "NASA GPM IMERG (GES DISC) — no IMERG tile ingested (run scripts/fetch_gpm_data.py --recent)"
    try:
        from app.rainfall_service import rainfall_service as _rain
        if _rain._provider._configured():
            gpm_status = "LIVE"
            gpm_source = "NASA GPM IMERG (GES DISC)"
    except Exception:  # pragma: no cover
        pass
    historical_events_status = "NOT_CONFIGURED"
    historical_events_source = "Verified event archive — no curated records for this location"

    # Bhuvan / ISRO supporting layers. Status reflects configuration: when the
    # token is set the layer is live-enabled (coverage caveats remain in the
    # per-request payloads). Static datasets internally carry AVAILABLE/CACHED.
    bhuvan_status = "LIVE" if (_config and _config.BHUVAN_API_TOKEN) else "NOT_CONFIGURED"
    bhuvan_geoid_status = "LIVE" if (_config and _config.BHUVAN_API_KEY) else "NOT_CONFIGURED"
    bhuvan_census_source = "Bhuvan / ISRO village census geocode (AP & Karnataka, census-2001)"
    bhuvan_lulc_source = "Bhuvan / ISRO LULC 50K & 250K (ISRO)"
    bhuvan_hospitals_source = "Bhuvan / ISRO hospitals proximity (Andhra Pradesh)"
    bhuvan_route_source = "Bhuvan / ISRO intra-state shortest path"
    bhuvan_geoid_source = "Bhuvan / ISRO CartoDEM v3R1 geoid tile proxy"

    terrain_configured = bool(
        _config and (_config.NASA_EARTHDATA_TOKEN or _config.NASA_TERRAIN_FALLBACK_OPENMETEO)
    )
    terrain_status = "CALCULATED" if terrain_configured else "NOT_CONFIGURED"
    terrain_provenance = (
        {"version": "SRTMGL1 v003 (LP DAAC)", "spatial_resolution": "1 arc-second (~30 m)"}
        if (_config and _config.NASA_EARTHDATA_TOKEN)
        else (
            {"version": "Open-Meteo elevation (SRTM/COP90)", "spatial_resolution": "~0.1°"}
            if terrain_status == "CALCULATED"
            else {}
        )
    )
    terrain_source = (
        "NASA Earthdata SRTM (LP DAAC SRTMGL1 v003)"
        if (_config and _config.NASA_EARTHDATA_TOKEN)
        else (
            "Open-Meteo elevation fallback (NASA Earthdata token not configured)"
            if terrain_status == "CALCULATED"
            else "NASA Earthdata SRTM not configured (Open-Meteo fallback disabled)"
        )
    )

    # Provenance metadata for the science layers (honest: retrieval/validity/
    # latency are request-scoped and stay null at this config-level panel).
    weather_provenance = (
        {"version": "Open-Meteo API v1 + ECMWF IFS 0.25°", "spatial_resolution": "0.1° / 0.25°"}
        if weather_configured
        else {}
    )
    flood_provenance = (
        {"version": "CEMS GloFAS operational (lisflood)", "spatial_resolution": "~0.1° river network"}
        if flood_status == "FORECAST"
        else {}
    )
    gpm_provenance = {"version": "NASA GPM IMERG", "spatial_resolution": "0.1°"} if gpm_status == "LIVE" else {}

    return [
        {"layer": "road_network", "status": "LIVE", "source": "OpenStreetMap road graph (Overpass API)", "updated_at": "—"},
        {"layer": "hazard_zones", "status": "MODEL", "source": "Terrain-derived slope + rainfall modelling", "updated_at": "—"},
        {"layer": "habitation_risk", "status": "MODEL", "source": "Risk engine over live altitude/rainfall/terrain", "updated_at": "—"},
        {"layer": "relocation_sites", "status": "STATIC", "source": "Survey-based capacity inventory", "updated_at": "—"},
        {"layer": "flood_forecast", "status": flood_status, "source": flood_source, "updated_at": "—", **flood_provenance},
        {"layer": "google_map_tiles", "status": basemap_status, "source": basemap_source, "updated_at": "—"},
        {"layer": "satellite_tiles", "status": "LIVE", "source": "Esri World Imagery (free, no key)", "updated_at": "—"},
        {"layer": "historical_data", "status": historical_status, "source": historical_source, "updated_at": "—"},
        {"layer": "road_conditions", "status": "LIVE", "source": "Field-report-derived road status", "updated_at": "—"},
        {"layer": "evacuation_routes", "status": "LIVE", "source": "Route optimization over live road graph", "updated_at": "—"},
        {"layer": "weather", "status": weather_status, "source": weather_source, "updated_at": "—", **weather_provenance},
        {"layer": "weather_forecast", "status": "MODEL" if weather_configured else "NOT_CONFIGURED", "source": "Open-Meteo primary + ECMWF (IFS 0.25°) backup — India-wide grid", "updated_at": "—", **weather_provenance},
        {"layer": "rainfall", "status": gpm_status, "source": gpm_source, "updated_at": "—", **gpm_provenance},
        {"layer": "terrain", "status": terrain_status, "source": terrain_source, "updated_at": "—", **terrain_provenance},
        {"layer": "nearby_places", "status": "LIVE", "source": "OpenStreetMap (Overpass API)", "updated_at": "—"},
        {"layer": "risk_assessment", "status": "MODEL", "source": "Weighted rule engine (config weights) + optional ML", "updated_at": "—"},
        {"layer": "disaster_events", "status": historical_events_status, "source": historical_events_source, "updated_at": "—"},
        {"layer": "bhuvan_village_geocode", "status": bhuvan_status, "source": bhuvan_census_source, "updated_at": "—"},
        {"layer": "bhuvan_lulc", "status": bhuvan_status, "source": bhuvan_lulc_source, "updated_at": "—"},
        {"layer": "bhuvan_hospitals", "status": bhuvan_status, "source": bhuvan_hospitals_source, "updated_at": "—"},
        {"layer": "bhuvan_shortest_path", "status": bhuvan_status, "source": bhuvan_route_source, "updated_at": "—"},
        {"layer": "bhuvan_geoid", "status": bhuvan_geoid_status, "source": bhuvan_geoid_source, "updated_at": "—"},
    ]