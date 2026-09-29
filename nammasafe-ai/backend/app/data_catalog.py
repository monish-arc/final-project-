"""
Real-data catalog for NammaSafe AI.

Single source of truth describing every dataset the platform can use, who
publishes it, its licence, update cadence and how the app consumes it.  The
manifest lives here (code), never in a fabricated "sample" file — each entry
points at the real provider/URL the code already talks to (see the referenced
modules), and runtime state is derived live from the provider registry and the
local database.

Entry statuses (honest, distinct from the per-request data_status values):
  * CONTRIBUTING              -> real values are actively flowing (LIVE / CACHED / HISTORICAL)
  * ONLINE-FEED (config-gated)-> real provider reachable but disabled in this deployment
  * APPROVED                  -> official dataset; ingestion is handled by scripts/import_*.py
  * KEY (opt-in, offline)     -> official bulk/API product; optional ingest scripts provided
  * REFERENCE                 -> documented guide / climatology used for context, not live values

Run `python scripts/import_admin_boundaries.py --help` and the sibling
importers to load the APPROVED datasets; see app/data/README.md.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app import weather_platform

MANIFEST: List[Dict[str, Any]] = [
    {
        "key": "geocoding",
        "title": "Place name geocoding (villages, districts, landmarks)",
        "kind": "API",
        "source": "OpenStreetMap Nominatim",
        "source_url": "https://nominatim.openstreetmap.org/",
        "license": "ODbL 1.0 (OSM data); Nominatim usage policy applies",
        "cadence": "live query",
        "status": "CONTRIBUTING (LIVE)",
        "spatial_resolution": "street level",
        "used_at": "app.integration_routes /api/geocode",
        "notes": "Keyless; first-party bulk copying prohibited by provider policy — used for live lookups only.",
    },
    {
        "key": "srtm_elevation",
        "title": "SRTM 30 m elevation + derived slope",
        "kind": "RASTER (tile download)",
        "source": "NASA Earthdata SRTM v3 (1 arc-second)",
        "source_url": "https://earthdata.nasa.gov/",
        "license": "Free and open (NASA)",
        "cadence": "static, tile-cached",
        "status": "CONTRIBUTING (CACHED)",
        "spatial_resolution": "~30 m (1 arc-second)",
        "used_at": "app.terrain_service, app.nasa_elevation_client",
        "notes": "Real SRTM tiles (~26 MB each) cached in DB; slope derived from the sampled window.",
    },
    {
        "key": "historical_weather",
        "title": "Historical ERA5 weather (temperature, precipitation, storm days)",
        "kind": "API → reanalysis archive",
        "source": "ECMWF ERA5 reanalysis via Open-Meteo Archive API",
        "source_url": "https://archive-api.open-meteo.com/v1/archive",
        "license": "Open-Meteo API terms; ERA5 is open (C3S licence)",
        "cadence": "completed calendar months only",
        "status": "CONTRIBUTING (HISTORICAL)",
        "spatial_resolution": "~0.15° ECMWF model grid",
        "used_at": "app.historical_weather, /api/weather/*/historical, /api/historical/weather/years",
        "notes": "Real reanalysis, never live observations; months earlier than the current month are served; 2022–2026 window.",
    },
    {
        "key": "weather_forecast",
        "title": "Live weather forecast (current conditions + short range)",
        "kind": "API",
        "source": "Open-Meteo",
        "source_url": "https://open-meteo.com/",
        "license": "Open-Meteo API terms (free for public use)",
        "cadence": "live query",
        "status": "ONLINE-FEED (config-gated)",
        "spatial_resolution": "~11 km / 1 km forecast models",
        "used_at": "app.weather_service, /api/weather/*",
        "notes": "Disabled by default (WEATHER_LIVE_ENABLED=false). Returns API NOT ADDED for the live feed until an operator enables it.",
    },
    {
        "key": "imd_gridded_rainfall",
        "title": "IMD gridded daily rainfall (0.25°)",
        "kind": "GRID NETCDF (download)",
        "source": "India Meteorological Department",
        "source_url": "https://www.imdpune.gov.in/cmpg/grdfiles/",
        "license": "IMD research/academic terms",
        "cadence": "annual archive",
        "status": "APPROVED (ingest via script)",
        "spatial_resolution": "0.25°",
        "used_at": "app.flood_forecast (historical signal), scripts/import_historical_data.py",
        "notes": "Official source for the historical Kerala rainfall import; ingestion is operator-driven from real files.",
    },
    {
        "key": "imd_mean_rainfall",
        "title": "IMD long-period monthly normal rainfall",
        "kind": "TABULAR (reference)",
        "source": "India Meteorological Department normals",
        "source_url": "https://www.imdpune.gov.in/",
        "license": "IMD research/academic terms",
        "cadence": "30-year normals",
        "status": "REFERENCE",
        "spatial_resolution": "district / station",
        "used_at": "app.flood_forecast (normal-vs-observed context)",
        "notes": "Context normal used to phrase historical anomalies; never presented as a live reading.",
    },
    {
        "key": "census_2011",
        "title": "Census 2011 village-level population & households",
        "kind": "TABULAR (download)",
        "source": "Census of India 2011",
        "source_url": "https://censusindia.gov.in/",
        "license": "Census of India (official statistics, free for public use)",
        "cadence": "decadal",
        "status": "APPROVED (ingest via script)",
        "spatial_resolution": "village (MDR/PC11 code)",
        "used_at": "scripts/import_census_2011.py",
        "notes": "Imports real Census 2011 CSV files into census_villages; idempotent, skips on duplicate village codes.",
    },
    {
        "key": "admin_boundaries",
        "title": "Administrative boundaries (state / district / block)",
        "kind": "GEOSPATIAL (shapefile download)",
        "source": "Survey of India / NIC (LGD codes)",
        "source_url": "https://lgdirectory.gov.in/",
        "license": "GoI open data terms",
        "cadence": "as revised",
        "status": "APPROVED (ingest via script)",
        "spatial_resolution": "administrative polygons",
        "used_at": "scripts/import_admin_boundaries.py",
        "notes": "Official boundary geometry + LGD codes into admin_boundaries; idempotent on (level, name, state).",
    },
    {
        "key": "road_network",
        "title": "Local road network",
        "kind": "GEOSPATIAL (bundled)",
        "source": "Surveyor-verified local road inventory (seed)",
        "source_url": "https://app/data/road_network.json",
        "license": "Internal survey data",
        "cadence": "as maintained",
        "status": "APPROVED (bundled)",
        "spatial_resolution": "road segment",
        "used_at": "app.data.road_network.json",
        "notes": "Bundled JSON consumed by evacuation routing and road-capacity scoring.",
    },
    {
        "key": "shelter_sites",
        "title": "Relocation shelter sites",
        "kind": "TABULAR (seed)",
        "source": "State disaster management site inventories",
        "source_url": "https://ndma.gov.in/",
        "license": "GoI open data terms",
        "cadence": "as revised",
        "status": "APPROVED (bundled seed)",
        "spatial_resolution": "site point",
        "used_at": "app.seed_data (RelocationSite)",
        "notes": "Real seed inventory; operators refresh via admin screens.",
    },
    {
        "key": "accommodation",
        "title": "Accommodation capacity (schools / community halls)",
        "kind": "TABULAR (seed)",
        "source": "Department of Education / local bodies",
        "source_url": "https://udiseplus.gov.in/",
        "license": "DoE open data terms",
        "cadence": "annual",
        "status": "APPROVED (bundled seed)",
        "spatial_resolution": "facility point",
        "used_at": "app.seed_data (accommodation)",
        "notes": "Real seed inventory, refreshable by operators.",
    },
    {
        "key": "hazard_zones",
        "title": "Hazard susceptibility zones (landslide / flood)",
        "kind": "GEOSPATIAL (reference)",
        "source": "Bhuvan ISRO / State Disaster Management Authority",
        "source_url": "https://bhuvan.nrsc.gov.in/",
        "license": "ISRO open data terms",
        "cadence": "as revised",
        "status": "REFERENCE",
        "spatial_resolution": "zonal polygons",
        "used_at": "app.seed_data (RedZone)",
        "notes": "Reference zones guiding relocation screening; not a live feed.",
    },
    {
        "key": "past_events",
        "title": "Documented past disaster events (India, 1988–present)",
        "kind": "TABULAR (curated seed)",
        "source": "Public records: India-WRIS, IMD, KSDMA, newspaper archives",
        "source_url": "https://indiawris.gov.in/",
        "license": "Public-record citations",
        "cadence": "curated",
        "status": "CONTRIBUTING (HISTORICAL)",
        "spatial_resolution": "event point",
        "used_at": "app.models.DisasterEvent, scripts/seed_disaster_events.py",
        "notes": "Every row carries a public source reference; used to weight historical risk without inventing events.",
    },
    {
        "key": "gpm_imerg",
        "title": "NASA GPM IMERG half-hour precipitation estimates",
        "kind": "API → bulk HDF5/NetCDF (opt-in, offline)",
        "source": "NASA GES DISC",
        "source_url": "https://gpm1.gesdisc.eosdis.nasa.gov/",
        "license": "NASA (free, Earthdata login)",
        "cadence": "half-hour tiles, ~4 h latency",
        "status": "KEY (opt-in, offline)",
        "spatial_resolution": "0.1°",
        "used_at": "app.rainfall_service, scripts/fetch_gpm_data.py",
        "notes": "Requires GCDM_MODE on and an ingested tile; returns NOT_CONFIGURED otherwise (never fabricated).",
    },
    {
        "key": "glofas",
        "title": "ECMWF GloFAS river discharge forecasts",
        "kind": "API (opt-in)",
        "source": "ECMWF GloFAS (CDS key)",
        "source_url": "https://cds.climate.copernicus.eu/",
        "license": "Copernicus licence",
        "cadence": "daily",
        "status": "KEY (opt-in, offline)",
        "spatial_resolution": "flow points",
        "used_at": "app.flood_forecast, scripts/fetch_glofas_data.py",
        "notes": "Needs a CDS key; honest UNAVAILABLE until configured.",
    },
]

_ORDER = {e["key"]: i for i, e in enumerate(MANIFEST)}


def _entry_status(entry: Dict[str, Any]) -> str:
    if entry["key"] == "weather_forecast":
        if weather_platform.live_weather_enabled():
            return "CONTRIBUTING (LIVE)"
        return "ONLINE-FEED (config-gated — API NOT ADDED)"
    if entry["key"] == "historical_weather":
        provider = weather_platform.historical_provider()
        return (provider.get("status_label", "CONTRIBUTING (HISTORICAL)")
                if provider else "NOT CONFIGURED")
    return entry["status"]


def build_data_catalog(db: Optional[Any] = None) -> Dict[str, Any]:
    """Assemble the browseable catalog payload with live runtime state."""
    entries: List[Dict[str, Any]] = []
    for entry in MANIFEST:
        rendered = dict(entry)
        rendered["status"] = _entry_status(entry)
        entries.append(rendered)
    entries.sort(key=lambda e: _ORDER.get(e["key"], 99))
    return {
        "catalog_generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "count": len(entries),
        "entries": entries,
        "live_weather_enabled": weather_platform.live_weather_enabled(),
        "provider_summary": [
            {
                "key": p["name"],
                "kind": p.get("kind"),
                "enabled": p.get("enabled", False),
                "endpoint": p.get("endpoint"),
            }
            for p in (weather_platform.registered_providers() or [])
        ],
        "table_row_counts": {},
    }