"""
Pydantic Schemas for NammaSafe AI Request/Response Validation
"""

from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Any, Dict, Literal
from datetime import datetime

# Auth Schemas
class LoginRequest(BaseModel):
    username_or_email: str
    password: str
    state_id: Optional[str] = None
    district_id: Optional[str] = None
    sub_district_id: Optional[str] = None
    area_id: Optional[str] = None

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Dict[str, Any]


class RiskAlertCreate(BaseModel):
    area_id: str
    hazard_type: str
    severity: str
    description: str = Field(min_length=10)
    latitude: float
    longitude: float


class AccommodationUpdate(BaseModel):
    area_id: str
    site_name: str
    land_area_acres: float = Field(gt=0)
    estimated_capacity: int = Field(gt=0)
    current_occupancy_families: int = Field(ge=0)
    latitude: float
    longitude: float


class AssignmentCreate(BaseModel):
    user_id: str
    role: Literal[
        "field_officer", "local_office", "sub_district_officer",
        "district_officer", "state_officer", "gis_analysis_officer",
    ]
    state_id: str
    district_id: str
    sub_district_id: str
    area_id: str

# Habitation Schemas
class HabitationBase(BaseModel):
    village_code: str
    village_name: str
    district: str = "Chamoli"
    state: str = "Uttarakhand"
    population: int = Field(gt=0, description="Aggregated population count")
    households: int = Field(gt=0)
    children_count: int = Field(ge=0)
    elderly_count: int = Field(ge=0)
    hospital_distance_km: float = Field(ge=0.0)
    road_access_score: float = Field(ge=0.0, le=100.0)
    latitude: float
    longitude: float
    landslide_risk: float = Field(default=50.0, ge=0.0, le=100.0)
    flood_risk: float = Field(default=50.0, ge=0.0, le=100.0)
    extreme_rainfall_risk: float = Field(default=50.0, ge=0.0, le=100.0)
    past_disaster_frequency: float = Field(default=50.0, ge=0.0, le=100.0)
    notes: Optional[str] = None

class HabitationResponse(HabitationBase):
    id: str
    vulnerability_score: float
    hazard_score: float
    priority_score: float
    priority_level: str
    disaster_history_count: int

    class Config:
        from_attributes = True

# Hazard Event Schemas
class HazardEventBase(BaseModel):
    habitation_id: str
    hazard_type: str
    event_date: str
    intensity: str
    severity_level: str
    affected_people: int
    houses_damaged: int
    deaths: int
    source_url: Optional[str] = None

class HazardEventResponse(HazardEventBase):
    id: str
    habitation_name: Optional[str] = None

    class Config:
        from_attributes = True

# Red Zone Schemas
class RedZoneResponse(BaseModel):
    id: str
    zone_name: str
    hazard_type: str
    risk_level: str
    hazard_score: float
    zone_geometry: Dict[str, Any]
    data_source: str
    last_updated: str

    class Config:
        from_attributes = True

# Relocation Site Schemas
class RelocationSiteBase(BaseModel):
    site_name: str
    district: str = "Chamoli"
    land_area_acres: Optional[float] = Field(default=None, gt=0)
    estimated_capacity: Optional[int] = Field(default=None, gt=0, description="Families; None when unknown/unverified")
    current_occupancy_families: Optional[int] = Field(default=0, ge=0)
    water_score: float = Field(ge=0.0, le=100.0)
    road_score: float = Field(ge=0.0, le=100.0)
    school_score: float = Field(ge=0.0, le=100.0)
    hospital_score: float = Field(ge=0.0, le=100.0)
    low_hazard_score: float = Field(ge=0.0, le=100.0)
    flat_land_score: float = Field(ge=0.0, le=100.0)
    latitude: float
    longitude: float
    # Survey-based shelter/facility attributes (Phase 6)
    drinking_water_available: Optional[bool] = None
    toilets_available: Optional[int] = Field(default=None, ge=0)
    electricity_available: Optional[bool] = None
    medical_facility: Optional[bool] = None
    accessible_by_road: Optional[bool] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    verified: Optional[bool] = None
    last_verified: Optional[str] = None

class RelocationSiteResponse(RelocationSiteBase):
    id: str
    suitability_score: float
    land_capacity_families: int
    water_capacity_families: int
    school_capacity_families: int
    health_capacity_families: int
    road_capacity_families: int
    final_capacity_families: int
    available_capacity_families: int

    class Config:
        from_attributes = True

# Recommendation Schemas
class RelocationRecommendationResponse(BaseModel):
    id: str
    habitation_id: str
    habitation_name: str
    relocation_site_id: str
    relocation_site_name: str
    hazard_score: float
    vulnerability_score: float
    disaster_history_score: float
    final_priority_score: float
    priority_level: str
    recommended_families: int
    risk_reduction_percent: float
    explanation: str
    status: str
    created_at: str

    class Config:
        from_attributes = True

# Field Report Schemas
class FieldReportCreate(BaseModel):
    habitation_id: str
    report_type: str
    description: str = Field(min_length=10)
    image_url: Optional[str] = None
    severity: str = "High"
    latitude: float
    longitude: float

class FieldReportResponse(BaseModel):
    id: str
    habitation_id: str
    habitation_name: str
    officer_id: str
    officer_name: str
    report_type: str
    description: str
    image_url: Optional[str] = None
    reported_at: str
    verified: bool
    severity: str
    latitude: float
    longitude: float

    class Config:
        from_attributes = True

# Simulator Schemas
class SimulationRequest(BaseModel):
    habitation_id: str
    relocation_site_id: str
    families_count: int = Field(gt=0, description="Must be a positive number of families")

class SimulationResponse(BaseModel):
    habitation_id: str
    habitation_name: str
    target_site_id: str
    target_site_name: str
    families_relocated: int
    is_capacity_sufficient: bool
    risk_reduction_percent: float
    initial_site_capacity: int
    remaining_capacity_after: int
    water_capacity_status: str
    school_capacity_status: str
    hospital_access_status: str
    road_access_status: str
    bottleneck_factor: str
    explanation: str
    alternative_site: Optional[Dict[str, Any]] = None

# Priority Recalculation Request
class PriorityCalculateRequest(BaseModel):
    habitation_id: str
    landslide_risk: Optional[float] = Field(None, ge=0, le=100)
    flood_risk: Optional[float] = Field(None, ge=0, le=100)
    extreme_rainfall_risk: Optional[float] = Field(None, ge=0, le=100)
    road_access_score: Optional[float] = Field(None, ge=0, le=100)

# Admin Upload Schema
class AdminHazardUploadRequest(BaseModel):
    source_name: str
    hazard_data_format: str # GeoJSON, CSV, Shapefile
    payload: Dict[str, Any]
    update_notes: Optional[str] = None


# -------------------- Evacuation Routing --------------------
class EvacuationOrigin(BaseModel):
    type: Literal["habitation", "alert", "event", "map_click"]
    id: Optional[str] = None
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lng: Optional[float] = Field(None, ge=-180, le=180)


class EvacuationPlanRequest(BaseModel):
    origin: EvacuationOrigin
    families_count: Optional[int] = Field(None, gt=0, le=50000)
    dest_site_id: Optional[str] = None


class RouteCandidateSummary(BaseModel):
    site_id: str
    site_name: str
    site_score: Optional[float] = None
    route_status: Optional[str] = None
    distance_km: Optional[float] = None
    safety_score: Optional[float] = None
    final_score: Optional[float] = None
    reason: Optional[str] = None
    exclusion_reason: Optional[str] = None


class RoutePlanResponse(BaseModel):
    route_id: Optional[str] = None
    route_status: str
    origin: Dict[str, Any]
    destination: Optional[Dict[str, Any]] = None
    families_count: int
    selected_site_reason: str
    route_geometry: Optional[Dict[str, Any]] = None
    distance_km: Optional[float] = None
    travel_time_min: Optional[float] = None
    safety_score: Optional[int] = None
    risk_score: Optional[int] = None
    hazards_encountered: Optional[List[Dict[str, Any]]] = None
    hazards_avoided: Optional[List[Dict[str, Any]]] = None
    blocked_segments: Optional[List[Dict[str, Any]]] = None
    waypoints: Optional[List[str]] = None
    route_reason: Optional[str] = None
    shortest: Optional[Dict[str, Any]] = None
    candidates: Optional[List[Dict[str, Any]]] = None
    all_candidates: Optional[List[Dict[str, Any]]] = None
    warnings: Optional[List[str]] = None
    computed_at: Optional[str] = None
    verified_at: Optional[str] = None
    data_sources: Optional[List[Dict[str, str]]] = None
    is_synthetic_route: bool = True
    payload_version: str = "v1"


class RouteConfirmRequest(BaseModel):
    decision: str = "confirmed"
    notes: Optional[str] = None


# -------------------- Flood Forecast & Data Status --------------------
class FloodGaugeResponse(BaseModel):
    gauge_id: str
    gauge_name: str
    river: str
    latitude: float
    longitude: float
    current_level_m: float
    warning_level_m: float
    danger_level_m: float
    risk_level: str
    affected_edges: Optional[List[str]] = None
    inundation_zone: Optional[Dict[str, Any]] = None
    data_source: Optional[str] = None
    data_status: Optional[str] = None
    computed_at: Optional[str] = None


class FloodZoneResponse(BaseModel):
    zone_id: str
    gauge_id: str
    gauge_name: str
    river: str
    risk_level: str
    geometry: Dict[str, Any]


class FloodForecastDetail(BaseModel):
    """Honest CEMS GloFAS reading for the nearest grid cell in the region.

    Only present (data_status=FORECAST) when the configured NetCDF dataset was
    read successfully. Discharge/threshold are forecast-model values (m³/s);
    lead_time_hours/issue_time/valid_time describe the forecast horizon and are
    null when the dataset time axis cannot be decoded — never fabricated.
    """
    latitude: float
    longitude: float
    river_discharge_m3s: Optional[float] = None
    threshold_m3s: Optional[float] = None
    discharge_band: Optional[str] = None
    lead_time_hours: Optional[int] = None
    issue_time: Optional[str] = None
    valid_time: Optional[str] = None
    forecast_hours: Optional[int] = None
    dataset: Optional[str] = None
    assumption: Optional[str] = None


class FloodForecastResponse(BaseModel):
    gauges: List[FloodGaugeResponse]
    zones: List[FloodZoneResponse]
    data_status: str
    data_source: str
    computed_at: str
    forecast: Optional[FloodForecastDetail] = None


class DataStatusEntryResponse(BaseModel):
    layer: str
    status: str
    source: str
    updated_at: Optional[str] = None
    # Provenance fields (honest, per layer): version of the dataset/provider,
    # optional retrieval window/validity and measured latency (null when not
    # applicable to a config-level status panel), spatial resolution.
    version: Optional[str] = None
    retrieved_at: Optional[str] = None
    valid_time: Optional[str] = None
    latency_ms: Optional[float] = None
    spatial_resolution: Optional[str] = None


class ProviderStatusResponse(BaseModel):
    """Honest per-provider status for the official Historical Data sources.

    Every field is optional so the response degrades gracefully and older
    clients that only read ``DataStatusResponse.layers`` keep working unchanged.
    """

    provider: str
    status: str
    source: str
    available: bool = False
    cached: bool = False
    last_updated: Optional[str] = None
    period: Optional[str] = None
    error: Optional[str] = None
    coverage: Optional[str] = None


class DataStatusResponse(BaseModel):
    layers: List[DataStatusEntryResponse]
    checked_at: str
    # Additive: per-provider breakdown of the official historical sources
    # (ERA5 / IMD / India-WRIS / KSDMA). Optional so existing consumers of
    # `layers` are unaffected.
    providers: Optional[List[ProviderStatusResponse]] = None


class DataCatalogEntryResponse(BaseModel):
    key: str
    title: str
    kind: str
    source: str
    source_url: str
    license: str
    cadence: str
    status: str
    spatial_resolution: Optional[str] = None
    used_at: Optional[str] = None
    notes: Optional[str] = None


class DataCatalogProviderResponse(BaseModel):
    key: str
    kind: str = "live"
    enabled: bool = False
    endpoint: Optional[str] = None


class DataCatalogResponse(BaseModel):
    catalog_generated_at: str
    count: int
    entries: List[DataCatalogEntryResponse]
    live_weather_enabled: bool = False
    provider_summary: Optional[List[DataCatalogProviderResponse]] = None
    table_row_counts: Optional[Dict[str, int]] = None


# ---------------- Historical (Previous-Year) Data ----------------
# Every response carries an explicit status: "HISTORICAL" when a verified
# dataset has been imported for the district/year, otherwise "NOT CONFIGURED".
# These payloads describe provenance data only — they are never labelled LIVE.

class HistoricalQualityResponse(BaseModel):
    grade: str = "INSUFFICIENT"
    coverage_percent: float = 0.0
    reason: str


class HistoricalObservationResponse(BaseModel):
    district_id: int
    district: str
    observation_date: str
    hazard_type: str = "rainfall"
    rainfall_mm: float
    source: str
    source_reference: str = ""
    data_year: int
    status: str = "HISTORICAL"


class HistoricalDistrictSummaryResponse(BaseModel):
    district_id: int
    district: str
    data_year: Optional[int] = None
    observation_count: int = 0
    average_rainfall_mm: float = 0.0
    max_rainfall_mm: float = 0.0
    source: Optional[str] = None
    status: str = "NOT CONFIGURED"
    quality_grade: Optional[str] = None
    latest_observations: List[HistoricalObservationResponse] = []


class HistoricalBaselineResponse(BaseModel):
    district_id: int
    district: str
    data_year: int
    total_rainfall_mm: Optional[float] = None
    average_rainfall_mm: Optional[float] = None
    max_rainfall_mm: Optional[float] = None
    min_rainfall_mm: Optional[float] = None
    observation_count: int = 0
    date_range: Optional[Dict[str, Optional[str]]] = None
    median_rainfall_mm: Optional[float] = None
    p90_rainfall_mm: Optional[float] = None
    p95_rainfall_mm: Optional[float] = None
    quality: HistoricalQualityResponse
    source: Optional[str] = None
    source_reference: Optional[str] = None
    status: str = "NOT CONFIGURED"
    live_data_status: str = "NOT CONFIGURED"


class HistoricalAvailabilityResponse(BaseModel):
    state: Dict[str, Any]
    dataset_year: int
    years_available: List[int] = []
    total_records: int = 0
    districts: List[Dict[str, Any]] = []
    last_import_at: Optional[str] = None
    live_data_status: str = "NOT CONFIGURED"
    status: str = "NOT CONFIGURED"


class HistoricalCompareResponse(BaseModel):
    district_id: Optional[int] = None
    district: Optional[str] = None
    observation_date: Optional[str] = None
    rainfall_mm: Optional[float] = None
    hazard_type: str = "rainfall"
    source: Optional[str] = None
    baseline_average: Optional[float] = None
    anomaly_mm: Optional[float] = None
    percent_difference: Optional[float] = None
    severity: str = "NORMAL"
    baseline_status: str = "NOT CONFIGURED"
    live_data_status: str = "NOT CONFIGURED"


# ==================== SAFE_MOVE_AI LIVE-INTELLIGENCE API ====================
# Points, per the platform spec: responses must never present absent data as
# real. All of the payload shapes below carry explicit data_status.

class WeatherCurrent(BaseModel):
    temperature_c: Optional[float] = None
    relative_humidity_percent: Optional[float] = None
    precipitation_mm: Optional[float] = None
    rain_intensity: Optional[str] = None
    weather_code: Optional[int] = None
    weather_description: Optional[str] = None
    wind_speed_kmh: Optional[float] = None
    wind_gusts_kmh: Optional[float] = None
    pressure_hpa: Optional[float] = None
    cloud_cover_percent: Optional[float] = None
    wind_direction_deg: Optional[float] = None
    apparent_temperature_c: Optional[float] = None
    dewpoint_c: Optional[float] = None
    uv_index: Optional[float] = None
    visibility_km: Optional[float] = None


class WeatherHour(BaseModel):
    time: str
    temperature_c: Optional[float] = None
    precipitation_mm: Optional[float] = None
    precipitation_probability_percent: Optional[int] = None
    weather_code: Optional[int] = None
    weather_description: Optional[str] = None
    wind_speed_kmh: Optional[float] = None
    wind_gusts_kmh: Optional[float] = None
    relative_humidity_percent: Optional[float] = None
    cloud_cover_percent: Optional[float] = None


class WeatherForecastDay(BaseModel):
    date: str
    max_temp_c: Optional[float] = None
    min_temp_c: Optional[float] = None
    precipitation_mm: Optional[float] = None
    precipitation_probability_percent: Optional[int] = None
    wind_speed_kmh: Optional[float] = None
    weather_code: Optional[int] = None
    weather_description: Optional[str] = None


class WeatherResponse(BaseModel):
    latitude: float
    longitude: float
    data_status: str = "UNAVAILABLE"
    data_source: str
    provider: Optional[str] = None            # Open-Meteo | ECMWF | IMD
    provider_role: Optional[str] = None       # primary | backup | legacy
    dataset: Optional[str] = None             # exact upstream dataset that served
    fetched_at: Optional[str] = None          # UTC instant the response was built
    model: Optional[str] = None               # e.g. gfs_seamless / ecmwf_ifs04
    generationtime_ms: Optional[float] = None
    elevation_actual: Optional[float] = None  # true grid elevation, never invented
    observed_at: Optional[str] = None
    current: Optional[WeatherCurrent] = None
    hourly: List[WeatherHour] = []
    forecast: List[WeatherForecastDay] = []
    units: Dict[str, Any] = {}
    timezone: Optional[str] = None
    reason: Optional[str] = None


class WeatherGridPoint(BaseModel):
    latitude: float
    longitude: float
    value: Optional[float] = None
    data_status: Optional[str] = None
    provider: Optional[str] = None
    provider_role: Optional[str] = None
    reason: Optional[str] = None


class WeatherGridResponse(BaseModel):
    data_status: str = "UNAVAILABLE"
    data_source: str
    provider: Optional[str] = None
    provider_role: Optional[str] = None
    model: Optional[str] = None
    variable: str               # temperature_2m | precipitation | ...
    day: int                    # 0 = current conditions, 1..7 forecast day
    hour: Optional[int] = None  # intraday hour offset from now (0..47); None = day mode
    unit: Optional[str] = None
    bounds: Dict[str, float]    # north/south/east/west (clamped to India)
    steps: Dict[str, float]     # latitude/longitude grid spacing
    resolution: Dict[str, float] = {"latitude": 0.0, "longitude": 0.0}
    valid_time: Optional[str] = None   # provider timestamp the grid actually covers
    min: Optional[float] = None        # min over cells with a value (never fabricated)
    max: Optional[float] = None        # max over cells with a value (never fabricated)
    derived: bool = False              # True for computed layers (wind_u/wind_v)
    points: List[WeatherGridPoint] = []
    computed_at: Optional[str] = None
    generated_at: Optional[str] = None
    assumption: Optional[str] = None
    reason: Optional[str] = None
    # --- Historical (ERA5 archive) provenance fields (live grids leave these None) ---
    year: Optional[int] = None
    month: Optional[int] = None
    is_historical: Optional[bool] = None
    data_provenance: Optional[Dict[str, Any]] = None


class HistoricalVariableValue(BaseModel):
    """One historical monthly metric (ERA5 archive). `available=False` + a reason
    is the honest state when the archive does not expose a variable (humidity,
    cloud cover, ...) — never a fabricated substitute."""

    value: Optional[float] = None
    unit: Optional[str] = None
    aggregation: Optional[str] = None  # monthly_total | monthly_mean | monthly_mean_of_daily_max | days | ...
    available: bool = True
    reason: Optional[str] = None


class HistoricalDailyRow(BaseModel):
    date: str
    temperature_2m_max: Optional[float] = None
    temperature_2m_min: Optional[float] = None
    temperature_2m_mean: Optional[float] = None
    precipitation_mm: Optional[float] = None
    weather_code: Optional[int] = None
    wind_speed_10m_max: Optional[float] = None
    wind_gusts_10m_max: Optional[float] = None
    surface_pressure_mean: Optional[float] = None
    wind_direction_10m_dominant: Optional[float] = None


class HistoricalWeatherResponse(BaseModel):
    latitude: float
    longitude: float
    data_status: str = "HISTORICAL"
    data_source: str
    provider: Optional[str] = None
    provider_role: Optional[str] = "historical"
    dataset: Optional[str] = None
    is_historical: bool = True
    year: int
    month: int
    period: Optional[str] = None
    variables: Dict[str, HistoricalVariableValue] = {}
    top_rain_day: Optional[Dict[str, Any]] = None
    daily: List[HistoricalDailyRow] = []
    computed_at: Optional[str] = None
    reason: Optional[str] = None


class HistoricalWeatherYearsResponse(BaseModel):
    availability: List[Dict[str, Any]]
    current_year: int
    completed_through_month: Optional[int] = None
    provider: Dict[str, Any] = {}
    provenance: str


class TerrainResponse(BaseModel):
    latitude: float
    longitude: float
    data_status: str = "UNAVAILABLE"
    data_source: Optional[str] = None
    provider: Optional[str] = None            # nasa | open-meteo
    provider_role: Optional[str] = None       # primary | fallback
    dataset: Optional[str] = None
    elevation_m: Optional[float] = None
    slope_percent: Optional[float] = None
    slope_degrees: Optional[float] = None
    slope_category: Optional[str] = None
    elevation_change_m: Optional[float] = None
    slope_window_arcsec: Optional[int] = None
    sample_radius_km: Optional[float] = None
    sample_count: Optional[int] = None
    computed_at: Optional[str] = None
    reason: Optional[str] = None


class TerrainGridPoint(BaseModel):
    latitude: float
    longitude: float
    elevation_m: Optional[float] = None
    slope_percent: Optional[float] = None
    slope_category: Optional[str] = None
    data_status: Optional[str] = None
    data_source: Optional[str] = None
    provider: Optional[str] = None
    reason: Optional[str] = None


class TerrainGridResponse(BaseModel):
    data_status: str = "UNAVAILABLE"
    data_source: Optional[str] = None
    valid_time: Optional[str] = None
    reason: Optional[str] = None
    points: List[TerrainGridPoint] = []


class FloodRiskGridPoint(BaseModel):
    latitude: float
    longitude: float
    risk_score: Optional[float] = None
    risk_level: Optional[str] = None   # LOW | MODERATE | HIGH | EXTREME
    contributing_factors: List[str] = []
    data_status: Optional[str] = None
    reason: Optional[str] = None


class FloodRiskGridResponse(BaseModel):
    data_status: str = "UNAVAILABLE"
    data_source: str
    weights: Dict[str, float] = {}
    valid_time: Optional[str] = None
    reason: Optional[str] = None
    points: List[FloodRiskGridPoint] = []


class FloodRiskResponse(BaseModel):
    latitude: float
    longitude: float
    data_status: str = "NOT_CONFIGURED"
    data_source: str
    river_discharge_m3s: Optional[float] = None
    threshold_m3s: Optional[float] = None
    discharge_band: Optional[str] = None
    lead_time_hours: Optional[int] = None
    issue_time: Optional[str] = None
    valid_time: Optional[str] = None
    forecast_hours: Optional[int] = None
    dataset: Optional[str] = None
    computed_at: Optional[str] = None
    assumption: Optional[str] = None
    reason: Optional[str] = None


class RainfallResponse(BaseModel):
    latitude: float
    longitude: float
    data_status: str = "NOT_CONFIGURED"
    data_source: str
    precipitation_mm_hour: Optional[float] = None
    dataset: Optional[str] = None
    tile_time: Optional[str] = None
    computed_at: Optional[str] = None
    assumption: Optional[str] = None
    reason: Optional[str] = None


class RainfallGridPoint(BaseModel):
    latitude: float
    longitude: float
    precipitation_mm_hour: Optional[float] = None


class RainfallGridResponse(BaseModel):
    data_status: str = "NOT_CONFIGURED"
    data_source: str
    dataset: Optional[str] = None
    tile_time: Optional[str] = None
    computed_at: Optional[str] = None
    bounds: Dict[str, float]
    points: List[RainfallGridPoint] = []
    assumption: Optional[str] = None
    reason: Optional[str] = None


class NearbyPlace(BaseModel):
    osm_id: Optional[int] = None
    osm_type: Optional[str] = None
    kind: str
    label: str
    name: str
    amenity: Optional[str] = None
    operator: Optional[str] = None
    latitude: float
    longitude: float
    distance_km: float


class NearbyPlacesResponse(BaseModel):
    kind: str
    label: str
    center: Dict[str, float]
    radius_km: float
    data_status: str = "UNAVAILABLE"
    data_source: str
    count: int = 0
    places: List[NearbyPlace] = []
    reason: Optional[str] = None


class GeocodeResult(BaseModel):
    place_id: Optional[int] = None
    display_name: Optional[str] = None
    latitude: float
    longitude: float
    type: Optional[str] = None
    category: Optional[str] = None
    address: Dict[str, Any] = {}


class GeocodeResponse(BaseModel):
    query: str
    data_status: str = "UNAVAILABLE"
    data_source: str
    count: int = 0
    places: List[GeocodeResult] = []
    reason: Optional[str] = None


class SafeRouteOption(BaseModel):
    data_status: str
    data_source: str
    distance_km: Optional[float] = None
    travel_time_min: Optional[float] = None
    safety_score: Optional[int] = None
    risk_score: Optional[int] = None
    route_geometry: Optional[Dict[str, Any]] = None
    hazards_encountered: Optional[List[Dict[str, Any]]] = None
    is_synthetic_route: Optional[bool] = None
    assumption: Optional[str] = None


class SafeRoutesResponse(BaseModel):
    data_status: str
    data_source: str
    origin: List[float]
    destination: List[float]
    routing_provider: Optional[str] = None
    options: List[SafeRouteOption] = []
    reason: Optional[str] = None


class DisasterEventResponse(BaseModel):
    id: int
    name: str
    hazard_type: str
    event_date: str
    state: str
    district: Optional[str] = None
    latitude: float
    longitude: float
    severity_level: Optional[str] = None
    affected_population: Optional[int] = None
    fatalities: Optional[int] = None
    damage_estimate_inr_crore: Optional[float] = None
    description: Optional[str] = None
    source: str
    source_reference: str
    data_status: str = "HISTORICAL"
    distance_km: Optional[float] = None


class DisasterEventsResponse(BaseModel):
    data_status: str = "HISTORICAL"
    total: int = 0
    center: Optional[Dict[str, float]] = None
    radius_km: Optional[float] = None
    events: List[DisasterEventResponse] = []


# ==================== RISK ASSESSMENT + RED ZONES + SAFE LOCATIONS ==========

class AssessmentSource(BaseModel):
    name: str
    status: str = "UNAVAILABLE"
    reference: Optional[str] = None
    updated_at: Optional[str] = None


class RiskFactor(BaseModel):
    key: str
    label: str
    score: Optional[float] = None          # 0-100 contribution before weighting
    weight: float = 0.0
    impact: str = "NOT_ATTRIBUTABLE"       # ATTRIBUTABLE | NOT_ATTRIBUTABLE | NOT_AVAILABLE
    detail: Optional[str] = None
    source: Optional[AssessmentSource] = None


class RiskAssessmentResponse(BaseModel):
    latitude: float
    longitude: float
    place_label: Optional[str] = None
    state: Optional[str] = None
    district: Optional[str] = None
    village: Optional[str] = None
    risk_score: Optional[float] = None      # None when no signals were available
    risk_band: str = "UNKNOWN"              # LOW | MEDIUM | HIGH | CRITICAL | UNKNOWN
    risk_level: str = "UNKNOWN"
    assessment_mode: str = "rule_based"
    model_version: Optional[str] = None
    model_status: Optional[str] = None
    prediction_timestamp: Optional[str] = None
    input_data_timestamp: Optional[str] = None
    factors: List[RiskFactor] = []
    sources: List[AssessmentSource] = []
    disaster_type: Optional[str] = None     # FLOOD | LANDSLIDE | CYCLONE | COASTAL_FLOOD
    computed_at: str
    caveat: str = (
        "Predictive scores are model-based susceptibility estimates for "
        "decision support and are never official notifications."
    )


class RiskZone(BaseModel):
    id: str
    latitude: float
    longitude: float
    label: str
    risk_score: Optional[float] = None
    risk_band: str = "UNKNOWN"
    risk_level: str = "UNKNOWN"
    assessment_mode: str = "rule_based"
    assessment_label: str = "AI-Assessed High-Risk Zone"
    hazards: List[str] = []
    population_estimate: Optional[int] = None
    computed_at: str


class RiskZonesResponse(BaseModel):
    granularity: str = "habitations"
    data_status: str = "LIVE"
    assessment_mode: str = "rule_based"
    assessment_label: str = "AI-Assessed High-Risk Zone"
    zones: List[RiskZone] = []
    computed_at: str


class SafeLocation(BaseModel):
    id: str
    name: str
    kind: str = "facility"                  # relocation_site | school | college | facility
    latitude: float
    longitude: float
    distance_km: float
    capacity_families: Optional[int] = None
    current_occupancy_families: Optional[int] = None
    available_capacity_families: Optional[int] = None
    suitability_score: Optional[float] = None
    site_score: Optional[float] = None
    risk_band: Optional[str] = None
    features: List[str] = []
    data_grade: str = "ESTIMATE"            # REAL | ESTIMATE
    data_source: str
    reason: Optional[str] = None
    # Shelter/facility attributes (Phase 6) — None when the upstream record has no info
    toilets: Optional[int] = None
    drinking_water: Optional[bool] = None
    electricity: Optional[bool] = None
    medical_facility: Optional[bool] = None
    accessibility: Optional[str] = None
    contact: Optional[str] = None
    verified: Optional[bool] = None
    last_verified: Optional[str] = None


class SafeLocationsResponse(BaseModel):
    center: Dict[str, float]
    affected_population: int = 0
    units: int = 0
    data_status: str = "LIVE"
    excluded_status: Optional[List[str]] = None
    locations: List[SafeLocation] = []
    computed_at: str


class RecalculateRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    place_label: Optional[str] = None
    state: Optional[str] = None
    district: Optional[str] = None
    village: Optional[str] = None


# ==================== BHUVAN / ISRO (India geospatial layer) ==============
# Supporting layer over the official Bhuvan v2 REST APIs. Payloads always carry
# the explicit data vocabulary: AVAILABLE | CACHED | UNAVAILABLE | ERROR |
# LOCATION_MISMATCH. Static/historical data is annotated, never labelled LIVE.

class BhuvanVillageRecord(BaseModel):
    name: Optional[str] = None
    census_village_code: Optional[str] = None
    district: Optional[str] = None
    sub_district: Optional[str] = None
    households: Optional[str] = None


class BhuvanVillageGeocodeResponse(BaseModel):
    source: str = "Bhuvan / ISRO"
    service: str = "village_geocode"
    data_status: str = "UNAVAILABLE"
    data_source: str
    dataset_year: Optional[str] = None
    query: Dict[str, Any] = {}
    record: Optional[BhuvanVillageRecord] = None
    has_coordinates: bool = False
    coordinate_note: Optional[str] = None
    coverage_note: Optional[str] = None
    reason: Optional[str] = None
    computed_at: Optional[str] = None


class BhuvanReverseGeocodeResponse(BaseModel):
    source: str = "Bhuvan / ISRO"
    service: str = "reverse_geocode"
    data_status: str = "UNAVAILABLE"
    data_source: str
    villages: List[str] = []
    reverse_latitude: Optional[float] = None
    reverse_longitude: Optional[float] = None
    coverage_note: Optional[str] = None
    reason: Optional[str] = None
    computed_at: Optional[str] = None


class BhuvanHospital(BaseModel):
    name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    distance_m: Optional[float] = None
    type: Optional[str] = None


class BhuvanHospitalsResponse(BaseModel):
    source: str = "Bhuvan / ISRO"
    service: str = "hospitals"
    data_status: str = "UNAVAILABLE"
    data_source: str
    center: Dict[str, float] = {}
    buffer_m: int = 0
    count: int = 0
    hospitals: List[BhuvanHospital] = []
    coverage_note: Optional[str] = None
    reason: Optional[str] = None
    computed_at: Optional[str] = None


class BhuvanLulcResponse(BaseModel):
    source: str = "Bhuvan / ISRO"
    service: str = "lulc"
    data_status: str = "UNAVAILABLE"
    data_source: str
    dataset_year: Optional[str] = None
    year: Optional[str] = None
    class_: Optional[str] = Field(None, alias="class", serialization_alias="class")
    classes: Optional[Dict[str, Any]] = None
    stats: Optional[Dict[str, Any]] = None
    area: Optional[float] = None
    percent: Optional[float] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    state_abbr: Optional[str] = None
    district_code: Optional[str] = None
    reason: Optional[str] = None
    computed_at: Optional[str] = None


class BhuvanShortestPathRequest(BaseModel):
    lat1: float = Field(ge=-90, le=90)
    lon1: float = Field(ge=-180, le=180)
    lat2: float = Field(ge=-90, le=90)
    lon2: float = Field(ge=-180, le=180)


class BhuvanShortestPathResponse(BaseModel):
    source: str = "Bhuvan / ISRO"
    service: str = "shortest_path"
    data_status: str = "UNAVAILABLE"
    data_source: str
    origin: List[float] = []
    destination: List[float] = []
    geometry: Optional[Dict[str, Any]] = None
    distance_km: Optional[float] = None
    coverage_note: Optional[str] = None
    reason: Optional[str] = None
    computed_at: Optional[str] = None


class BhuvanGeoidResponse(BaseModel):
    source: str = "Bhuvan / ISRO"
    service: str = "geoid_tile_proxy"
    data_status: str = "UNAVAILABLE"
    data_source: str
    tile_id: Optional[str] = None
    datum: Optional[str] = None
    proxy: bool = True
    download_endpoint: Optional[str] = None
    note: Optional[str] = None
    height_note: Optional[str] = None
    reason: Optional[str] = None
    computed_at: Optional[str] = None
