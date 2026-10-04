import {
  Habitation,
  RelocationSite,
  RelocationRecommendation,
  FieldReport,
  DashboardSummary,
  SimulationResult,
  User,
  PriorityLevel,
  PriorityCalculationResult,
  EvacuationPlanResponse,
  EvacuationOriginPayload,
  RoadConditionsResponse,
  EvacuationRouteCandidate,
  FloodForecastResponse,
  DataStatusResponse,
  HistoricalAvailability,
  HistoricalBaseline,
  HistoricalDistrictSummary,
  HistoricalCompareResponse,
  WeatherResponse,
  WeatherGridResponse,
  WeatherVariable,
  TerrainResponse,
  TerrainGridResponse,
  FloodRiskResponse,
  FloodRiskGridResponse,
  RainfallResponse,
  RainfallGridResponse,
  NearbyPlacesResponse,
  GeocodeResponse,
  SafeRoutesResponse,
  DisasterEventsResponse,
  RiskAssessmentResponse,
  RiskZonesResponse,
  SafeLocationsResponse,
  DataLayerStatus,
  RiskAlert,
  MapLayersResponse,
  HabitationsFetchResult,
  BhuvanVillageGeocodeResponse,
  BhuvanReverseGeocodeResponse,
  BhuvanHospitalsResponse,
  BhuvanLulcResponse,
  BhuvanShortestPathResponse,
  BhuvanGeoidResponse,
  HistoricalWeatherYearsResponse,
  HistoricalWeatherResponse,
} from '../types';
import { clipWeatherGridBounds } from '../lib/weatherBounds';
import {
  INITIAL_HABITATIONS,
  INITIAL_RELOCATION_SITES,
  INITIAL_RED_ZONES,
  INITIAL_HAZARD_EVENTS,
  INITIAL_FIELD_REPORTS,
  INITIAL_RECOMMENDATIONS,
  INFRASTRUCTURE_ITEMS,
  DEMO_USERS,
} from '../data/mockData';
import { apiUrl } from './apiBase';

// ---- weather grid client cache ----
// The map stays cache-first across pans/timeline stops so repeated identical
// grid requests never reach the backend during a single session. Entries are
// keyed by the full request contract (provider, bounds, step, max points,
// variable, day/hour, prefer, forecast time) and expire after 5 minutes so
// stale tiles eventually refresh.
const WEATHER_GRID_CACHE_TTL_MS = 5 * 60 * 1000;
const WEATHER_POINT_TIMEOUT_MS = 12 * 1000;
type WeatherGridCacheEntry = { payload: WeatherGridResponse; expires: number };
const weatherGridCache = new Map<string, WeatherGridCacheEntry>();

function weatherGridCacheKey(c: {
  clipped: string;
  variable: string;
  day: number;
  hour: number | undefined;
  step: number;
  maxPoints: number;
  prefer: string;
  forecastTime: string | undefined;
  year?: number;
  month?: number;
}): string {
  return [
    'weather-grid-v1',
    c.clipped,
    c.variable,
    String(c.day),
    c.hour === undefined ? 'x' : String(c.hour),
    String(c.step),
    String(c.maxPoints),
    c.prefer,
    c.forecastTime || 'x',
    c.year === undefined ? 'x' : String(c.year),
    c.month === undefined ? 'x' : String(c.month),
  ].join('|');
}

export function clearWeatherGridCache(): void {
  weatherGridCache.clear();
}

// ---- request timeout contract ----
// Every backend request the portal depends on must settle within a bounded
// window. A stalled proxy/host must never pin the app's global "Loading"
// state indefinitely: LOADING always transitions to SUCCESS or an honest
// ERROR. The 25s cap is comfortably above any normal backend computation
// while guaranteeing the portal recovers by itself if a request hangs.
// Terrain requests get their own longer ceiling (TERRAIN_REQUEST_TIMEOUT_MS)
// because a cold NASA LP DAAC SRTM tile download can legitimately take
// 15–30s+ on first touch — see the terrain lifecycle section below.
export const API_FETCH_TIMEOUT_MS = 25 * 1000;

/** Raised when `fetchWithTimeout` aborts a request because its own timer
 *  fired — NOT because the caller's AbortSignal was cancelled. Callers can
 *  then label the outcome honestly instead of guessing "backend unreachable"
 *  when the provider was simply slow. */
export class ApiTimeoutError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ApiTimeoutError';
  }
}

export async function fetchWithTimeout(
  url: string,
  init: RequestInit = {},
  ms: number = API_FETCH_TIMEOUT_MS
): Promise<Response> {
  const controller = new AbortController();
  const external = init.signal;
  let didTimeOut = false;
  const onExternalAbort = () => controller.abort();
  if (external) {
    if (external.aborted) controller.abort();
    else external.addEventListener('abort', onExternalAbort);
  }
  const timer = setTimeout(() => {
    didTimeOut = true;
    controller.abort();
  }, ms);
  try {
    try {
      return await fetch(apiUrl(url), { ...init, signal: controller.signal });
    } catch (error) {
      if (didTimeOut && !external?.aborted) {
        throw new ApiTimeoutError(`Request timed out after ${ms} ms`);
      }
      throw error;
    }
  } finally {
    clearTimeout(timer);
    external?.removeEventListener('abort', onExternalAbort);
  }
}

function round5(value: number): number {
  return Math.round(value * 100000) / 100000;
}

// ---- terrain elevation client cache ----
// The Terrain map samples many points; the same elevation is usually needed
// again moments later (pan/zoom). Real SRTM values are persisted server-side,
// so a short TTL here is purely a UX nicety, never a source of staleness.
const TERRAIN_ELEVATION_CACHE_TTL_MS = 10 * 60 * 1000;
type TerrainElevationCacheEntry = { payload: TerrainResponse; expires: number };
const terrainElevationCache = new Map<string, TerrainElevationCacheEntry>();

export function clearTerrainElevationCache(): void {
  terrainElevationCache.clear();
}

// ---- full terrain point client cache ----
// The terrain popup requests a full slope/category payload per map click.
// Caching by rounded coordinates means a second click on the same/nearby
// location renders instantly from the cache (key: "terrain:<lat5>:<lng5>"),
// never repeating the network round-trip. Real SRTM values are persisted
// server-side, so the TTL here is purely a UX nicety.
const TERRAIN_POINT_CACHE_TTL_MS = 10 * 60 * 1000;
type TerrainPointCacheEntry = { payload: TerrainResponse; expires: number };
const terrainPointCache = new Map<string, TerrainPointCacheEntry>();

export function clearTerrainPointCache(): void {
  terrainPointCache.clear();
}

function terrainPointCacheKey(latitude: number, longitude: number): string {
  return `terrain:${round5(latitude)}:${round5(longitude)}`;
}

export function getCachedTerrainPoint(latitude: number, longitude: number): TerrainResponse | null {
  const entry = terrainPointCache.get(terrainPointCacheKey(latitude, longitude));
  if (entry && entry.expires > Date.now()) return entry.payload;
  return null;
}

// ---- Terrain request lifecycle ----
// A terrain/elevation query follows ONE coherent lifecycle from click to a
// terminal state:
//   1. cache-first by rounded coordinate (10-min session TTL)
//   2. in-flight dedupe by coordinate — concurrent clicks on the same cell
//      share a single network request instead of flooding the provider
//   3. wait through the provider's real latency (a cold NASA LP DAAC .hgt
//      tile download measured 16–26.5s in this stack) up to a terrain-specific
//      ceiling — the popup is never flipped to UNAVAILABLE at an arbitrary
//      small timeout while the backend is still legitimately working
//   4. retry exactly ONCE (bounded — never a loop) on a transient transport /
//      5xx / client-ceiling failure, signalling the UI via `onRetry` so it can
//      render "Terrain provider is temporarily unavailable. Retrying…"
//   5. terminal UNAVAILABLE only when a real backend answer, an auth/RBAC/
//      validation failure, or the exhausted transient retry says so.
// A user cancellation or a definitive backend UNAVAILABLE/NOT_CONFIGURED
// payload never triggers a retry.
export const TERRAIN_REQUEST_TIMEOUT_MS = 60 * 1000;
const TERRAIN_RETRY_DELAY_MS = 800;

export interface TerrainRequestOptions {
  signal?: AbortSignal;
  /** Client-side ceiling for this single terrain/elevation request. Defaults
   *  to the terrain ceiling (60s), NOT the generic 25s API cap — a cold SRTM
   *  tile is legitimately slower than any ordinary API call. */
  timeoutMs?: number;
  /** Fired when a transient failure is about to be retried so UI layers can
   *  show "retrying" instead of an error. */
  onRetry?: () => void;
}

/** A zero-status (network) failure, a 5xx, or a client-ceiling timeout are
 *  transient and eligible for the bounded retry. Auth/RBAC/validation and any
 *  definitive backend answer are terminal. */
function isTerrainTransientFailure(status: number, timedOut: boolean): boolean {
  return status === 0 || status >= 500 || timedOut;
}

type TerrainAttempt = {
  ok: boolean;
  status: number;
  cancelled: boolean;
  timedOut: boolean;
  payload?: TerrainResponse;
};

async function terrainAttempt(
  path: string,
  options: TerrainRequestOptions
): Promise<TerrainAttempt> {
  let response: Response | null = null;
  let timedOut = false;
  try {
    response = await authFetch(
      path,
      { signal: options.signal },
      options.timeoutMs ?? TERRAIN_REQUEST_TIMEOUT_MS
    );
  } catch (error) {
    if (options.signal?.aborted) return { ok: false, status: 0, cancelled: true, timedOut: false };
    if (error instanceof ApiTimeoutError) timedOut = true;
    response = null;
  }
  const status = response?.status ?? 0;
  if (response?.ok) {
    try {
      return {
        ok: true,
        status,
        timedOut: false,
        cancelled: false,
        payload: (await response.json()) as TerrainResponse,
      };
    } catch {
      // malformed success body — fall through to status-based failure handling
    }
  }
  return { ok: false, status, cancelled: false, timedOut };
}

/** Settles after `ms` unless the caller's signal cancels it first (unlike a
 *  plain sleep, an abort during backoff is never swallowed). */
function abortAwareDelay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('The user aborted a request.', 'AbortError'));
      return;
    }
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException('The user aborted a request.', 'AbortError'));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

function terrainFailurePayload(
  latitude: number,
  longitude: number,
  dataset: string | null,
  reason: string
): TerrainResponse {
  return {
    latitude,
    longitude,
    data_status: 'UNAVAILABLE',
    data_source: null,
    provider: null,
    provider_role: null,
    dataset,
    elevation_m: null,
    slope_percent: null,
    slope_degrees: null,
    slope_category: null,
    elevation_change_m: null,
    slope_window_arcsec: null,
    sample_radius_km: null,
    sample_count: null,
    computed_at: null,
    reason,
  };
}

function terrainCancelPayload(latitude: number, longitude: number, dataset: string | null): TerrainResponse {
  return terrainFailurePayload(latitude, longitude, dataset, 'Cancelled.');
}

function terrainReasonFor(endpoint: 'terrain' | 'elevation', status: number, timedOut: boolean): string {
  if (timedOut) {
    return 'The terrain provider took too long to answer this request (client timeout). Please try again.';
  }
  if (status === 401) {
    return 'Session expired — the terrain request was re-authenticated but access was still denied.';
  }
  if (status === 403) {
    return endpoint === 'elevation'
      ? 'Insufficient permission for this account to read elevation data.'
      : 'Insufficient permission for this account to read terrain data.';
  }
  if (status === 422) {
    return 'Invalid latitude/longitude values for terrain.';
  }
  if (status >= 500) {
    return endpoint === 'elevation'
      ? `Elevation request failed (${status}).`
      : `Backend/provider failure while fetching terrain (${status}).`;
  }
  if (status > 0) {
    return `Terrain request failed (${status}).`;
  }
  return endpoint === 'elevation'
    ? 'Backend unreachable — elevation unavailable.'
    : 'Backend unreachable from this browser context.';
}

/** Single-coordinate terrain fetch with the full lifecycle: bounded transient
 *  retry (exactly once, backoff, abort-aware) layered on one auth'd attempt.
 *  Returns a terminal TerrainResponse the caller can render as-is. */
async function requestTerrainPayload(
  endpoint: 'terrain' | 'elevation',
  path: string,
  latitude: number,
  longitude: number,
  datasetLabel: string | null,
  options: TerrainRequestOptions
): Promise<TerrainResponse> {
  let attempt = await terrainAttempt(path, options);
  if (attempt.cancelled) {
    return terrainCancelPayload(latitude, longitude, datasetLabel);
  }

  // Terminal outcomes never retry: a definitive backend answer (ok status with
  // UNAVAILABLE/NOT_CONFIGURED), or auth/RBAC/validation client failures.
  if (attempt.ok) {
    return attempt.payload as TerrainResponse;
  }
  if (!isTerrainTransientFailure(attempt.status, attempt.timedOut)) {
    return terrainFailurePayload(
      latitude,
      longitude,
      datasetLabel,
      terrainReasonFor(endpoint, attempt.status, attempt.timedOut)
    );
  }

  // Transient failure: bounded single retry with a short, abort-aware backoff.
  if (!options.signal?.aborted) {
    options.onRetry?.();
    try {
      await abortAwareDelay(TERRAIN_RETRY_DELAY_MS, options.signal);
    } catch {
      return terrainCancelPayload(latitude, longitude, datasetLabel);
    }
    attempt = await terrainAttempt(path, options);
    if (attempt.cancelled) {
      return terrainCancelPayload(latitude, longitude, datasetLabel);
    }
    if (attempt.ok) {
      return attempt.payload as TerrainResponse;
    }
  }

  return terrainFailurePayload(
    latitude,
    longitude,
    datasetLabel,
    terrainReasonFor(endpoint, attempt.status, attempt.timedOut)
  );
}

// ---- in-flight dedupe maps ----
// Two rapid clicks on the same coordinate (or a fixed + satellite map sharing
// a point) must produce ONE request. The same rounded keys as the caches bind
// the dedupe window, so an in-flight cell is reuse-coalesced and the promise
// is dropped from the map as soon as it settles.
const terrainPointInflight = new Map<string, Promise<TerrainResponse>>();
const terrainElevationInflight = new Map<string, Promise<TerrainResponse>>();

// Local reactive state for browser session persistence
let habitationsState = [...INITIAL_HABITATIONS];
let relocationSitesState = [...INITIAL_RELOCATION_SITES];
let recommendationsState = [...INITIAL_RECOMMENDATIONS];
let fieldReportsState = [...INITIAL_FIELD_REPORTS];
let activeUser: User = DEMO_USERS[0]; // Admin by default

// Bearer token for the RBAC-guarded /api/evacuation/* surface (backend login).
let authToken: string | null = (() => {
  try { return localStorage.getItem('nammasafe_access_token'); } catch { return null; }
})();

export function getAuthToken(): string | null {
  return authToken;
}

// Decodes the JWT `exp` claim (UTC seconds) so callers can detect a stale
// session BEFORE issuing a request instead of learning it from a late 401.
// A missing/malformed token is treated as stale (forces a fresh login).
export function isAccessTokenExpired(token: string | null): boolean {
  if (!token) return true;
  try {
    const part = token.split('.')[1];
    if (!part) return true;
    const normalized = part.replace(/-/g, '+').replace(/_/g, '/');
    const payload = JSON.parse(
      atob(`${normalized}${'='.repeat((4 - (normalized.length % 4)) % 4)}`)
    ) as { exp?: unknown };
    return typeof payload?.exp === 'number' ? payload.exp * 1000 <= Date.now() : false;
  } catch {
    return true;
  }
}

function readStoredAccessToken(): string | null {
  try {
    return localStorage.getItem('nammasafe_access_token');
  } catch {
    return null;
  }
}

function clearStoredAccessToken(): void {
  try {
    localStorage.removeItem('nammasafe_access_token');
  } catch {
    /* noop */
  }
}

// Development-only diagnostics. Logs request paths, HTTP statuses, whether a
// token was present (boolean only) and retry flags — never the token itself.
const IS_DEV = Boolean((import.meta as { env?: Record<string, unknown> }).env?.DEV) &&
  (import.meta as { env?: Record<string, unknown> }).env?.MODE !== 'test';
function devLog(...args: unknown[]): void {
  if (!IS_DEV) return;
  try {
    // eslint-disable-next-line no-console
    console.debug(
      '[namsafe-api]',
      args.map((a) => (typeof a === 'object' ? JSON.stringify(a) : String(a))).join(' ')
    );
  } catch {
    // never let logging break the client
  }
}

const scopeOrDefault = (value?: string) =>
  value && value !== '*' ? value : '';

// Honest curated-inventory gate: relocation sites and hazard events only exist
// as curated records for the one region that genuinely carries them. A request is
// served from that inventory strictly when the selection matches the curated region
// itself — never as a substitute for any other location.
const isCuratedRegion = (state?: string, district?: string) =>
  String(state ?? '').toLowerCase() === 'uttarakhand' &&
  String(district ?? '').toLowerCase() === 'chamoli';

// No pilot fallbacks: every region is resolved to its own coordinates and served
// its own data. Curated records (when any exist for the selected region) are
// ordinary inventory; live providers always target the selected location.

// Normalize an OSM-derived habitations record into the Habitation shape.
// Curated risk scores are NOT fabricated for OSM villages — they are shown as
// unavailable (0) and the layer is explicitly labelled as OSM-derived.
function toOsHabitation(raw: Record<string, unknown>): Habitation {
  const lat = Number(raw.latitude);
  const lng = Number(raw.longitude);
  return {
    id: String(raw.id ?? `osm-${lat}-${lng}`),
    village_code: String(raw.village_code ?? raw.id ?? `osm-${lat}-${lng}`),
    village_name: String(raw.village_name ?? `Village ${lat.toFixed(4)}, ${lng.toFixed(4)}`),
    district: String(raw.district ?? ''),
    state: String(raw.state ?? ''),
    population: Number(raw.population) || 0,
    households: Number(raw.households) || 0,
    children_count: 0,
    elderly_count: 0,
    hospital_distance_km: Number(raw.hospital_distance_km) || 0,
    road_access_score: 0,
    vulnerability_score: 0,
    hazard_score: 0,
    priority_score: 0,
    priority_level: (raw.priority_level as PriorityLevel) ?? 'Monitor Only',
    latitude: lat,
    longitude: lng,
    landslide_risk: 0,
    flood_risk: 0,
    extreme_rainfall_risk: 0,
    past_disaster_frequency: 0,
    disaster_history_count: 0,
    is_dynamic_osm: true,
    source: 'OpenStreetMap (Overpass API)',
    data_status: String(raw.data_status ?? 'LIVE'),
    notes: 'Derived live from OpenStreetMap; curated risk scores unavailable.',
  };
}

async function loginToBackend(): Promise<void> {
  const user = getActiveUser();
  const creds: { username_or_email: string; password: string; state_id?: string; district_id?: string; sub_district_id?: string; area_id?: string } = {
    username_or_email: user.username,
    password: `${user.username}123`,
  };
  if (user.role !== 'admin' && user.assignment) {
    creds.state_id = scopeOrDefault(user.assignment.state_id);
    creds.district_id = scopeOrDefault(user.assignment.district_id);
    creds.sub_district_id = scopeOrDefault(user.assignment.sub_district_id);
    creds.area_id = scopeOrDefault(user.assignment.area_id);
  }

  let token: string | null = null;
  try {
    const res = await fetchWithTimeout('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(creds),
    });
    if (res.ok) token = (await res.json()).access_token;
  } catch {
    token = null;
  }

  if (!token && user.role !== 'admin') {
    // Fallback: public-read officer scope keeps evacuation usable for non-admin
    // personas without pretending any fixed location is the user's scope.
    try {
      const res = await fetchWithTimeout('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username_or_email: 'officer',
          password: 'officer123',
          state_id: '',
          district_id: '',
          sub_district_id: '',
          area_id: '',
        }),
      });
      if (res.ok) token = (await res.json()).access_token;
    } catch {
      token = null;
    }
  }

  authToken = token;
  if (token) {
    try { localStorage.setItem('nammasafe_access_token', token); } catch { /* noop */ }
  } else {
    try { localStorage.removeItem('nammasafe_access_token'); } catch { /* noop */ }
  }
}

async function ensureAuthToken(): Promise<void> {
  const stored = readStoredAccessToken();
  authToken = stored && !isAccessTokenExpired(stored) ? stored : null;
  if (!authToken && stored) {
    // A stored session exists but is expired/malformed — discard it so the
    // next login persists a fresh credential.
    clearStoredAccessToken();
  }
  if (!authToken) await loginToBackend();
}

async function doFetch(
  path: string,
  options: RequestInit,
  timeoutMs: number = API_FETCH_TIMEOUT_MS
): Promise<Response> {
  const headers: Record<string, string> = {
    ...((options.headers as Record<string, string>) ?? {}),
  };
  if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
  if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  return fetchWithTimeout(path, { ...options, headers }, timeoutMs);
}

async function authFetch(
  path: string,
  options: RequestInit = {},
  timeoutMs: number = API_FETCH_TIMEOUT_MS
): Promise<Response> {
  await ensureAuthToken();
  let retried = false;
  let response = await doFetch(path, options, timeoutMs);
  if (response.status === 401) {
    // Stale/expired session: clear it, re-login with the existing backend flow
    // and retry the request exactly ONCE. Never loops.
    retried = true;
    authToken = null;
    clearStoredAccessToken();
    await loginToBackend();
    response = await doFetch(path, options, timeoutMs);
  }
  devLog('auth request', { path, status: response.status, tokenPresent: Boolean(authToken), retried });
  return response;
}

// Authenticated GET helper for the SAFE_MOVE_AI live-intelligence endpoints.
async function authGet(path: string, options: RequestInit = {}): Promise<Response> {
  await ensureAuthToken();
  return authFetch(path, options);
}

// Typed API error so the UI can distinguish auth/RBAC/validation/server failures.
export class ApiRequestError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiRequestError';
    this.status = status;
  }
}

async function toApiError(res: Response): Promise<ApiRequestError> {
  let message: string | undefined;
  try {
    const data = await res.json();
    message = typeof data.detail === 'string' ? data.detail : undefined;
  } catch {
    /* non-JSON error body — use status-based message */
  }
  if (res.status === 401) {
    return new ApiRequestError(401, 'Authentication failed — please sign in again.');
  }
  if (res.status === 403) {
    return new ApiRequestError(403, 'You are not authorized to submit field reports with this role.');
  }
  if (res.status === 422) {
    return new ApiRequestError(422, 'Submission validation failed — check the description (at least 10 characters) and coordinates.');
  }
  return new ApiRequestError(
    res.status,
    message || (res.status === 400 ? 'The submission was rejected due to invalid data.' : `The reporting service returned an error (${res.status}).`)
  );
}

export function getActiveUser(): User {
  let saved: string | null = null;
  try {
    saved = localStorage.getItem('nammasafe_user');
  } catch {
    saved = null;
  }
  if (saved) {
    try {
      return JSON.parse(saved);
    } catch {
      // ignore
    }
  }
  return activeUser;
}

export function setActiveUser(user: User) {
  activeUser = user;
  localStorage.setItem('nammasafe_user', JSON.stringify(user));
}

// ==================== CALCULATION ENGINES ====================
export function calculateHazardScore(
  landslide: number,
  flood: number,
  rainfall: number,
  pastFreq: number
): number {
  const score = 0.4 * landslide + 0.3 * flood + 0.2 * rainfall + 0.1 * pastFreq;
  return Number(Math.min(100, Math.max(0, score)).toFixed(1));
}

export function calculateVulnerabilityScore(
  population: number,
  households: number,
  children: number,
  elderly: number,
  hospitalKm: number,
  roadAccessScore: number
): number {
  const popDensityScore = Math.min(100, (population / 5000) * 100);
  const dependentRatio = population > 0 ? ((children + elderly) / population) * 100 : 0;
  const poorRoadComponent = 100 - roadAccessScore;
  const hospitalDistScore = Math.min(100, (hospitalKm / 40) * 100);

  const score =
    0.35 * popDensityScore +
    0.25 * dependentRatio +
    0.2 * poorRoadComponent +
    0.2 * hospitalDistScore;
  return Number(Math.min(100, Math.max(0, score)).toFixed(1));
}

export function calculatePriorityScore(
  hazardScore: number,
  vulnScore: number,
  disasterHistCount: number
): { score: number; level: Habitation['priority_level'] } {
  const histScore = Math.min(100, disasterHistCount * 16);
  const priority = 0.5 * hazardScore + 0.3 * vulnScore + 0.2 * histScore;
  const finalScore = Number(Math.min(100, Math.max(0, priority)).toFixed(1));

  let level: Habitation['priority_level'] = 'Monitor Only';
  if (finalScore >= 75.0) {
    level = 'Immediate Relocation';
  } else if (finalScore >= 50.0) {
    level = 'Short-Term Relocation';
  } else if (finalScore >= 30.0) {
    level = 'Medium-Term Relocation';
  }

  return { score: finalScore, level };
}

// Honest curated-scope helper: the curated Chamoli dashboard summary is
// derived ONLY from the genuinely-curated Chamoli inventory (habitations,
// safe sites, hazard events and verified field reports) that is seeded and
// served for that exact region. Every number is a real aggregate over those
// curated records — none are fabricated or substituted.
function buildCuratedChamoliSummary(): DashboardSummary {
  const priorityDistribution: PriorityLevel[] = [
    'Immediate Relocation',
    'Short-Term Relocation',
    'Medium-Term Relocation',
    'Monitor Only',
  ];

  const criticalVillages = [...habitationsState]
    .filter((h) => h.state === 'Uttarakhand' && h.district === 'Chamoli')
    .sort((a, b) => (b.priority_score ?? 0) - (a.priority_score ?? 0))
    .slice(0, 5);

  const distinctPriority = (v: PriorityLevel) =>
    habitationsState.filter((h) => h.priority_level === v);

  const relocationPriorityDistribution = priorityDistribution
    .map((level) => {
      const group = distinctPriority(level);
      return {
        level,
        count: group.length,
        population: group.reduce((s, h) => s + (h.population || 0), 0),
      };
    })
    .filter((g) => g.count > 0);

  const verifiedCount = fieldReportsState.filter((r) => r.verified).length;

  const hazardCounts = new Map<string, number>();
  priorityDistribution.forEach(() => {});
  INITIAL_HAZARD_EVENTS.forEach((e) => {
    hazardCounts.set(e.hazard_type, (hazardCounts.get(e.hazard_type) ?? 0) + 1);
  });

  const available_capacity = relocationSitesState.reduce(
    (s, site) => s + (site.available_capacity_families ?? 0),
    0,
  );

  return {
    total_habitations_monitored: habitationsState.length,
    high_risk_population: habitationsState
      .filter((h) => h.priority_level === 'Immediate Relocation')
      .reduce((s, h) => s + (h.population || 0), 0),
    immediate_relocation_villages_count: distinctPriority('Immediate Relocation').length,
    available_safe_site_capacity: available_capacity,
    total_safe_sites: relocationSitesState.length,
    verified_field_reports_count: verifiedCount,
    pending_field_reports_count: fieldReportsState.length - verifiedCount,
    hazard_distribution: [...hazardCounts.entries()].map(([hazard_type, count]) => ({
      hazard_type,
      count,
      affected_population: habitationsState
        .filter((h) => h.id === hazard_type)
        .reduce((s, h) => s + (h.population || 0), 0),
    })),
    relocation_priority_distribution: relocationPriorityDistribution,
    recent_field_reports: [...fieldReportsState]
      .sort((a, b) => b.reported_at.localeCompare(a.reported_at))
      .slice(0, 3),
    top_five_critical_villages: criticalVillages,
    pilot_district: 'Chamoli',
    pilot_state: 'Uttarakhand',
    is_synthetic_demo_data: false,
    data_status: 'SIMULATED',
    region: { state: 'Uttarakhand', district: 'Chamoli', is_pilot: true, has_curated_data: true },
    message: 'Curated Chamoli inventory summary.',
  };
}

// ==================== API SERVICE METHODS ====================
export const api = {
  async getDashboardSummary(state?: string, district?: string): Promise<DashboardSummary> {
    try {
      const params = new URLSearchParams();
      if (state) params.append('state', state);
      if (district) params.append('district', district);
      const qs = params.toString();
      const res = await fetchWithTimeout(`/api/dashboard-summary${qs ? `?${qs}` : ''}`);
      if (res.ok) return await res.json();
    } catch {
      // fallback below — never fabricate numbers for an empty region
    }

    // Honest curated-scope contract: the curated Chamoli dashboard summary is
    // derived ONLY from the genuinely-curated inventory (habitations, safe
    // sites, hazard events, field reports). It is served exactly when Chamoli
    // is genuinely selected — never substituted for another region.
    if (isCuratedRegion(state, district)) {
      return buildCuratedChamoliSummary();
    }

    const emptyPriority: Record<PriorityLevel, { level: PriorityLevel; count: number; population: number }> = {

      'Immediate Relocation': { level: 'Immediate Relocation', count: 0, population: 0 },
      'Short-Term Relocation': { level: 'Short-Term Relocation', count: 0, population: 0 },
      'Medium-Term Relocation': { level: 'Medium-Term Relocation', count: 0, population: 0 },
      'Monitor Only': { level: 'Monitor Only', count: 0, population: 0 },
    };
    return {
      total_habitations_monitored: 0,
      high_risk_population: 0,
      immediate_relocation_villages_count: 0,
      available_safe_site_capacity: 0,
      total_safe_sites: 0,
      verified_field_reports_count: 0,
      pending_field_reports_count: 0,
      hazard_distribution: [],
      relocation_priority_distribution: Object.values(emptyPriority),
      recent_field_reports: [],
      top_five_critical_villages: [],
      is_synthetic_demo_data: false,
      data_status: 'UNAVAILABLE',
      message: 'Data unavailable for this location',
    };
  },

  async getMapLayers(state?: string, district?: string): Promise<MapLayersResponse> {
    try {
      const params = new URLSearchParams();
      if (state) params.append('state', state);
      if (district) params.append('district', district);
      const qs = params.toString();
      const res = await fetchWithTimeout(`/api/map-layers${qs ? `?${qs}` : ''}`);
      if (res.ok) return await res.json();
    } catch {
      // fallback
    }

    return {
      red_zones: [],
      habitations: [],
      relocation_sites: [],
      infrastructure: [],
      pilot_center: null,
      is_synthetic_demo_data: false,
      layers_status: {
        red_zones: 'UNAVAILABLE',
        habitations: 'UNAVAILABLE',
        relocation_sites: 'UNAVAILABLE',
        infrastructure: 'UNAVAILABLE',
      },
    };
  },

  async getHabitations(options: {
    priorityLevel?: string;
    search?: string;
    state?: string;
    district?: string;
    lat?: number;
    lng?: number;
    radius?: number;
  } = {}): Promise<HabitationsFetchResult> {
    const { priorityLevel, search, state, district, lat, lng, radius } = options;

    // 1) Curated inventory for the selected region (records only exist where the
    // source dataset covers them; otherwise UNAVAILABLE, not a substitute).
    try {
      const params = new URLSearchParams();
      if (priorityLevel) params.append('priority_level', priorityLevel);
      if (search) params.append('search', search);
      if (state) params.append('state', state);
      if (district) params.append('district', district);
      const qs = params.toString();
      const res = await fetchWithTimeout(`/api/habitations${qs ? `?${qs}` : ''}`);
      if (res.ok) {
        const list: Habitation[] = await res.json();
        return {
          habitations: list,
          data_status: list.length ? 'SIMULATED' : 'UNAVAILABLE',
          data_source: 'Curated inventory dataset',
          count: list.length,
          reason: list.length ? undefined : 'No curated habitations for this region.',
        };
      }
    } catch {
      // fall through
    }

    // 2) Live OSM-derived villages around the anchor point (real data, LIVE).
    if (typeof lat === 'number' && typeof lng === 'number') {
      const params = new URLSearchParams({ lat: String(lat), lng: String(lng) });
      if (state) params.append('state', state);
      if (district) params.append('district', district);
      if (radius) params.append('radius', String(radius));
      try {
        const res = await authGet(`/api/habitations/dynamic?${params.toString()}`);
        if (res.ok) {
          const payload = await res.json();
          const habitations = (payload.habitations ?? []).map((raw: Record<string, unknown>) =>
            toOsHabitation(raw)
          );
          return {
            habitations,
            data_status: payload.data_status === 'LIVE' ? 'LIVE' : 'UNAVAILABLE',
            data_source: 'OpenStreetMap (Overpass API)',
            count: habitations.length,
            reason: payload.reason ?? null,
          };
        }
      } catch {
        // fall through
      }
    }

    // Honest curated-scope contract: the curated inventory genuinely exists
    // ONLY for Chamoli (Uttarakhand / Chamoli). It is served exactly when the
    // selected region is precisely Chamoli — never substituted for another.
    if (!isCuratedRegion(state, district)) {
      return {
        habitations: [],
        data_status: 'UNAVAILABLE',
        data_source: 'Curated inventory dataset',
        count: 0,
        reason: 'No curated habitations for this region.',
      };
    }
    return {
      habitations: habitationsState,
      data_status: 'SIMULATED',
      data_source: 'Curated inventory dataset',
      count: habitationsState.length,
      reason: undefined,
    };
  },

  async getHabitationById(id: string): Promise<Habitation | null> {
    try {
      const res = await fetchWithTimeout(`/api/habitations/${id}`);
      if (res.ok) return await res.json();
    } catch {
      // fallback
    }
    return habitationsState.find((h) => h.id === id || h.village_code === id) || null;
  },

  async getHabitationRiskAnalysis(id: string) {
    try {
      const res = await fetchWithTimeout(`/api/habitations/${id}/risk-analysis`);
      if (res.ok) return await res.json();
    } catch {
      // fallback
    }

    const hab = habitationsState.find((h) => h.id === id || h.village_code === id);
    if (!hab) throw new Error('Habitation not found');

    const events = INITIAL_HAZARD_EVENTS.filter((e) => e.habitation_id === hab.id);
    const recs = recommendationsState.filter((r) => r.habitation_id === hab.id);
    const reports = fieldReportsState.filter((fr) => fr.habitation_id === hab.id);

    return {
      habitation: hab,
      historical_events: events,
      recommendations: recs,
      field_reports: reports,
      risk_breakdown: {
        hazard_components: {
          landslide_risk_weighted: Number((0.4 * hab.landslide_risk).toFixed(1)),
          flood_risk_weighted: Number((0.3 * hab.flood_risk).toFixed(1)),
          rainfall_risk_weighted: Number((0.2 * hab.extreme_rainfall_risk).toFixed(1)),
          past_disaster_weighted: Number((0.1 * hab.past_disaster_frequency).toFixed(1)),
          total_hazard_score: hab.hazard_score,
        },
        vulnerability_components: {
          vulnerability_score: hab.vulnerability_score,
          hospital_distance_km: hab.hospital_distance_km,
          road_access_score: hab.road_access_score,
          children_ratio_percent: Number(((hab.children_count / hab.population) * 100).toFixed(1)),
          elderly_ratio_percent: Number(((hab.elderly_count / hab.population) * 100).toFixed(1)),
        },
        priority_calculation: {
          hazard_contribution_50pct: Number((0.5 * hab.hazard_score).toFixed(1)),
          vulnerability_contribution_30pct: Number((0.3 * hab.vulnerability_score).toFixed(1)),
          disaster_history_contribution_20pct: Number(
            (0.2 * Math.min(100, hab.disaster_history_count * 16)).toFixed(1)
          ),
          final_priority_score: hab.priority_score,
          priority_level: hab.priority_level,
        },
      },
    };
  },

  async getRelocationSites(state?: string, district?: string): Promise<RelocationSite[]> {
    try {
      const params = new URLSearchParams();
      if (state) params.append('state', state);
      if (district) params.append('district', district);
      const qs = params.toString();
      const res = await fetchWithTimeout(`/api/relocation-sites${qs ? `?${qs}` : ''}`);
      if (res.ok) return await res.json();
    } catch {
      // fallback
    }
    return isCuratedRegion(state, district) ? relocationSitesState : [];
  },

  async getRedZones(): Promise<any[]> {
    return INITIAL_RED_ZONES;
  },

  async getInfrastructure(): Promise<any[]> {
    return INFRASTRUCTURE_ITEMS;
  },

  async getHazardEvents(state?: string, district?: string): Promise<any[]> {
    return isCuratedRegion(state, district) ? INITIAL_HAZARD_EVENTS : [];
  },

  async getRecommendations(): Promise<RelocationRecommendation[]> {
    return this.getRelocationRecommendations();
  },

  async getRelocationRecommendations(statusFilter?: string): Promise<RelocationRecommendation[]> {
    try {
      const params = statusFilter ? `?status_filter=${statusFilter}` : '';
      const res = await fetchWithTimeout(`/api/relocation-recommendations${params}`);
      if (res.ok) return await res.json();
    } catch {
      // fallback
    }

    if (statusFilter && statusFilter !== 'all') {
      return recommendationsState.filter((r) => r.status.toLowerCase() === statusFilter.toLowerCase());
    }
    return recommendationsState;
  },

  async getFieldReports(): Promise<FieldReport[]> {
    try {
      const res = await fetchWithTimeout('/api/field-reports');
      if (res.ok) return await res.json();
    } catch {
      // fallback
    }
    return fieldReportsState;
  },

  async submitFieldReport(report: Partial<FieldReport>): Promise<FieldReport> {
    const hab = habitationsState.find((h) => h.id === report.habitation_id);
    if (!hab) throw new ApiRequestError(400, 'Invalid habitation — this village is unknown.');

    const payload = {
      habitation_id: hab.id,
      report_type: report.report_type || 'Geotechnical Observation',
      description: report.description || '',
      image_url: report.image_url || undefined,
      severity: report.severity || 'High',
      latitude: report.latitude ?? hab.latitude,
      longitude: report.longitude ?? hab.longitude,
    };

    let res: Response;
    try {
      res = await authFetch('/api/field-reports', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } catch {
      // Backend unreachable — never fake a successful submission.
      throw new ApiRequestError(0, 'Cannot reach the reporting service — please try again later.');
    }

    if (!res.ok) throw await toApiError(res);

    const created = await res.json();
    fieldReportsState = [created, ...fieldReportsState];
    return {
      id: created.id,
      habitation_id: created.habitation_id,
      habitation_name: created.habitation_name,
      officer_id: created.officer_id,
      officer_name: created.officer_name,
      report_type: created.report_type,
      description: created.description,
      image_url: created.image_url || '',
      reported_at: created.reported_at,
      verified: Boolean(created.verified),
      severity: created.severity,
      latitude: created.latitude,
      longitude: created.longitude,
    };
  },

  async verifyFieldReport(id: string, verifierName?: string): Promise<FieldReport> {
    fieldReportsState = fieldReportsState.map((r) =>
      r.id === id
        ? {
            ...r,
            verified: true,
            officer_name: verifierName ? `${r.officer_name} [Verified by ${verifierName}]` : r.officer_name,
          }
        : r
    );
    const updated = fieldReportsState.find((r) => r.id === id);
    return updated!;
  },

  async recalculatePriority(params: any): Promise<Habitation> {
    await this.calculatePriority(params);
    const hab = habitationsState.find((h) => h.id === params.habitation_id);
    return hab!;
  },

  async calculatePriority(params: {
    habitation_id: string;
    landslide_risk?: number;
    flood_risk?: number;
    extreme_rainfall_risk?: number;
    road_access_score?: number;
  }): Promise<PriorityCalculationResult> {
    const hab = habitationsState.find((h) => h.id === params.habitation_id);
    if (!hab) throw new Error('Habitation not found');

    const l = params.landslide_risk ?? hab.landslide_risk;
    const f = params.flood_risk ?? hab.flood_risk;
    const r = params.extreme_rainfall_risk ?? hab.extreme_rainfall_risk;
    const road = params.road_access_score ?? hab.road_access_score;

    const newH = calculateHazardScore(l, f, r, hab.past_disaster_frequency);
    const newV = calculateVulnerabilityScore(
      hab.population,
      hab.households,
      hab.children_count,
      hab.elderly_count,
      hab.hospital_distance_km,
      road
    );
    const { score: newP, level: newLvl } = calculatePriorityScore(newH, newV, hab.disaster_history_count);

    // Update in state
    habitationsState = habitationsState.map((h) =>
      h.id === hab.id
        ? {
            ...h,
            hazard_score: newH,
            vulnerability_score: newV,
            priority_score: newP,
            priority_level: newLvl,
            landslide_risk: l,
            flood_risk: f,
            extreme_rainfall_risk: r,
            road_access_score: road,
          }
        : h
    );

    return {
      habitation_id: hab.id,
      village_name: hab.village_name,
      hazard_score: newH,
      vulnerability_score: newV,
      priority_score: newP,
      priority_level: newLvl,
      updated: true,
    };
  },

  async simulateRelocation(
    habitationId: string,
    siteId: string,
    familiesCount: number
  ): Promise<SimulationResult> {
    try {
      const res = await fetchWithTimeout('/api/simulate-relocation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          habitation_id: habitationId,
          relocation_site_id: siteId,
          families_count: familiesCount,
        }),
      });
      if (res.ok) return await res.json();
    } catch {
      // fallback to client-side engine
    }

    const hab = habitationsState.find((h) => h.id === habitationId);
    const site = relocationSitesState.find((s) => s.id === siteId);

    if (!hab || !site) throw new Error('Invalid Habitation or Relocation Site');

    const availableCap = site.available_capacity_families;
    const isSufficient = familiesCount <= availableCap;
    const remainingCap = availableCap - familiesCount;

    // Risk reduction calculation
    const sourceRisk = hab.hazard_score;
    const destRisk = 100.0 - site.suitability_score;
    const delta = Math.max(0, sourceRisk - destRisk);
    const riskReduction = Number(((delta / sourceRisk) * 100).toFixed(1));

    // Pillar statuses
    const waterRatio = (familiesCount + site.current_occupancy_families) / site.water_capacity_families;
    let waterStatus = 'Sufficient';
    if (waterRatio > 1.0) waterStatus = 'Deficit - Pipeline Expansion Needed';
    else if (waterRatio > 0.8) waterStatus = 'Near Capacity (80%+)';

    const schoolRatio = (familiesCount + site.current_occupancy_families) / site.school_capacity_families;
    let schoolStatus = 'Adequate';
    if (schoolRatio > 1.0) schoolStatus = 'Overburdened - New Classrooms Needed';
    else if (schoolRatio > 0.8) schoolStatus = 'Approaching Threshold';

    const hospitalStatus =
      site.hospital_score >= 85 ? 'Optimal (Sub-district trauma access within 15 min)' : 'Moderate';
    const roadStatus = site.road_score >= 85 ? 'High Connectivity (All-weather 2-lane)' : 'Moderate';

    let altRec: string | undefined = undefined;
    if (!isSufficient) {
      const altSite = relocationSitesState
        .filter((s) => s.id !== site.id && s.available_capacity_families >= familiesCount)
        .sort((a, b) => b.suitability_score - a.suitability_score)[0];
      if (altSite) {
        altRec = `${altSite.site_name} (Available Capacity: ${altSite.available_capacity_families} families, Suitability: ${altSite.suitability_score}/100)`;
      }
    }

    let rationale = `Relocating ${familiesCount} households from ${hab.village_name} (Priority ${hab.priority_score}) to ${site.site_name} yields an estimated ${riskReduction}% drop in compound hazard exposure.`;
    if (!isSufficient) {
      rationale += ` WARNING: The requested ${familiesCount} families exceeds ${site.site_name}'s safe remaining threshold of ${availableCap} families by ${Math.abs(remainingCap)}.`;
    } else {
      rationale += ` Infrastructure carrying capacity is viable, retaining a buffer of ${remainingCap} family slots.`;
    }

    return {
      habitation_id: hab.id,
      habitation_name: hab.village_name,
      relocation_site_id: site.id,
      relocation_site_name: site.site_name,
      families_requested: familiesCount,
      is_capacity_sufficient: isSufficient,
      remaining_capacity_after_relocation: remainingCap,
      risk_reduction_percent: riskReduction,
      water_capacity_status: waterStatus,
      school_capacity_status: schoolStatus,
      hospital_access_status: hospitalStatus,
      road_access_status: roadStatus,
      decision_rationale: rationale,
      alternative_site_recommendation: altRec,
    };
  },

  async planEvacuation(
    origin: EvacuationOriginPayload,
    familiesCount?: number,
    destSiteId?: string
  ): Promise<EvacuationPlanResponse> {
    await ensureAuthToken();
    const res = await authFetch('/api/evacuation/plan', {
      method: 'POST',
      body: JSON.stringify({
        origin: { type: origin.type, id: origin.id, label: origin.label, lat: origin.lat, lng: origin.lng, latitude: origin.latitude, longitude: origin.longitude },
        families_count: familiesCount,
        dest_site_id: destSiteId,
      }),
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error((detail as { detail?: string }).detail ?? `Evacuation planning failed (${res.status})`);
    }
    return res.json();
  },

  async getEvacuationCandidates(
    originType: EvacuationOriginPayload['type'],
    originId: string,
    familiesCount = 50
  ): Promise<{ origin: EvacuationOriginPayload; families_count: number; candidates: EvacuationRouteCandidate[] }> {
    await ensureAuthToken();
    const params = new URLSearchParams({
      origin_type: originType,
      origin_id: originId,
      families_count: String(familiesCount),
    });
    const res = await authFetch(`/api/evacuation/candidates?${params.toString()}`);
    if (!res.ok) throw new Error(`Could not fetch evacuation candidates (${res.status})`);
    return res.json();
  },

  async getEvacuationRoute(routeId: string): Promise<EvacuationPlanResponse> {
    await ensureAuthToken();
    const res = await authFetch(`/api/evacuation/routes/${routeId}`);
    if (!res.ok) throw new Error(`Could not fetch evacuation route (${res.status})`);
    return res.json();
  },

  async confirmEvacuationRoute(routeId: string, decision = 'approved', notes?: string): Promise<EvacuationPlanResponse> {
    await ensureAuthToken();
    const res = await authFetch(`/api/evacuation/routes/${routeId}/confirm`, {
      method: 'POST',
      body: JSON.stringify({ decision, notes }),
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error((detail as { detail?: string }).detail ?? `Could not confirm route (${res.status})`);
    }
    return res.json();
  },

  async getRoadConditions(): Promise<RoadConditionsResponse> {
    await ensureAuthToken();
    const res = await authFetch('/api/evacuation/road-conditions');
    if (!res.ok) throw new Error(`Could not fetch road conditions (${res.status})`);
    return res.json();
  },

  async getFloodForecast(state?: string, district?: string): Promise<FloodForecastResponse> {
    await ensureAuthToken();
    const params = new URLSearchParams();
    if (state) params.append('state', state);
    if (district) params.append('district', district);
    const qs = params.toString();
    const res = await authFetch(`/api/flood-forecast${qs ? `?${qs}` : ''}`);
    if (!res.ok) throw new Error(`Could not fetch flood forecast (${res.status})`);
    return res.json();
  },

  async getRiskAlerts(areaId?: string): Promise<RiskAlert[]> {
    await ensureAuthToken();
    const qs = areaId ? `?area_id=${encodeURIComponent(areaId)}` : '';
    const res = await authFetch(`/api/risk-alerts${qs}`);
    if (!res.ok) throw new Error(`Could not fetch risk alerts (${res.status})`);
    return res.json();
  },

  async getDataStatus(): Promise<DataStatusResponse> {
    await ensureAuthToken();
    const res = await authFetch('/api/data-status');
    if (!res.ok) {
      // Return an empty set rather than a hand-written partial list. The
      // consumer resolves an empty `layers` to its own documented fallback, so a
      // fabricated 2-row payload here would silently replace the full status
      // list instead of deferring to it.
      return {
        layers: [],
        checked_at: new Date().toISOString(),
        providers: [],
      };
    }
    return res.json();
  },

  // ---- SAFE_MOVE_AI live intelligence ----
  // Read-only public endpoints (map.read_public — every role incl. citizens).
  // Science-data endpoints (weather/terrain/flood/rainfall/nearby/geocode)
  // return explicitly labelled UNAVAILABLE/NOT_CONFIGURED payloads on ANY
  // failure — never fabricated telemetry. Aggregation endpoints (risk-zones,
  // safe-locations, risk-assessment) throw so the page can show the failure.

  async getWeather(latitude: number, longitude: number): Promise<WeatherResponse> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), WEATHER_POINT_TIMEOUT_MS);
    try {
      const res = await authGet(`/api/weather/${latitude}/${longitude}`, { signal: controller.signal });
      if (res.ok) return await res.json();
    } catch {
      /* fall through to labelled payload */
    } finally {
      clearTimeout(timer);
    }
    return {
      latitude, longitude, data_status: 'UNAVAILABLE', data_source: 'Open-Meteo',
      observed_at: null, current: null, forecast: [], timezone: null,
      reason: 'Weather provider unreachable from this browser context.',
    };
  },

  // Single-point forecast used by the Weather Forecast map popup. Carries the
  // same honest status taxonomy as getTerrain so an auth failure is never
  // labelled a provider outage.
  async getWeatherRow(latitude: number, longitude: number, days = 7): Promise<WeatherResponse> {
    const params = new URLSearchParams({ days: String(days) });
    const path = `/api/weather/${latitude}/${longitude}?${params.toString()}`;
    let response: Response | null = null;
    try {
      response = await authFetch(path);
    } catch {
      response = null; // network failure — backend unreachable
    }
    const status = response?.status ?? 0;

    if (response && response.ok) {
      try {
        return (await response.json()) as WeatherResponse;
      } catch {
        /* malformed body — fall through to the status path */
      }
    }

    let reason = 'Backend unreachable from this browser context.';
    if (status === 401) {
      reason = 'Session expired — the weather request was re-authenticated but access was still denied.';
    } else if (status === 403) {
      reason = 'Insufficient permission for this account to read forecast data.';
    } else if (status === 422) {
      reason = 'Invalid latitude/longitude or days value for the forecast.';
    } else if (status >= 500) {
      reason = `Backend/provider failure while fetching forecast (${status}).`;
    } else if (status > 0) {
      reason = `Forecast request failed (${status}).`;
    }

    return {
      latitude, longitude,
      data_status: 'UNAVAILABLE',
      data_source: 'Open-Meteo/ECMWF',
      provider: null, provider_role: null, model: null,
      observed_at: null, current: null, hourly: [], forecast: [],
      timezone: null, reason,
    };
  },

  // Single-point historical (ERA5 archive) record for a completed past month.
  // Used by the Weather map picker enrichment in historical mode. Mirrors the
  // honest status vocabulary of getWeather — never labels an auth failure a
  // provider outage.
  async getWeatherHistorical(latitude: number, longitude: number, year: number, month: number): Promise<HistoricalWeatherResponse> {
    const path = `/api/weather/${latitude}/${longitude}/historical?year=${year}&month=${month}`;
    let response: Response | null = null;
    try {
      response = await authFetch(path);
    } catch {
      response = null;
    }
    const status = response?.status ?? 0;
    if (response && response.ok) {
      try {
        return (await response.json()) as HistoricalWeatherResponse;
      } catch {
        /* malformed body — fall through */
      }
    }
    let reason = 'Backend unreachable from this browser context.';
    if (status === 401) {
      reason = 'Session expired — the historical weather request was re-authenticated but access was still denied.';
    } else if (status === 403) {
      reason = 'Insufficient permission for this account to read historical weather data.';
    } else if (status === 400) {
      reason = 'No historical weather sample covers that month yet (completed months only).';
    } else if (status >= 500) {
      reason = `Backend/provider failure while fetching historical weather (${status}).`;
    } else if (status > 0) {
      reason = `Historical weather request failed (${status}).`;
    }
    return {
      latitude, longitude,
      data_status: 'UNAVAILABLE',
      data_source: 'Open-Meteo ERA5 Archive',
      provider: null,
      provider_role: 'historical',
      dataset: 'Open-Meteo ERA5 Archive',
      is_historical: true,
      year, month,
      period: `${year}-${String(month).padStart(2, '0')}`,
      variables: {},
      top_rain_day: null,
      daily: [],
      computed_at: null,
      reason,
    };
  },

  // India-wide weather / hazard map grid. `bounds` is 'north,south,east,west'
  // (resolved by the caller from the viewport). Map bounds are clipped to the
  // weather data domain (India) before the request so a global view still pulls
  // the full Indian window and invalid/degenerate bounds are never sent. Views
  // entirely outside the domain come back as an honest UNAVAILABLE grid.
  async getWeatherGrid(
    bounds: string,
    options: {
      variable?: WeatherVariable | string;
      layer?: WeatherVariable | string;
      day?: number;
      hour?: number;
      forecastTime?: string;
      step?: number;
      maxPoints?: number;
      prefer?: 'auto' | 'ecmwf';
      // Historical (ERA5) mode: completed past months only. When set, the
      // request omits live-forecast parameters that the backend rejects.
      year?: number;
      month?: number;
      signal?: AbortSignal;
    } = {}
  ): Promise<WeatherGridResponse> {
    const {
      variable = 'temperature_2m',
      layer,
      day = 0,
      hour,
      forecastTime,
      step = 0.25,
      maxPoints = 600,
      prefer = 'auto',
      year,
      month,
      signal,
    } = options;

    const clip = clipWeatherGridBounds(bounds);
    const requestedBounds = {
      north: clip.north, south: clip.south, east: clip.east, west: clip.west,
    };
    const historical = typeof year === 'number' && typeof month === 'number';

    const fallbackBase: WeatherGridResponse = {
      data_status: 'UNAVAILABLE',
      data_source: historical ? 'Open-Meteo ERA5 Archive' : 'Open-Meteo/ECMWF',
      provider: null, provider_role: null, model: null,
      variable: layer || variable, day, hour, unit: null,
      bounds: requestedBounds,
      steps: { latitude: step, longitude: step },
      resolution: { latitude: step, longitude: step },
      valid_time: null, min: null, max: null,
      derived: layer === 'wind_u' || layer === 'wind_v' || variable === 'wind_u' || variable === 'wind_v',
      points: [],
      computed_at: null, generated_at: null,
      assumption: null,
      reason: null,
      is_historical: historical,
      year: historical ? year : null,
      month: historical ? month : null,
    };

    if (clip.entirelyOutside || !clip.clipped) {
      return {
        ...fallbackBase,
        reason:
          'Requested area lies outside the weather data domain (India: lat 6–37.4, lon 68–98.5).',
      };
    }

    const params = new URLSearchParams({
      bounds: clip.clipped,
      variable: layer || variable,
      step: String(step),
      max_points: String(maxPoints),
    });
    if (historical) {
      params.set('year', String(year));
      params.set('month', String(month));
      params.set('day', String(day));
    } else {
      params.set('day', String(day));
      params.set('prefer', String(prefer));
      if (hour !== undefined) {
        params.set('hour', String(hour));
      }
      if (forecastTime) {
        params.set('forecast_time', forecastTime);
      }
    }
    const path = `/api/weather/grid?${params.toString()}`;

    const cacheKey = weatherGridCacheKey({
      clipped: clip.clipped,
      variable: layer || variable,
      day,
      hour: historical ? undefined : hour,
      step,
      maxPoints,
      prefer,
      forecastTime,
      year,
      month,
    });
    const hit = weatherGridCache.get(cacheKey);
    if (hit && hit.expires > Date.now()) {
      return hit.payload;
    }

    let response: Response | null = null;
    try {
      response = await authFetch(path, { signal });
    } catch {
      if (signal?.aborted) {
        return {
          ...fallbackBase,
          reason: 'Request cancelled.',
        };
      }
      response = null;
    }
    const status = response?.status ?? 0;

    if (response && response.ok) {
      try {
        const grid = (await response.json()) as WeatherGridResponse;
        const served = grid.data_status ?? '';
        if (!['UNAVAILABLE', 'ERROR', 'NOT_CONFIGURED'].includes(served)) {
          weatherGridCache.set(cacheKey, {
            payload: grid,
            expires: Date.now() + WEATHER_GRID_CACHE_TTL_MS,
          });
        }
        return grid;
      } catch {
        /* malformed body — fall through */
      }
    }

    let reason = 'Backend unreachable from this browser context.';
    if (status === 401) {
      reason = 'Session expired — the weather grid request was re-authenticated but access was still denied.';
    } else if (status === 403) {
      reason = 'Insufficient permission for this account to read the weather grid.';
    } else if (status === 400) {
      reason = 'Invalid grid bounds/variable — bounds must be north,south,east,west.';
    } else if (status === 422) {
      reason = 'Invalid weather grid parameters.';
    } else if (status >= 500) {
      reason = `Backend/provider failure while fetching the weather grid (${status}).`;
    } else if (status > 0) {
      reason = `Weather grid request failed (${status}).`;
    }

    return { ...fallbackBase, reason };
  },

  // Real SRTM elevation + slope layer for the weather & hazard map.
  async getTerrainGrid(
    bounds: string,
    options: { step?: number; maxPoints?: number; signal?: AbortSignal } = {}
  ): Promise<TerrainGridResponse> {
    const { step = 0.1, maxPoints = 400, signal } = options;
    const parts = bounds.split(',').map((s) => Number(s));
    const rectangular = parts.length === 4 && parts.every((n) => Number.isFinite(n));
    if (!rectangular) {
      return {
        data_status: 'UNAVAILABLE',
        data_source: null,
        reason: 'Invalid bounds — expected north,south,east,west.',
        points: [],
      };
    }
    const params = new URLSearchParams({ bounds, step: String(step), max_points: String(maxPoints) });
    const path = `/api/terrain-grid?${params.toString()}`;
    let response: Response | null = null;
    try {
      response = await authFetch(path, { signal });
    } catch {
      if (signal?.aborted) {
        return { data_status: 'UNAVAILABLE', data_source: null, reason: 'Cancelled.', points: [] };
      }
      response = null;
    }
    if (response && response.ok) {
      try {
        return (await response.json()) as TerrainGridResponse;
      } catch {
        /* malformed body — fall through */
      }
    }
    return {
      data_status: 'UNAVAILABLE',
      data_source: null,
      reason: response
        ? `Terrain grid request failed (${response.status}).`
        : 'Backend unreachable — terrain layer unavailable.',
      points: [],
    };
  },

  // Transparent rule-based flood-risk overlay grid (CALCULATED, never fabricated).
  // Historical mode: pass year+month to combine ERA5 monthly precipitation and
  // storm-day counts with SRTM terrain (completed months only).
  async getFloodRiskGrid(
    bounds: string,
    options: { step?: number; maxPoints?: number; signal?: AbortSignal; year?: number; month?: number } = {}
  ): Promise<FloodRiskGridResponse> {
    const { step = 0.15, maxPoints = 300, signal, year, month } = options;
    const historical = typeof year === 'number' && typeof month === 'number';
    const parts = bounds.split(',').map((s) => Number(s));
    const rectangular = parts.length === 4 && parts.every((n) => Number.isFinite(n));
    if (!rectangular) {
      return {
        data_status: 'UNAVAILABLE',
        data_source: 'Transparent rule-based overlay (weather + SRTM terrain)',
        reason: 'Invalid bounds — expected north,south,east,west.',
        points: [],
      };
    }
    const params = new URLSearchParams({ bounds, step: String(step), max_points: String(maxPoints) });
    if (historical) {
      params.set('year', String(year));
      params.set('month', String(month));
    }
    const path = `/api/flood-risk-grid?${params.toString()}`;
    let response: Response | null = null;
    try {
      response = await authFetch(path, { signal });
    } catch {
      if (signal?.aborted) {
        return {
          data_status: 'UNAVAILABLE',
          data_source: 'Transparent rule-based overlay (weather + SRTM terrain)',
          reason: 'Cancelled.',
          points: [],
        };
      }
      response = null;
    }
    if (response && response.ok) {
      try {
        return (await response.json()) as FloodRiskGridResponse;
      } catch {
        /* malformed body — fall through */
      }
    }
    return {
      data_status: 'UNAVAILABLE',
      data_source: 'Transparent rule-based overlay (weather + SRTM terrain)',
      reason: response
        ? `Flood-risk grid request failed (${response.status}).`
        : 'Backend unreachable — flood-risk layer unavailable.',
      points: [],
    };
  },

  // Failure vocabulary for terrain requests — never labels an authentication
  // failure as a NASA/provider outage. The full request lifecycle (cache →
  // in-flight dedupe → wait through the provider's latency → bounded transient
  // retry → honest terminal state) lives in requestTerrainPayload above.
  async getTerrain(latitude: number, longitude: number, options: TerrainRequestOptions = {}): Promise<TerrainResponse> {
    const cached = getCachedTerrainPoint(latitude, longitude);
    if (cached) return cached;

    const key = terrainPointCacheKey(latitude, longitude);
    const inflight = terrainPointInflight.get(key);
    if (inflight) return inflight;

    const path = `/api/terrain/${latitude}/${longitude}`;
    const promise = requestTerrainPayload(
      'terrain',
      path,
      latitude,
      longitude,
      null,
      options
    ).then((payload) => {
      if (payload.data_status !== 'UNAVAILABLE' && payload.data_status !== 'NOT_CONFIGURED') {
        terrainPointCache.set(key, {
          payload,
          expires: Date.now() + TERRAIN_POINT_CACHE_TTL_MS,
        });
      }
      devLog('terrain', {
        path,
        tokenPresent: Boolean(getAuthToken()),
        data_status: payload.data_status,
        reason: payload.reason,
      });
      return payload;
    });
    terrainPointInflight.set(key, promise);
    promise.then(() => terrainPointInflight.delete(key), () => terrainPointInflight.delete(key));
    return promise;
  },

  // Alias is kept for callers that followed the old /api/elevation?lat&lon
  // convention; the fast path now serves elevation-only (real SRTM, cached
  // tile, no slope window) — see getElevationFast below.
  async getElevation(latitude: number, longitude: number): Promise<TerrainResponse> {
    return this.getElevationFast(latitude, longitude);
  },

  // Fast elevation sample for the Terrain map (real NASA SRTM elevation only,
  // progressive-loading contract). Cache-first with in-flight dedupe; the
  // same bounded lifecycle as getTerrain applies.
  async getElevationFast(latitude: number, longitude: number, options: TerrainRequestOptions = {}): Promise<TerrainResponse> {
    const cacheKey = `elevfast:${round5(latitude)}:${round5(longitude)}`;
    const hit = terrainElevationCache.get(cacheKey);
    if (hit && hit.expires > Date.now()) {
      return hit.payload;
    }

    const inflight = terrainElevationInflight.get(cacheKey);
    if (inflight) return inflight;

    const path = `/api/elevation?lat=${latitude}&lon=${longitude}`;
    const promise = requestTerrainPayload(
      'elevation',
      path,
      latitude,
      longitude,
      'NASA SRTM (fast path)',
      options
    ).then((payload) => {
      if (payload.data_status !== 'UNAVAILABLE' && payload.data_status !== 'NOT_CONFIGURED') {
        terrainElevationCache.set(cacheKey, {
          payload,
          expires: Date.now() + TERRAIN_ELEVATION_CACHE_TTL_MS,
        });
      }
      return payload;
    });
    terrainElevationInflight.set(cacheKey, promise);
    promise.then(() => terrainElevationInflight.delete(cacheKey), () => terrainElevationInflight.delete(cacheKey));
    return promise;
  },

  // Historical (ERA5) completed-month availability: years + completed months.
  async getHistoricalYears(): Promise<HistoricalWeatherYearsResponse> {
    try {
      const res = await authFetch('/api/historical/weather/years');
      if (res.ok) return (await res.json()) as HistoricalWeatherYearsResponse;
    } catch {
      /* fall through */
    }
    return {
      availability: [],
      current_year: new Date().getUTCFullYear(),
      completed_through_month: null,
      provider: null,
      provenance: null,
    };
  },

  async getFloodRisk(latitude: number, longitude: number): Promise<FloodRiskResponse> {
    try {
      const res = await authGet(`/api/flood-risk/${latitude}/${longitude}`);
      if (res.ok) return await res.json();
    } catch {
      /* fall through */
    }
    return {
      latitude, longitude, data_status: 'NOT CONFIGURED' as DataLayerStatus, data_source: 'Copernicus GloFAS',
      river_discharge_m3s: null, threshold_m3s: null, discharge_band: null,
      lead_time_hours: null, issue_time: null, valid_time: null, forecast_hours: null,
      dataset: null, computed_at: null, assumption: null,
      reason: 'GloFAS dataset not reachable/integrated.',
    };
  },

  async getRainfall(latitude: number, longitude: number): Promise<RainfallResponse> {
    try {
      const res = await authGet(`/api/rainfall/${latitude}/${longitude}`);
      if (res.ok) return await res.json();
    } catch {
      /* fall through */
    }
    return {
      latitude, longitude, data_status: 'NOT CONFIGURED' as DataLayerStatus, data_source: 'NASA GPM IMERG',
      precipitation_mm_hour: null, dataset: null, tile_time: null,
      computed_at: null, assumption: null,
      reason: 'GPM IMERG tiles not integrated for this point.',
    };
  },

  async getRainfallMap(bounds: string, maxPoints = 400): Promise<RainfallGridResponse> {
    let res: Response | null = null;
    try {
      const params = new URLSearchParams({ bounds, max_points: String(maxPoints) });
      res = await authGet(`/api/rainfall-grid?${params.toString()}`);
      if (res.ok) return await res.json();
    } catch {
      res = null;
    }
    const [n, s, e, w] = bounds.split(',').map((part) => Number(part));
    return {
      data_status: 'UNAVAILABLE' as DataLayerStatus,
      data_source: 'NASA GPM IMERG',
      dataset: null,
      tile_time: null,
      computed_at: null,
      bounds: { north: n || 0, south: s || 0, east: e || 0, west: w || 0 },
      points: [],
      assumption: null,
      reason: res?.status === 400
        ? 'bounds is required (north,south,east,west) — resolve it from the selected region.'
        : 'GPM IMERG grid unreachable from this browser context.',
    };
  },

  async getNearby(kind: string, latitude: number, longitude: number, radius?: number): Promise<NearbyPlacesResponse> {
    try {
      const params = new URLSearchParams({ lat: String(latitude), lng: String(longitude) });
      if (radius) params.set('radius', String(radius));
      const res = await authGet(`/api/nearby/${kind}?${params.toString()}`);
      if (res.ok) return await res.json();
    } catch {
      /* fall through */
    }
    return {
      kind, label: kind, center: { latitude, longitude }, radius_km: radius ?? 10,
      data_status: 'UNAVAILABLE', data_source: 'OpenStreetMap (Overpass API)',
      count: 0, places: [], reason: 'Overpass unreachable from this browser context.',
    };
  },

  async geocode(query: string, limit = 3, country = 'in'): Promise<GeocodeResponse> {
    try {
      const params = new URLSearchParams({ q: query, limit: String(limit), country });
      const res = await authGet(`/api/geocode?${params.toString()}`);
      if (res.ok) return await res.json();
    } catch {
      /* fall through */
    }
    return {
      query, data_status: 'UNAVAILABLE', data_source: 'Nominatim (OSM)',
      count: 0, places: [], reason: 'Geocoder unreachable from this browser context.',
    };
  },

  // -------------------- Bhuvan / ISRO (supporting layer) --------------------
  // Every method returns a typed payload carrying the explicit data vocabulary
  // (AVAILABLE | CACHED | UNAVAILABLE | ERROR | LOCATION_MISMATCH). Fallbacks
  // are honest: UNAVAILABLE with a reason, never fabricated coordinates.

  async bhuvanVillageGeocode(village: string, state?: string, district?: string): Promise<BhuvanVillageGeocodeResponse> {
    try {
      const params = new URLSearchParams({ village });
      if (state) params.set('state', state);
      if (district) params.set('district', district);
      const res = await authGet(`/api/bhuvan/village/geocode?${params.toString()}`);
      if (res.ok) return await res.json();
    } catch {
      /* fall through */
    }
    return {
      source: 'Bhuvan / ISRO', service: 'village_geocode', data_status: 'UNAVAILABLE',
      data_source: 'Bhuvan / ISRO village census geocode', has_coordinates: false,
      query: { village, state, district },
      reason: 'Bhuvan village geocode unreachable from this deployment.',
    };
  },

  async bhuvanReverseGeocode(lat: number, lng: number): Promise<BhuvanReverseGeocodeResponse> {
    try {
      const res = await authGet(`/api/bhuvan/village/reverse-geocode?lat=${lat}&lng=${lng}`);
      if (res.ok) return await res.json();
    } catch {
      /* fall through */
    }
    return {
      source: 'Bhuvan / ISRO', service: 'reverse_geocode', data_status: 'UNAVAILABLE',
      data_source: 'Bhuvan / ISRO reverse geocode', villages: [],
      reason: 'Bhuvan reverse geocode unreachable from this deployment.',
    };
  },

  async bhuvanHospitals(lat: number, lng: number, bufferM = 3000): Promise<BhuvanHospitalsResponse> {
    try {
      const res = await authGet(`/api/bhuvan/hospitals?lat=${lat}&lng=${lng}&buffer_m=${bufferM}`);
      if (res.ok) return await res.json();
    } catch {
      /* fall through */
    }
    return {
      source: 'Bhuvan / ISRO', service: 'hospitals', data_status: 'UNAVAILABLE',
      data_source: 'Bhuvan / ISRO hospitals proximity', center: { latitude: lat, longitude: lng },
      buffer_m: bufferM, count: 0, hospitals: [],
      reason: 'Bhuvan hospitals unreachable from this deployment.',
    };
  },

  async bhuvanLulc(lat: number, lng: number, year = 'all'): Promise<BhuvanLulcResponse> {
    try {
      const res = await authGet(`/api/bhuvan/lulc?lat=${lat}&lng=${lng}&year=${year}`);
      if (res.ok) return await res.json();
    } catch {
      /* fall through */
    }
    return {
      source: 'Bhuvan / ISRO', service: 'lulc', data_status: 'UNAVAILABLE',
      data_source: 'Bhuvan / ISRO LULC 250K', latitude: lat, longitude: lng,
      reason: 'Bhuvan LULC unreachable from this deployment.',
    };
  },

  async bhuvanShortestPath(lat1: number, lon1: number, lat2: number, lon2: number): Promise<BhuvanShortestPathResponse> {
    try {
      const res = await authGet(`/api/bhuvan/shortest-path`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lat1, lon1, lat2, lon2 }),
      });
      if (res.ok) return await res.json();
    } catch {
      /* fall through */
    }
    return {
      source: 'Bhuvan / ISRO', service: 'shortest_path', data_status: 'UNAVAILABLE',
      data_source: 'Bhuvan / ISRO intra-state shortest path',
      origin: [lat1, lon1], destination: [lat2, lon2],
      reason: 'Bhuvan routing unreachable from this deployment.',
    };
  },

  async bhuvanGeoid(tileId: string, datum = 'elipsoid'): Promise<BhuvanGeoidResponse> {
    try {
      const res = await authGet(`/api/bhuvan/geoid?tile_id=${encodeURIComponent(tileId)}&datum=${datum}`);
      if (res.ok) return await res.json();
    } catch {
      /* fall through */
    }
    return {
      source: 'Bhuvan / ISRO', service: 'geoid_tile_proxy', data_status: 'UNAVAILABLE',
      data_source: 'Bhuvan / ISRO CartoDEM geoid tile proxy', proxy: true,
      reason: 'Bhuvan geoid proxy unreachable from this deployment.',
    };
  },

  async getSafeRoutes(
    originLat: number, originLng: number, destLat: number, destLng: number
  ): Promise<SafeRoutesResponse> {
    const params = new URLSearchParams({
      origin_lat: String(originLat), origin_lng: String(originLng),
      dest_lat: String(destLat), dest_lng: String(destLng),
    });
    const res = await authGet(`/api/routes/safe?${params.toString()}`);
    if (!res.ok) throw new Error(`Could not compute safe routes (${res.status})`);
    return res.json();
  },

  async getDisasterEvents(params?: { state?: string; district?: string; hazard_type?: string; limit?: number }): Promise<DisasterEventsResponse> {
    const query = new URLSearchParams();
    if (params?.state) query.set('state', params.state);
    if (params?.district) query.set('district', params.district);
    if (params?.hazard_type) query.set('hazard_type', params.hazard_type);
    if (params?.limit) query.set('limit', String(params.limit));
    const suffix = query.toString() ? `?${query.toString()}` : '';
    const res = await authGet(`/api/disaster-events${suffix}`);
    if (!res.ok) throw new Error(`Could not fetch disaster events (${res.status})`);
    return res.json();
  },

  async getDisasterEventsNear(latitude: number, longitude: number, radiusKm = 50): Promise<DisasterEventsResponse> {
    const query = new URLSearchParams({ lat: String(latitude), lng: String(longitude), radius: String(radiusKm) });
    const res = await authGet(`/api/disaster-events/near?${query.toString()}`);
    if (!res.ok) throw new Error(`Could not fetch nearby disaster events (${res.status})`);
    return res.json();
  },

  async getRiskAssessment(params: {
    latitude: number; longitude: number; placeLabel?: string;
    state?: string; district?: string; village?: string; force?: boolean;
  }): Promise<RiskAssessmentResponse> {
    const query = new URLSearchParams({
      lat: String(params.latitude), lng: String(params.longitude),
    });
    if (params.placeLabel) query.set('place_label', params.placeLabel);
    if (params.state) query.set('state', params.state);
    if (params.district) query.set('district', params.district);
    if (params.village) query.set('village', params.village);
    if (params.force) query.set('force', 'true');
    const res = await authGet(`/api/risk-assessment?${query.toString()}`);
    if (!res.ok) throw new Error(`Could not compute risk assessment (${res.status})`);
    return res.json();
  },

  async recalculateRisk(params: {
    latitude: number; longitude: number; placeLabel?: string;
    state?: string; district?: string; village?: string;
  }): Promise<RiskAssessmentResponse> {
    const res = await authFetch('/api/risk-assessment/recalculate', {
      method: 'POST',
      body: JSON.stringify({
        latitude: params.latitude, longitude: params.longitude,
        place_label: params.placeLabel, state: params.state,
        district: params.district, village: params.village,
      }),
    });
    if (!res.ok) throw new Error(`Could not recompute risk assessment (${res.status})`);
    return res.json();
  },

  async getRiskZones(params?: { granularity?: 'habitations' | 'grid'; bounds?: string; maxPoints?: number; state?: string; district?: string }): Promise<RiskZonesResponse> {
    const query = new URLSearchParams({ granularity: params?.granularity ?? 'habitations' });
    if (params?.bounds) query.set('bounds', params.bounds);
    if (params?.maxPoints) query.set('max_points', String(params.maxPoints));
    if (params?.state) query.set('state', params.state);
    if (params?.district) query.set('district', params.district);
    const res = await authGet(`/api/risk-zones?${query.toString()}`);
    if (!res.ok) throw new Error(`Could not fetch risk zones (${res.status})`);
    return res.json();
  },

  async getSafeLocations(params: {
    latitude: number; longitude: number; affectedPopulation?: number; excludeStatus?: string[];
  }): Promise<SafeLocationsResponse> {
    const query = new URLSearchParams({
      lat: String(params.latitude), lng: String(params.longitude),
      affected_population: String(params.affectedPopulation ?? 0),
    });
    if (params.excludeStatus && params.excludeStatus.length > 0) {
      query.set('exclude_status', params.excludeStatus.join(','));
    }
    const res = await authGet(`/api/safe-locations?${query.toString()}`);
    if (!res.ok) throw new Error(`Could not fetch safe locations (${res.status})`);
    return res.json();
  },

  // ---- Historical (previous-year) Kerala data ----
  // Public read-only endpoints (no auth token needed).  On any failure we
  // return a clearly-labelled "NOT CONFIGURED" payload — never a fabricated
  // historical value.

  async getHistoricalAvailability(): Promise<HistoricalAvailability> {
    try {
      const res = await fetchWithTimeout('/api/historical/availability');
      if (res.ok) return await res.json();
    } catch {
      // fallback below
    }
    return {
      state: { code: 32, name: 'Kerala' },
      dataset_year: 2025,
      years_available: [],
      total_records: 0,
      districts: [],
      last_import_at: null,
      live_data_status: 'NOT CONFIGURED',
      status: 'NOT CONFIGURED',
    };
  },

  async getHistoricalKeralaSummaries(): Promise<HistoricalDistrictSummary[]> {
    try {
      const res = await fetchWithTimeout('/api/historical/kerala');
      if (res.ok) return await res.json();
    } catch {
      // fallback below
    }
    return [];
  },

  async getHistoricalDistrictBaseline(
    district: number | string,
    dataYear?: number
  ): Promise<HistoricalBaseline | null> {
    const query = dataYear ? `?data_year=${dataYear}` : '';
    try {
      const res = await fetchWithTimeout(`/api/historical/kerala/${district}/baseline${query}`);
      if (res.ok) return await res.json();
    } catch {
      // fallback below
    }
    return null;
  },

  async getHistoricalDistrictSummary(
    district: number | string
  ): Promise<HistoricalDistrictSummary | null> {
    try {
      const res = await fetchWithTimeout(`/api/historical/kerala/${district}`);
      if (res.ok) return await res.json();
    } catch {
      // fallback below
    }
    return null;
  },

  async getHistoricalCompare(
    district: number | string,
    rainfallMm: number,
    observationDate: string,
    options?: { hazardType?: string; source?: string; dataYear?: number }
  ): Promise<HistoricalCompareResponse | null> {
    const params = new URLSearchParams({
      rainfall_mm: String(rainfallMm),
      observation_date: observationDate,
    });
    if (options?.hazardType) params.set('hazard_type', options.hazardType);
    if (options?.source) params.set('source', options.source);
    if (options?.dataYear) params.set('data_year', String(options.dataYear));
    try {
      const res = await fetchWithTimeout(`/api/historical/kerala/${district}/compare?${params.toString()}`);
      if (res.ok) return await res.json();
    } catch {
      // fallback below
    }
    return null;
  },

  async resetSeedData() {
    return this.resetToDemoSeed();
  },

  async resetToDemoSeed() {
    habitationsState = [...INITIAL_HABITATIONS];
    relocationSitesState = [...INITIAL_RELOCATION_SITES];
    recommendationsState = [...INITIAL_RECOMMENDATIONS];
    fieldReportsState = [...INITIAL_FIELD_REPORTS];
    return true;
  },
};

export const apiService = api;
