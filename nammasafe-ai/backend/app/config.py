import json
import os
from pathlib import Path

# Load backend/.env (gitignored) so operator secrets like the NASA Earthdata
# token never have to live in tracked files or shell history.
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_BACKEND_DIR = Path(__file__).resolve().parent.parent

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    # Stable, CWD-independent default so the SQLite cache (terrain_samples,
    # historical_weather_samples, ...) never wanders to a stray file in the
    # directory the server happened to be launched from.
    "sqlite:///" + str(_BACKEND_DIR / "nammasafe.db").replace("\\", "/"),
)
JWT_SECRET = os.getenv("JWT_SECRET", "nammasafe-super-secret-key-chamoli-2025")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_MINUTES = 60 * 24

PILOT_DISTRICT = "Chamoli"
PILOT_STATE = "Uttarakhand"
PILOT_CENTER_LAT = 30.4000
PILOT_CENTER_LNG = 79.3300

# -------------------- Historical (Previous-Year) Data --------------------
# Default dataset year = most recent completed year (2026 -> 2025).
# Every imported row keeps the actual source data_year; this is only the
# fallback/expected year used by the baseline when none is supplied.
HISTORICAL_DATA_YEAR = int(os.getenv("HISTORICAL_DATA_YEAR", "2025"))
# Plausibility ceiling for a single daily rainfall observation (mm).
HISTORICAL_MAX_RAINFALL_MM = float(os.getenv("HISTORICAL_MAX_RAINFALL_MM", "1500"))
# Minimum number of observations before percentile statistics are published.
HISTORICAL_MIN_PERCENTILE_OBS = int(os.getenv("HISTORICAL_MIN_PERCENTILE_OBS", "30"))

# -------------------- Evacuation Routing --------------------
# Provider stays "local" for the pilot (curated graph + risk-aware A*).
# An OSRM / GraphHopper backend can be swapped in behind RoutingProvider.
ROUTING_PROVIDER = os.getenv("ROUTING_PROVIDER", "local")
ROUTE_MAX_SEARCH_KM = float(os.getenv("ROUTE_MAX_SEARCH_KM", "120"))
ROUTE_SNAP_M = float(os.getenv("ROUTE_SNAP_M", "250"))
ROUTE_SNAP_FALLBACK_M = float(os.getenv("ROUTE_SNAP_FALLBACK_M", "6000"))
EVACUATION_CACHE_TTL_MIN = int(os.getenv("EVACUATION_CACHE_TTL_MIN", "60"))
EVACUATION_WALK_SPEED_KMH = float(os.getenv("EVACUATION_WALK_SPEED_KMH", "4.0"))
MAX_CANDIDATE_ROUTES = int(os.getenv("MAX_CANDIDATE_ROUTES", "3"))

# -------------------- Map Provider --------------------
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

# -------------------- Live Weather (Open-Meteo primary / ECMWF backup) --------------------
# Open-Meteo requires no API key and is the default primary provider. ECMWF (via
# the Open-Meteo /ecmwf model endpoint, IFS 0.25°) is the always-present backup
# and is used only when the primary is unreachable or unparseable. No values are
# ever fabricated: a provider's missing variables stay null and data_status is
# UNAVAILABLE only when both providers fail.
OPEN_METEO_BASE_URL = os.getenv("OPEN_METEO_BASE_URL", "https://api.open-meteo.com/v1")
# ECMWF backup is served through the SAME /forecast contract by selecting the
# `ecmwf_ifs025` (IFS HRES 0.25°) model — the legacy /v1/ecmwf endpoint has no
# /forecast suffix.
ECMWF_BASE_URL = os.getenv("ECMWF_BASE_URL", "https://api.open-meteo.com/v1")
WEATHER_CACHE_TTL_SEC = int(os.getenv("WEATHER_CACHE_TTL_SEC", "600"))
WEATHER_TIMEOUT_SEC = float(os.getenv("WEATHER_TIMEOUT_SEC", "15"))
# Forecast horizon (days) for a single-location request. 1..7.
WEATHER_FORECAST_DAYS = int(os.getenv("WEATHER_FORECAST_DAYS", "7"))
# Grid (nationwide weather map) limits — see /api/weather/grid.
WEATHER_GRID_MAX_POINTS = int(os.getenv("WEATHER_GRID_MAX_POINTS", "600"))
WEATHER_GRID_STEP = float(os.getenv("WEATHER_GRID_STEP", "0.25"))
WEATHER_GRID_CACHE_TTL_SEC = int(os.getenv("WEATHER_GRID_CACHE_TTL_SEC", str(WEATHER_CACHE_TTL_SEC)))
# Preferred provider chain for grid layers: "auto" (Open-Meteo primary, ECMWF
# backup — the behaviour existing consumers rely on) or "ecmwf" (ECMWF IFS 0.25°
# attempted first, Open-Meteo only as fallback). The weather & hazard map
# requests "ecmwf" so its source panel is honest about the model serving.
WEATHER_PREFERRED_PROVIDER = os.getenv("WEATHER_PREFERRED_PROVIDER", "auto")
# Number of grid cells sent per upstream multi-location request (Open-Meteo
# accepts comma-separated latitude/longitude arrays up to 1000 points).
WEATHER_BATCH_SIZE = int(os.getenv("WEATHER_BATCH_SIZE", "200"))
# After a provider answers HTTP 429 (or otherwise fails), block further calls to
# that provider for this many seconds so we never hammer a throttled upstream.
# `Retry-After` from the response is honoured when present (capped at 60s).
WEATHER_PROVIDER_COOLDOWN_SEC = int(os.getenv("WEATHER_PROVIDER_COOLDOWN_SEC", "30"))
# Upper bound on concurrent upstream provider HTTP requests. Keeps a multi-chunk
# grid view from firing a burst that trips free-tier rate limiters.
WEATHER_MAX_CONCURRENT = int(os.getenv("WEATHER_MAX_CONCURRENT", "2"))
# TTL for cached *failure* payloads (UNAVAILABLE grids/points/blocks). Short so a
# wounded provider can recover quickly and the map does not stay unusable for the
# full success-cache TTL. Success payloads keep WEATHER_GRID_CACHE_TTL_SEC.
WEATHER_FAILURE_CACHE_TTL_SEC = int(os.getenv("WEATHER_FAILURE_CACHE_TTL_SEC", "30"))

# -------------------- Weather platform (provider registry) --------------------
# The current live-weather chain (Open-Meteo primary / ECMWF backup) ships
# DISABLED by default: a fresh deployment must never make unsolicited calls to
# live weather APIs. The historical ERA5 archive provider is enabled instead.
# Operators flip WEATHER_LIVE_ENABLED=on (and add provider tokens) to re-enable
# the live chain — the registry in app/weather_platform.py mirrors this switch.
WEATHER_LIVE_ENABLED = os.getenv("WEATHER_LIVE_ENABLED", "off") == "on"

# -------------------- Historical Weather (ERA5 Archive) --------------------
# Open-Meteo's ERA5 reanalysis archive (ECMWF) is the default historical
# provider: real reanalysis fields, no API key, global coverage including
# India. Swappable via the provider registry in app/weather_platform.py.
HISTORICAL_WEATHER_BASE_URL = os.getenv(
    "HISTORICAL_WEATHER_BASE_URL",
    "https://archive-api.open-meteo.com/v1",
)
HISTORICAL_WEATHER_TIMEOUT_SEC = float(os.getenv("HISTORICAL_WEATHER_TIMEOUT_SEC", "20"))
# Year range surfaced by the historical weather selector. The *current* year is
# only served for completed months (see historical_weather.available_periods).
HISTORICAL_YEAR_MIN = int(os.getenv("HISTORICAL_YEAR_MIN", "2022"))
HISTORICAL_YEAR_MAX = int(os.getenv("HISTORICAL_YEAR_MAX", "2026"))
HISTORICAL_WEATHER_CACHE_TTL_SEC = int(os.getenv("HISTORICAL_WEATHER_CACHE_TTL_SEC", "604800"))
# Cells per upstream multi-location request (ERA5 archive accepts arrays).
HISTORICAL_WEATHER_BATCH = int(os.getenv("HISTORICAL_WEATHER_BATCH", "200"))
# Reuse the same cooldown the live chain uses so a throttled archive provider
# is never hammered on retries.
HISTORICAL_WEATHER_COOLDOWN_SEC = int(os.getenv("HISTORICAL_WEATHER_COOLDOWN_SEC", str(WEATHER_PROVIDER_COOLDOWN_SEC)))
HISTORICAL_WEATHER_MAX_CONCURRENT = int(os.getenv("HISTORICAL_WEATHER_MAX_CONCURRENT", "2"))
# Persist validated ERA5 samples to the historical_weather_samples cache table.
HISTORICAL_WEATHER_DB_CACHE = os.getenv("HISTORICAL_WEATHER_DB_CACHE", "on") == "on"

# IMD Mausam "Current Weather" API (LEGACY, optional, disabled by default).
# The default provider chain is Open-Meteo (primary) -> ECMWF (backup). Only
# when BOTH the base URL and a token are provided does IMD rejoin as a
# last-resort primary (backward compatibility for existing operators); empty
# strings keep it disabled.
IMD_MAUSAM_BASE_URL = os.getenv("IMD_MAUSAM_BASE_URL", "")
IMD_MAUSAM_TOKEN = os.getenv("IMD_MAUSAM_TOKEN", "")
IMD_MAUSAM_TIMEOUT_SEC = float(os.getenv("IMD_MAUSAM_TIMEOUT_SEC", "12"))

# -------------------- Terrain (NASA Earthdata SRTM primary / Open-Meteo fallback) --------------------
TERRAIN_CACHE_TTL_SEC = int(os.getenv("TERRAIN_CACHE_TTL_SEC", "86400"))
# Number of cardinal samples around the query point used for slope estimation.
TERRAIN_GRID_SAMPLES = int(os.getenv("TERRAIN_GRID_SAMPLES", "8"))
# Distance (km) from the query point to the sample ring used for slope
# (Open-Meteo provider only).
TERRAIN_SAMPLE_KM = float(os.getenv("TERRAIN_SAMPLE_KM", "1.2"))


def _read_nasa_token_from_file() -> str:
    """Read the NASA Earthdata bearer token from the operator's local file.

    The spec references the file `apikeynasa.env` at the repository root; the
    exact variants present on disk are also accepted (`apikeynasa.env.env`,
    `apikeynasa.env.txt`). Each may hold the raw JWT (single line or wrapped)
    or dotenv-style `NASA_EARTHDATA_TOKEN=<token>` / `EARTHDATA_TOKEN=<token>`
    lines. A token is only accepted when it looks like a complete 3-segment
    JWT. The value is used server-side only and is never logged or exposed.
    """
    repo_root = Path(__file__).resolve().parents[3]
    candidates = [
        repo_root / "apikeynasa.env",
        repo_root / "apikeynasa.env.env",
        repo_root / "apikeynasa.env.txt",
    ]
    for path in candidates:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        token: str | None = None
        continuation: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                key, _, value = stripped.partition("=")
                if key.strip().upper() in ("NASA_EARTHDATA_TOKEN", "EARTHDATA_TOKEN"):
                    token = value.strip().strip('"').strip("'")
                    break
            else:
                continuation.append(stripped)
        if token is None and continuation:
            token = "".join(continuation)
        if token and token.count(".") == 2:
            return token
    return ""


# NASA Earthdata Login bearer token (a JWT), resolved in priority order:
#   1. NASA_EARTHDATA_TOKEN env var
#   2. EARTHDATA_TOKEN env var (shared NASA token; also used by GPM rainfall)
#   3. the operator's local apikeynasa.env / apikeynasa.env.env file
NASA_EARTHDATA_TOKEN = (
    os.getenv("NASA_EARTHDATA_TOKEN", "").strip()
    or os.getenv("EARTHDATA_TOKEN", "").strip()
    or _read_nasa_token_from_file()
)
# Official NASA LP DAAC Earthdata Cloud distribution of the Shuttle Radar
# Topography Mission Global 1 arc-second Version 3 DEM (SRTMGL1.003).
# DOI: https://doi.org/10.5067/MEASURES/SRTM/SRTMGL1.003 . {tile} expands to a
# 1-degree tile name like N30E079. Auth: "Authorization: Bearer <EDL token>".
NASA_SRTM_LPDAAC_URL_TEMPLATE = os.getenv(
    "NASA_SRTM_LPDAAC_URL_TEMPLATE",
    "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/SRTMGL1.003/{tile}.SRTMGL1.hgt/{tile}.SRTMGL1.hgt.zip",
)
NASA_SRTM_TIMEOUT_SEC = float(os.getenv("NASA_SRTM_TIMEOUT_SEC", "30"))
NASA_SRTM_MAX_TILES = int(os.getenv("NASA_SRTM_MAX_TILES", "16"))
# Parallelism for terrain-grid sampling downloads (threads, network-bound).
TERRAIN_GRID_WORKERS = int(os.getenv("TERRAIN_GRID_WORKERS", "8"))
# Overall budget for a terrain-grid request. When the SRTM sources are slow or
# unreachable the grid degrades to an honest UNAVAILABLE (never a hang) once the
# budget lapses, so the terrain layer always settles.
TERRAIN_GRID_TIMEOUT_SEC = float(os.getenv("TERRAIN_GRID_TIMEOUT_SEC", "45"))
# Arc-seconds between the +/- samples used for the real slope window (~90 m at
# the equator). The native SRTMGL1 grid is 1 arc-second (~30 m).
NASA_TERRAIN_SAMPLE_ARCSEC = int(os.getenv("NASA_TERRAIN_SAMPLE_ARCSEC", "3"))
# Persist validated NASA SRTM samples to the terrain_samples cache table.
TERRAIN_DB_CACHE = os.getenv("TERRAIN_DB_CACHE", "on")
# Open-Meteo may be used as a fallback ONLY when this is explicitly "on".
# Off by default: NASA failure is reported honestly as UNAVAILABLE.
NASA_TERRAIN_FALLBACK_OPENMETEO = os.getenv("NASA_TERRAIN_FALLBACK_OPENMETEO", "off") == "on"

# -------------------- Copernicus CDS / GloFAS --------------------
# The CDS API is job-based, not a simple REST lookup. GloFAS point extraction
# runs against a downloaded/cached NetCDF dataset. Prefer GLOFAS_DATASET_PATH
# (an explicit NetCDF file); otherwise the first *.nc under GLOPAS_DATA_DIR is
# used. Without credentials and a cached dataset the service returns
# NOT_CONFIGURED, and an unreadable dataset returns UNAVAILABLE.
CDS_API_URL = os.getenv("CDS_API_URL", "https://cds.climate.copernicus.eu/api/v2")
CDS_API_KEY = os.getenv("CDS_API_KEY", "")
CDS_API_SECRET = os.getenv("CDS_API_SECRET", "")
GLOFAS_DATASET_PATH = os.getenv("GLOFAS_DATASET_PATH", "")
GLOPAS_DATA_DIR = os.getenv("GLOPAS_DATA_DIR", "")
GLOPAS_DATASET = os.getenv("GLOPAS_DATASET", "cems-glofas-forecast")
FLOOD_CACHE_TTL_SEC = int(os.getenv("FLOOD_CACHE_TTL_SEC", "1800"))

# -------------------- NASA GPM / GES DISC --------------------
# GPM IMERG is distributed as bulk HDF5/NetCDF files, not a point REST API.
# GPM_MODE=on enables extraction from an ingested tile in GPM_DATA_DIR.
GPM_MODE = os.getenv("GPM_MODE", "off")
GPM_DATA_DIR = os.getenv("GPM_DATA_DIR", "")
EARTHDATA_USERNAME = os.getenv("EARTHDATA_USERNAME", "")
EARTHDATA_TOKEN = os.getenv("EARTHDATA_TOKEN", "")
RAINFALL_CACHE_TTL_SEC = int(os.getenv("RAINFALL_CACHE_TTL_SEC", "3600"))

# -------------------- Bhuvan / ISRO (India geospatial) --------------------
# Official Bhuvan v2 REST gateways (docs: https://bhuvan-app1.nrsc.gov.in/api/).
# The access token (most APIs) and the key (geoid tile API) are operator
# secrets: they live only in backend/.env (gitignored) and are consumed
# server-side — never by the browser bundle.
BHUVAN_API_BASE_URL = os.getenv("BHUVAN_API_BASE_URL", "https://bhuvan-app1.nrsc.gov.in/api")
BHUVAN_API_TOKEN = os.getenv("BHUVAN_API_TOKEN", "")
BHUVAN_API_KEY = os.getenv("BHUVAN_API_KEY", "")
BHUVAN_TIMEOUT_SEC = float(os.getenv("BHUVAN_TIMEOUT_SEC", "15"))
# Static/historical datasets (LULC, routing) use a long TTL.
BHUVAN_CACHE_TTL_SEC = int(os.getenv("BHUVAN_CACHE_TTL_SEC", "86400"))
# Census-2001 records are effectively immutable; cache for ~30 days.
BHUVAN_GEOCODE_TTL_SEC = int(os.getenv("BHUVAN_GEOCODE_TTL_SEC", "2592000"))
# When "on", the LULC and geoid factors participate in the risk engine. Off by
# default so the engine stays on its verified live sources.
BHUVAN_RISK_FACTOR = os.getenv("BHUVAN_RISK_FACTOR", "off")

# -------------------- OpenStreetMap providers --------------------
OVERPASS_API_URL = os.getenv("OVERPASS_API_URL", "https://overpass-api.de/api/interpreter")
# Conservative minimum interval between Outbound Overpass requests.
OVERPASS_MIN_INTERVAL_SEC = float(os.getenv("OVERPASS_MIN_INTERVAL_SEC", "1.5"))
NEARBY_RADIUS_KM_DEFAULT = float(os.getenv("NEARBY_RADIUS_KM_DEFAULT", "20.0"))
NEARBY_CACHE_TTL_SEC = int(os.getenv("NEARBY_CACHE_TTL_SEC", "1800"))
NOMINATIM_BASE_URL = os.getenv("NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org")
GEOCODE_CACHE_TTL_SEC = int(os.getenv("GEOCODE_CACHE_TTL_SEC", "2592000"))
GEOCODE_MIN_INTERVAL_SEC = float(os.getenv("GEOCODE_MIN_INTERVAL_SEC", "1.0"))
OSM_USER_AGENT = os.getenv("OSM_USER_AGENT", "NammaSafeAI-DisasterDecisionSupport/1.0 (govt pilot)")

# -------------------- Routing --------------------
# ROUTING_PROVIDER: "local" (curated risk-aware A*), "osrm" (public OSRM),
# "auto" (try OSRM, fall back to local graph).
OSRM_BASE_URL = os.getenv("OSRM_BASE_URL", "https://router.project-osrm.org")
ROUTER_CACHE_TTL_SEC = int(os.getenv("ROUTER_CACHE_TTL_SEC", "1800"))

# -------------------- Risk Assessment Engine --------------------
# Transparent, configurable weights (not validated scientific weights). Kept in
# environment so operators can tune risk behaviour without a code change.
RISK_ASSESSMENT_WEIGHTS = json.loads(
    os.getenv(
        "RISK_ASSESSMENT_WEIGHTS",
        json.dumps(
            {
                "rainfall": 0.25,
                "water": 0.25,
                "elevation": 0.20,
                "historical": 0.15,
                "proximity": 0.10,
                "field_damage": 0.05,
                "lulc": 0.06,
                "geoid": 0.02,
            }
        ),
    )
)
# 0-30 LOW, 31-60 MEDIUM, 61-80 HIGH, 81-100 CRITICAL
RISK_BANDS = [
    {"max": 30.0, "level": "LOW"},
    {"max": 60.0, "level": "MEDIUM"},
    {"max": 80.0, "level": "HIGH"},
    {"max": 100.0, "level": "CRITICAL"},
]
# Assessment mode exposed to the UI. "rule_based" is authoritative until a
# trained model is present ("hybrid" / "ml").
ASSESSMENT_MODE = os.getenv("ASSESSMENT_MODE", "rule_based")
ML_MODEL_PATH = os.getenv("ML_MODEL_PATH", "")  # *.onnx or sklearn joblib
# Search radii used to gather historical events and field damage reports.
HISTORICAL_EVENT_RADIUS_KM = float(os.getenv("HISTORICAL_EVENT_RADIUS_KM", "50.0"))
FIELD_REPORT_RADIUS_KM = float(os.getenv("FIELD_REPORT_RADIUS_KM", "25.0"))

# Per-hazard weight profile. Inf values represent impassable / closed.
RISK_WEIGHTS = {
    "slope_flat": 1.0,
    "slope_moderate": 1.3,
    "slope_steep": 1.8,
    "bridge_crossing": 1.5,
    "landslide_high": 5.0,
    "flood_moderate": 6.0,
    "wildfire_proximity": 4.0,
    "earthquake_impact": 6.0,
    "habitation_proximity": 1.5,
    "road_damage_report": 2.0,
    "restricted_condition": 2.5,
    "critical_exit": 4.0,
}
