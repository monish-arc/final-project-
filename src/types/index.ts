export type UserRole =
  | 'normal_citizen'
  | 'field_officer'
  | 'local_office'
  | 'sub_district_officer'
  | 'district_officer'
  | 'state_officer'
  | 'gis_analysis_officer'
  | 'admin';

export interface AdministrativeScope {
  state_id: string;
  district_id: string;
  sub_district_id: string;
  area_id: string;
}

export interface RegionState {
  code: number;
  name: string;
}

export interface RegionDistrict {
  code: number;
  name: string;
}

export interface RegionSubDistrict {
  code: number;
  name: string;
}

export interface RegionBlock {
  code: number;
  name: string;
}

export type RegionPlace = [code: number, name: string];

export interface RegionSelection {
  state: RegionState | null;
  district: RegionDistrict | null;
  subDistrict: RegionSubDistrict | null;
  place: RegionPlace | null;
}

export type { RegionViewportFocus } from '../lib/regionViewport';

export interface User {
  id: string;
  username: string;
  email: string;
  role: UserRole;
  full_name: string;
  designation?: string;
  department?: string;
  district?: string;
  assignment?: AdministrativeScope;
}

export type PriorityLevel = 
  | 'Immediate Relocation' 
  | 'Short-Term Relocation' 
  | 'Medium-Term Relocation' 
  | 'Monitor Only';

export interface PriorityCalculationResult {
  habitation_id?: string;
  village_name?: string;
  hazard_score: number;
  vulnerability_score: number;
  disaster_history_score?: number;
  priority_score: number;
  priority_level: PriorityLevel;
  updated?: boolean;
}

export type HazardType = 
  | 'Landslide' 
  | 'Flash Flood' 
  | 'Land Subsidence' 
  | 'Cloudburst' 
  | 'Avalanche' 
  | 'Rockfall' 
  | 'Multi-Hazard'
  | 'Extreme Rainfall';

export type SeverityLevel = 'Low' | 'Medium' | 'High' | 'Critical';

export interface Habitation {
  id: string;
  village_code: string;
  village_name: string;
  district: string;
  state: string;
  population: number;
  households: number;
  children_count: number;
  elderly_count: number;
  hospital_distance_km: number;
  road_access_score: number; // 0 to 100 (100 = excellent, low = poor)
  vulnerability_score: number; // 0 to 100
  hazard_score: number; // 0 to 100
  priority_score: number; // 0 to 100
  priority_level: PriorityLevel;
  latitude: number;
  longitude: number;
  landslide_risk: number; // 0 to 100
  flood_risk: number; // 0 to 100
  extreme_rainfall_risk: number; // 0 to 100
  past_disaster_frequency: number; // past disaster score 0 to 100
  disaster_history_count: number;
  notes?: string;
  // Dynamic (OSM-derived) habitations carry no curated risk scores. These
  // provenance markers let the UI label the layer honestly.
  is_dynamic_osm?: boolean;
  source?: string;
  data_status?: string;
}

export interface HazardEvent {
  id: string;
  habitation_id: string;
  habitation_name: string;
  hazard_type: HazardType;
  event_date: string;
  intensity: string;
  severity_level: SeverityLevel;
  affected_people: number;
  houses_damaged: number;
  deaths: number;
  source_url: string;
}

export interface RedZone {
  id: string;
  zone_name: string;
  hazard_type: HazardType;
  risk_level: SeverityLevel;
  hazard_score: number;
  zone_geometry: {
    type: 'Polygon' | 'MultiPolygon';
    coordinates: number[][][] | number[][][][];
  };
  data_source: string;
  last_updated: string;
}

export interface RelocationSite {
  id: string;
  site_name: string;
  district: string;
  land_area_acres?: number | null;
  estimated_capacity?: number | null; // total families (null = unknown/unverified)
  current_occupancy_families?: number;
  water_score: number; // 0-100
  road_score: number; // 0-100
  school_score: number; // 0-100
  hospital_score: number; // 0-100
  low_hazard_score: number; // 0-100 (100 = very low hazard)
  flat_land_score: number; // 0-100 (100 = flat)
  suitability_score: number; // 0-100
  latitude: number;
  longitude: number;
  // Specific carrying capacity factors (in families)
  land_capacity_families: number;
  water_capacity_families: number;
  school_capacity_families: number;
  health_capacity_families: number;
  road_capacity_families: number;
  final_capacity_families: number; // min of above
  available_capacity_families: number;
  // Phase 6 — survey-based shelter/facility attributes
  drinking_water_available?: boolean | null;
  toilets_available?: number | null;
  electricity_available?: boolean | null;
  medical_facility?: boolean | null;
  accessible_by_road?: boolean | null;
  contact_name?: string | null;
  contact_phone?: string | null;
  verified?: boolean | null;
  last_verified?: string | null;
}

export interface RelocationRecommendation {
  id: string;
  habitation_id: string;
  habitation_name: string;
  relocation_site_id: string;
  relocation_site_name: string;
  hazard_score: number;
  vulnerability_score: number;
  disaster_history_score: number;
  final_priority_score: number;
  priority_level: PriorityLevel;
  recommended_families: number;
  risk_reduction_percent: number;
  explanation: string;
  status: 'Draft' | 'Approved' | 'Under Review' | 'In Progress' | 'Completed';
  created_at: string;
}

export interface FieldReport {
  id: string;
  habitation_id: string;
  habitation_name: string;
  officer_id: string;
  officer_name: string;
  report_type: string;
  description: string;
  image_url: string;
  reported_at: string;
  verified: boolean;
  severity: SeverityLevel;
  latitude: number;
  longitude: number;
}

export interface SimulationRequest {
  habitation_id: string;
  relocation_site_id: string;
  families_count: number;
}

export interface CapacityCheckStatus {
  status: 'Adequate' | 'Near Limit' | 'Exceeded';
  available: number;
  utilized_percent: number;
}

export interface SimulationResult {
  habitation_id?: string;
  habitation_name?: string;
  relocation_site_id?: string;
  relocation_site_name?: string;
  families_requested: number;
  families_relocated?: number;
  risk_reduction_percent: number;
  initial_site_capacity?: number;
  remaining_capacity_after?: number;
  remaining_capacity_after_relocation: number;
  water_capacity_status: string;
  school_capacity_status: string;
  hospital_access_status: string;
  road_access_status: string;
  decision_rationale: string;
  bottleneck_factor?: string;
  explanation?: string;
  is_capacity_sufficient: boolean;
  alternative_site?: RelocationSite;
  alternative_site_recommendation?: string;
}

export interface DashboardSummary {
  total_habitations_monitored: number;
  high_risk_population: number;
  population_exposed?: number;
  households_exposed?: number;
  children_est?: number;
  elderly_est?: number;
  immediate_relocation_villages_count: number;
  available_safe_site_capacity: number;
  total_safe_sites: number;
  verified_field_reports_count: number;
  pending_field_reports_count: number;
  hazard_distribution: {
    hazard_type: string;
    count: number;
    affected_population: number;
  }[];
  relocation_priority_distribution: {
    level: PriorityLevel;
    count: number;
    population: number;
  }[];
  recent_field_reports: FieldReport[];
  top_five_critical_villages: Habitation[];
  pilot_district?: string;
  pilot_state?: string;
  is_synthetic_demo_data?: boolean;
  region?: { state: string | null; district: string | null; is_pilot: boolean; has_curated_data: boolean };
  data_status?: string;
  message?: string;
}

export interface MapLayerItem {
  id: string;
  name: string;
  type: 'hospital' | 'school' | 'evacuation_road';
  latitude: number;
  longitude: number;
  coordinates?: [number, number][];
  capacity_or_type: string;
}

export interface MapLayersResponse {
  red_zones: RedZone[];
  habitations: Habitation[];
  relocation_sites: RelocationSite[];
  infrastructure: MapLayerItem[];
  pilot_center?: { lat: number; lng: number; zoom: number } | null;
  region?: { state: string | null; district: string | null; is_pilot: boolean };
  layers_status?: {
    red_zones: string;
    habitations: string;
    relocation_sites: string;
    infrastructure: string;
  };
  is_synthetic_demo_data?: boolean;
}

export interface HabitationsFetchResult {
  habitations: Habitation[];
  data_status: DataLayerStatus;
  data_source: string;
  count: number;
  reason?: string | null;
}

export type EvacuationOriginType = 'habitation' | 'alert' | 'event' | 'map_click';

export interface EvacuationOriginPayload {
  type: EvacuationOriginType;
  id?: string | null;
  label?: string;
  latitude?: number;
  longitude?: number;
  lat?: number;
  lng?: number;
}

export type RouteStatus =
  | 'SAFE'
  | 'CAUTION'
  | 'NO_ROUTE'
  | 'NO_SAFE_SITE'
  | 'ORIGIN_UNREACHABLE'
  | 'DEST_UNREACHABLE'
  | 'DEST_BECAME_UNSAFE';

export interface EvacuationRouteCandidate {
  site_id: string;
  site_name: string;
  site_score?: number | null;
  route_status?: RouteStatus | null;
  distance_km?: number | null;
  safety_score?: number | null;
  final_score?: number | null;
  reason?: string | null;
  exclusion_reason?: string | null;
}

export interface EvacuationHazard {
  zone_name?: string;
  hazard_type?: string;
  risk_level?: string;
  road?: string;
  status?: string;
  edge_id?: string;
  latitude?: number | null;
  longitude?: number | null;
}

export interface EvacuationBlockedSegment {
  segment_id: string;
  name: string;
  status: string;
  hazard_type: string;
  reason: string;
  geometry?: { type: 'LineString'; coordinates: [number, number][] } | null;
}

export interface EvacuationDestination {
  site_id: string;
  site_name: string;
  latitude: number;
  longitude: number;
  available_capacity_families: number;
  final_capacity_families: number;
  suitability_score: number;
}

export interface EvacuationShortest {
  distance_km: number;
  delta_km?: number;
}

export interface EvacuationPlanResponse {
  route_id?: string | null;
  route_status: RouteStatus;
  status?: string;
  confirmed_at?: string | null;
  origin: EvacuationOriginPayload;
  destination?: EvacuationDestination | null;
  families_count: number;
  selected_site_reason: string;
  route_geometry?: { type: 'LineString'; coordinates: [number, number][] } | null;
  distance_km?: number | null;
  travel_time_min?: number | null;
  safety_score?: number | null;
  risk_score?: number | null;
  hazards_encountered?: EvacuationHazard[] | null;
  hazards_avoided?: EvacuationHazard[] | null;
  blocked_segments?: EvacuationBlockedSegment[] | null;
  waypoints?: EvacuationOriginPayload[] | null;
  route_reason?: string | null;
  shortest?: EvacuationShortest | null;
  candidates?: EvacuationRouteCandidate[] | null;
  all_candidates?: Array<Record<string, unknown>> | null;
  warnings?: string[];
  computed_at?: string;
  verified_at?: string | null;
  data_sources?: Array<{ layer: string; status: string; detail: string }>;
  is_synthetic_route: boolean;
  payload_version?: string;
}

export interface RoadConditionSegment {
  segment_id: string;
  name: string;
  status: 'OPEN' | 'RESTRICTED' | 'CLOSED' | string;
  data_class: string;
  is_synthetic: boolean;
  geometry?: { type: 'LineString'; coordinates: [number, number][] } | null;
}

export interface RoadConditionsResponse {
  road_conditions: Array<Record<string, unknown>>;
  segments: RoadConditionSegment[];
  is_synthetic_demo_data: boolean;
  data_sources: Array<{ layer: string; status: string; detail: string }>;
}

export type FloodRiskLevel = 'LOW' | 'MODERATE' | 'HIGH' | 'EXTREME';
export type DataLayerStatus = 'LIVE' | 'MODEL' | 'CALCULATED' | 'STATIC' | 'FORECAST' | 'DEMO' | 'NOT CONFIGURED' | 'NOT_CONFIGURED' | 'UNAVAILABLE' | 'HISTORICAL' | 'SIMULATED' | 'AVAILABLE' | 'CACHED' | 'RECENT' | 'ERROR' | 'LOCATION_MISMATCH';

// ==================== SAFE_MOVE_AI Live Intelligence ====================
// Payloads mirror the backend /api/weather|terrain|flood-risk|rainfall|nearby|
// geocode|routes/safe|disaster-events|risk-assessment|risk-zones|safe-locations
// contracts. Honesty rule mirrored everywhere: whenever a live provider is not
// reachable/configured the backend returns a clearly-labelled UNAVAILABLE /
// NOT_CONFIGURED payload — the UI renders that label, it never fabricates data.

export interface WeatherCurrent {
  temperature_c: number | null;
  relative_humidity_percent: number | null;
  precipitation_mm: number | null;
  rain_intensity: string | null;
  weather_code: number | null;
  weather_description: string | null;
  wind_speed_kmh: number | null;
  wind_gusts_kmh: number | null;
  // Extended fields (present on live Open-Meteo/ECMWF payloads; null when the
  // serving provider does not produce them — never fabricated).
  pressure_hpa?: number | null;
  cloud_cover_percent?: number | null;
  wind_direction_deg?: number | null;
  apparent_temperature_c?: number | null;
  dewpoint_c?: number | null;
  uv_index?: number | null;
  visibility_km?: number | null;
}

export interface WeatherHour {
  time: string;
  temperature_c: number | null;
  precipitation_mm: number | null;
  precipitation_probability_percent: number | null;
  weather_code: number | null;
  weather_description: string | null;
  wind_speed_kmh: number | null;
  wind_gusts_kmh: number | null;
  relative_humidity_percent: number | null;
  cloud_cover_percent: number | null;
}

export interface WeatherForecastDay {
  date: string;
  max_temp_c: number | null;
  min_temp_c: number | null;
  precipitation_mm: number | null;
  precipitation_probability_percent: number | null;
  wind_speed_kmh: number | null;
  weather_code?: number | null;
  weather_description?: string | null;
}

export interface WeatherResponse {
  latitude: number;
  longitude: number;
  data_status: DataLayerStatus;
  data_source: string;
  provider?: string | null;            // Open-Meteo | ECMWF | IMD
  provider_role?: 'primary' | 'backup' | 'legacy' | null;
  model?: string | null;
  generationtime_ms?: number | null;
  elevation_actual?: number | null;
  observed_at: string | null;
  current: WeatherCurrent | null;
  hourly?: WeatherHour[];
  forecast: WeatherForecastDay[];
  units?: Record<string, string | null>;
  timezone: string | null;
  reason: string | null;
}

// India-wide weather forecast grid (Weather Forecast map + Weather & Hazard Map).
export type WeatherVariable =
  | 'temperature_2m'
  | 'precipitation'
  | 'precipitation_probability'
  | 'wind_speed_10m'
  | 'wind_gusts_10m'
  | 'cloud_cover'
  | 'precipitation_accumulation'
  | 'storm_indicator'
  | 'relative_humidity'
  | 'pressure_msl'
  | 'wind_direction_10m'
  | 'wind_u'
  | 'wind_v'
  | 'apparent_temperature'
  | 'visibility';

export interface WeatherGridPoint {
  latitude: number;
  longitude: number;
  value: number | null;
  data_status?: DataLayerStatus | string | null;
  provider?: string | null;
  provider_role?: 'primary' | 'backup' | null;
  reason?: string | null;
}

export interface WeatherGridResponse {
  data_status: DataLayerStatus;
  data_source: string;
  provider?: string | null;
  provider_role?: 'primary' | 'backup' | null;
  model?: string | null;
  variable: string;
  day: number;                         // 0 = current conditions; 1..7 forecast day
  hour?: number | null;                // intraday hour offset (0..47); null = day mode
  unit: string | null;
  bounds: { north: number; south: number; east: number; west: number };
  steps: { latitude: number; longitude: number };
  resolution?: { latitude: number; longitude: number };
  valid_time?: string | null;          // provider timestamp the grid actually covers
  min?: number | null;                 // min over cells with a real value
  max?: number | null;                 // max over cells with a real value
  derived?: boolean;                   // true for computed layers (wind_u/wind_v)
  points: WeatherGridPoint[];
  computed_at?: string | null;
  generated_at?: string | null;
  assumption?: string | null;
  reason?: string | null;
  // Historical (ERA5 archive) grid mode — set when the caller asks for a
  // completed past month (year+month). Never mixed with live forecast fields.
  is_historical?: boolean;
  year?: number | null;
  month?: number | null;
  data_provenance?: {
    source?: string;
    dataset?: string | null;
    status?: string;
    year?: number | null;
    month?: number | null;
  } | null;
}

export interface TerrainResponse {
  latitude: number;
  longitude: number;
  data_status: DataLayerStatus;
  data_source: string | null;
  provider?: string | null;
  provider_role?: 'primary' | 'fallback' | null;
  dataset?: string | null;
  elevation_m: number | null;
  slope_percent: number | null;
  slope_degrees?: number | null;
  slope_category: string | null;
  elevation_change_m?: number | null;
  slope_window_arcsec?: number | null;
  sample_radius_km: number | null;
  sample_count: number | null;
  computed_at: string | null;
  reason: string | null;
}

export interface TerrainGridPoint {
  latitude: number;
  longitude: number;
  elevation_m: number | null;
  slope_percent: number | null;
  slope_category?: string | null;
  data_status?: DataLayerStatus | string | null;
  data_source?: string | null;
  provider?: string | null;
  reason?: string | null;
}

export interface TerrainGridResponse {
  data_status: DataLayerStatus;
  data_source: string | null;
  valid_time?: string | null;
  reason?: string | null;
  points: TerrainGridPoint[];
}

// Historical ERA5 (archive) weather — real reanalysis, completed months only.
export interface HistoricalVariableValue {
  variable: string;
  label: string;
  value: number | null;
  unit: string | null;
  aggregation: string;
}

export interface HistoricalDayRow {
  date: string;
  temperature_2m_max: number | null;
  temperature_2m_min: number | null;
  temperature_2m_mean: number | null;
  precipitation_mm: number | null;
  weather_code?: number | null;
  wind_speed_10m_max: number | null;
  wind_gusts_10m_max: number | null;
  surface_pressure_mean?: number | null;
  wind_direction_10m_dominant?: number | null;
}

export interface HistoricalWeatherResponse {
  latitude: number;
  longitude: number;
  data_status: string;                    // HISTORICAL | UNAVAILABLE
  data_source: string;
  provider?: string | null;
  provider_role?: 'historical' | null;
  dataset?: string | null;
  is_historical: boolean;
  year: number;
  month: number;
  period?: string | null;
  variables: Record<string, HistoricalVariableValue>;
  top_rain_day?: Record<string, unknown> | null;
  daily: HistoricalDayRow[];
  computed_at?: string | null;
  reason?: string | null;
}

export interface HistoricalAvailabilitySummary {
  year: number;
  completed_through_month: number;
  status: string;                         // FULL | COMPLETED | UNAVAILABLE …
  label: string;
}

export interface HistoricalWeatherYearsResponse {
  availability: HistoricalAvailabilitySummary[];
  current_year: number;
  completed_through_month: number | null;
  provider?: string | null;
  provenance?: { source?: string; dataset?: string | null } | null;
}

export interface FloodRiskGridPoint {
  latitude: number;
  longitude: number;
  risk_score: number | null;
  risk_level: 'LOW' | 'MODERATE' | 'HIGH' | 'EXTREME' | null;
  contributing_factors: string[];
  data_status?: DataLayerStatus | string | null;
  reason?: string | null;
}

export interface FloodRiskGridResponse {
  data_status: DataLayerStatus;
  data_source: string;
  weights?: Record<string, number>;
  valid_time?: string | null;
  reason?: string | null;
  points: FloodRiskGridPoint[];
}

export interface FloodRiskResponse {
  latitude: number;
  longitude: number;
  data_status: DataLayerStatus;
  data_source: string;
  river_discharge_m3s: number | null;
  threshold_m3s: number | null;
  discharge_band: string | null;
  lead_time_hours: number | null;
  issue_time: string | null;
  valid_time: string | null;
  forecast_hours: number | null;
  dataset: string | null;
  computed_at: string | null;
  assumption: string | null;
  reason: string | null;
}

export interface RainfallResponse {
  latitude: number;
  longitude: number;
  data_status: DataLayerStatus;
  data_source: string;
  precipitation_mm_hour: number | null;
  dataset: string | null;
  tile_time: string | null;
  computed_at: string | null;
  assumption: string | null;
  reason: string | null;
}

export interface RainfallGridPoint {
  latitude: number;
  longitude: number;
  precipitation_mm_hour: number | null;
}

export interface RainfallGridResponse {
  data_status: DataLayerStatus;
  data_source: string;
  dataset: string | null;
  tile_time: string | null;
  computed_at: string | null;
  bounds: Record<string, number>;
  points: RainfallGridPoint[];
  assumption: string | null;
  reason: string | null;
}

export interface NearbyPlace {
  osm_id: number | null;
  osm_type: string | null;
  kind: string;
  label: string;
  name: string;
  amenity: string | null;
  operator: string | null;
  latitude: number;
  longitude: number;
  distance_km: number;
}

export interface NearbyPlacesResponse {
  kind: string;
  label: string;
  center: Record<string, number>;
  radius_km: number;
  data_status: DataLayerStatus;
  data_source: string;
  count: number;
  places: NearbyPlace[];
  reason: string | null;
}

export interface GeocodeResult {
  place_id?: number | null;
  display_name?: string | null;
  latitude: number;
  longitude: number;
  type?: string | null;
  category?: string | null;
  address?: Record<string, unknown>;
}

export interface GeocodeResponse {
  query: string;
  data_status: DataLayerStatus;
  data_source: string;
  count: number;
  places: GeocodeResult[];
  reason: string | null;
}

export interface SafeRouteOption {
  data_status: string;
  data_source: string;
  distance_km: number | null;
  travel_time_min: number | null;
  safety_score: number | null;
  risk_score: number | null;
  route_geometry?: { type: string; coordinates: unknown } | null;
  hazards_encountered?: Array<Record<string, unknown>> | null;
  is_synthetic_route?: boolean | null;
  assumption?: string | null;
}

export interface SafeRoutesResponse {
  data_status: string;
  data_source: string;
  origin: [number, number];
  destination: [number, number];
  routing_provider?: string | null;
  options: SafeRouteOption[];
  reason?: string | null;
}

export interface DisasterEventResponse {
  id: number;
  name: string;
  hazard_type: string;
  event_date: string;
  state: string;
  district: string | null;
  latitude: number;
  longitude: number;
  severity_level: string | null;
  affected_population: number | null;
  fatalities: number | null;
  damage_estimate_inr_crore: number | null;
  description: string | null;
  source: string;
  source_reference: string;
  data_status?: string;
  distance_km?: number | null;
}

export interface DisasterEventsResponse {
  data_status: string;
  total: number;
  center: Record<string, number> | null;
  radius_km: number | null;
  events: DisasterEventResponse[];
}

export interface RiskAlert {
  id: string;
  area_id: string;
  hazard_type: string;
  severity: string;
  description: string;
  latitude: number;
  longitude: number;
  status: string;
  reported_by?: string;
  reported_by_name?: string;
  reported_at?: string;
}

export interface AssessmentSource {
  name: string;
  status: string;
  reference?: string | null;
  updated_at?: string | null;
}

export interface RiskFactor {
  key: string;
  label: string;
  score: number | null;
  weight: number;
  impact: string;
  detail: string | null;
  source?: AssessmentSource | null;
}

export type RiskBand = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' | 'UNKNOWN';

export interface RiskAssessmentResponse {
  latitude: number;
  longitude: number;
  place_label: string | null;
  state: string | null;
  district: string | null;
  village: string | null;
  risk_score: number | null;
  risk_band: RiskBand;
  risk_level: string;
  assessment_mode: string;
  model_version?: string | null;
  model_status?: string | null;
  prediction_timestamp?: string | null;
  input_data_timestamp?: string | null;
  factors: RiskFactor[];
  sources: AssessmentSource[];
  disaster_type: string | null;
  computed_at: string;
  caveat: string;
}

export interface RiskZone {
  id: string;
  latitude: number;
  longitude: number;
  label: string;
  risk_score: number | null;
  risk_band: RiskBand;
  risk_level: string;
  assessment_mode: string;
  assessment_label: string;
  hazards: string[];
  population_estimate: number | null;
  computed_at: string;
}

export interface RiskZonesResponse {
  granularity: string;
  data_status: DataLayerStatus;
  assessment_mode: string;
  assessment_label: string;
  zones: RiskZone[];
  computed_at: string;
}

export interface SafeLocation {
  id: string;
  name: string;
  kind: string;
  latitude: number;
  longitude: number;
  distance_km: number;
  capacity_families: number | null;
  current_occupancy_families: number | null;
  available_capacity_families: number | null;
  suitability_score: number | null;
  site_score: number | null;
  risk_band: string | null;
  features: string[];
  data_grade: 'REAL' | 'ESTIMATE';
  data_source: string;
  reason: string | null;
  // Phase 6 — shelter/facility attributes (null when the upstream record has no info)
  toilets?: number | null;
  drinking_water?: boolean | null;
  electricity?: boolean | null;
  medical_facility?: boolean | null;
  accessibility?: string | null;
  contact?: string | null;
  verified?: boolean | null;
  last_verified?: string | null;
}

export interface SafeLocationsResponse {
  center: Record<string, number>;
  affected_population: number;
  units: number;
  data_status: DataLayerStatus;
  excluded_status: string[] | null;
  locations: SafeLocation[];
  computed_at: string;
}

export interface FloodGauge {
  gauge_id: string;
  gauge_name: string;
  river: string;
  latitude: number;
  longitude: number;
  current_level_m: number;
  warning_level_m: number;
  danger_level_m: number;
  risk_level: FloodRiskLevel;
  affected_edges?: string[];
  inundation_zone?: { type: 'Polygon'; coordinates: number[][][] };
  data_source?: string;
  data_status?: DataLayerStatus;
  computed_at?: string;
}

export interface FloodZone {
  zone_id: string;
  gauge_id: string;
  gauge_name: string;
  river: string;
  risk_level: FloodRiskLevel;
  geometry: { type: 'Polygon'; coordinates: number[][][] };
}

export interface FloodForecastDetail {
  latitude: number;
  longitude: number;
  river_discharge_m3s: number | null;
  threshold_m3s: number | null;
  discharge_band: string | null;
  lead_time_hours: number | null;
  issue_time: string | null;
  valid_time: string | null;
  forecast_hours: number | null;
  dataset: string | null;
  assumption: string | null;
}

export interface FloodForecastResponse {
  gauges: FloodGauge[];
  zones: FloodZone[];
  data_status: DataLayerStatus;
  data_source: string;
  computed_at: string;
  forecast?: FloodForecastDetail | null;
}

export interface DataStatusEntry {
  layer: string;
  status: DataLayerStatus;
  source: string;
  updated_at?: string;
  version?: string | null;
  retrieved_at?: string | null;
  valid_time?: string | null;
  latency_ms?: number | null;
  spatial_resolution?: string | null;
}

export interface DataStatusResponse {
  layers: DataStatusEntry[];
  checked_at: string;
}

export interface BasemapKey {
  id: 'street' | 'satellite' | 'terrain';
  label: string;
}

// ==================== Historical (Previous-Year) Data ====================
// Payloads mirror the backend /api/historical/* responses.  Every record is
// previous-year provenance labelled "HISTORICAL" or "NOT CONFIGURED" — never
// live telemetry.

export interface HistoricalQuality {
  grade: 'GOOD' | 'LIMITED' | 'INSUFFICIENT';
  coverage_percent: number;
  reason: string;
}

export interface HistoricalObservation {
  district_id: number;
  district: string;
  observation_date: string;
  hazard_type: string;
  rainfall_mm: number;
  source: string;
  source_reference: string;
  data_year: number;
  status: 'HISTORICAL' | 'NOT CONFIGURED';
}

export interface HistoricalDistrictSummary {
  district_id: number;
  district: string;
  data_year: number | null;
  observation_count: number;
  average_rainfall_mm: number;
  max_rainfall_mm: number;
  source: string | null;
  status: 'HISTORICAL' | 'NOT CONFIGURED';
  quality_grade: HistoricalQuality['grade'] | null;
  latest_observations: HistoricalObservation[];
}

export interface HistoricalBaseline {
  district_id: number;
  district: string;
  data_year: number;
  total_rainfall_mm: number | null;
  average_rainfall_mm: number | null;
  max_rainfall_mm: number | null;
  min_rainfall_mm: number | null;
  observation_count: number;
  date_range: { first: string | null; last: string | null } | null;
  median_rainfall_mm: number | null;
  p90_rainfall_mm: number | null;
  p95_rainfall_mm: number | null;
  quality: HistoricalQuality;
  source: string | null;
  source_reference: string | null;
  status: 'HISTORICAL' | 'NOT CONFIGURED';
  live_data_status: 'NOT CONFIGURED' | 'LIVE';
}

export interface HistoricalAvailability {
  state: { code: number; name: string };
  dataset_year: number;
  years_available: number[];
  total_records: number;
  districts: { code: number; name: string; records: number }[];
  last_import_at: string | null;
  live_data_status: 'NOT CONFIGURED' | 'LIVE';
  status: 'HISTORICAL' | 'NOT CONFIGURED';
}

export interface HistoricalCompareResponse {
  district_id: number | null;
  district: string | null;
  observation_date: string | null;
  rainfall_mm: number | null;
  hazard_type: string;
  source: string | null;
  baseline_average: number | null;
  anomaly_mm: number | null;
  percent_difference: number | null;
  severity: 'NORMAL' | 'ELEVATED' | 'HIGH' | 'EXTREME';
  baseline_status: 'HISTORICAL' | 'NOT CONFIGURED';
  live_data_status: 'NOT CONFIGURED' | 'LIVE';
}

// ==================== Bhuvan / ISRO (supporting geospatial layer) ==========
// Official Bhuvan v2 REST APIs proxied server-side. Every payload carries the
// explicit data vocabulary (AVAILABLE | CACHED | UNAVAILABLE | ERROR |
// LOCATION_MISMATCH). Static datasets (census-2001, LULC) are annotated with a
// dataset year and are never labelled LIVE.

export interface BhuvanVillageRecord {
  name?: string | null;
  census_village_code?: string | null;
  district?: string | null;
  sub_district?: string | null;
  households?: string | null;
}

export interface BhuvanVillageGeocodeResponse {
  source: string;
  service: string;
  data_status: DataLayerStatus;
  data_source: string;
  dataset_year?: string | null;
  query: Record<string, unknown>;
  record?: BhuvanVillageRecord | null;
  has_coordinates: boolean;
  coordinate_note?: string | null;
  coverage_note?: string | null;
  reason?: string | null;
  computed_at?: string | null;
}

export interface BhuvanReverseGeocodeResponse {
  source: string;
  service: string;
  data_status: DataLayerStatus;
  data_source: string;
  villages: string[];
  reverse_latitude?: number | null;
  reverse_longitude?: number | null;
  coverage_note?: string | null;
  reason?: string | null;
  computed_at?: string | null;
}

export interface BhuvanHospital {
  name?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  distance_m?: number | null;
  type?: string | null;
}

export interface BhuvanHospitalsResponse {
  source: string;
  service: string;
  data_status: DataLayerStatus;
  data_source: string;
  center: Record<string, number>;
  buffer_m: number;
  count: number;
  hospitals: BhuvanHospital[];
  coverage_note?: string | null;
  reason?: string | null;
  computed_at?: string | null;
}

export interface BhuvanLulcResponse {
  source: string;
  service: string;
  data_status: DataLayerStatus;
  data_source: string;
  dataset_year?: string | null;
  year?: string | null;
  class?: string | null;
  classes?: Record<string, unknown> | null;
  stats?: Record<string, unknown> | null;
  area?: number | null;
  percent?: number | null;
  latitude?: number | null;
  longitude?: number | null;
  state_abbr?: string | null;
  district_code?: string | null;
  reason?: string | null;
  computed_at?: string | null;
}

export interface BhuvanShortestPathResponse {
  source: string;
  service: string;
  data_status: DataLayerStatus;
  data_source: string;
  origin: number[];
  destination: number[];
  geometry?: { type: string; coordinates: unknown[][] } | null;
  distance_km?: number | null;
  coverage_note?: string | null;
  reason?: string | null;
  computed_at?: string | null;
}

export interface BhuvanGeoidResponse {
  source: string;
  service: string;
  data_status: DataLayerStatus;
  data_source: string;
  tile_id?: string | null;
  datum?: string | null;
  proxy: boolean;
  download_endpoint?: string | null;
  note?: string | null;
  height_note?: string | null;
  reason?: string | null;
  computed_at?: string | null;
}
