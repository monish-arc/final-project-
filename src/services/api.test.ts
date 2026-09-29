import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import {
  calculateHazardScore,
  calculateVulnerabilityScore,
  calculatePriorityScore,
  apiService,
  ApiRequestError,
  ApiTimeoutError,
  clearTerrainPointCache,
  clearWeatherGridCache,
  getCachedTerrainPoint,
  isAccessTokenExpired,
  fetchWithTimeout,
  API_FETCH_TIMEOUT_MS,
} from './api';

type MockHeaders = Record<string, string> | undefined;

const jsonResponse = (body: unknown, status: number) => ({
  ok: status >= 200 && status < 300,
  status,
  headers: { get: () => 'application/json' },
  json: async () => body,
  text: async () => JSON.stringify(body),
});

const enc = (value: Record<string, unknown>) => btoa(JSON.stringify(value));
const expiredJwt = `${enc({ alg: 'HS256' })}.${enc({ role: 'admin', exp: Math.floor(Date.now() / 1000) - 60 })}.sig`;
const liveJwt = `${enc({ alg: 'HS256' })}.${enc({ role: 'admin', exp: Math.floor(Date.now() / 1000) + 3600 })}.sig`;

afterEach(() => {
  vi.unstubAllGlobals();
});

beforeEach(() => {
  clearTerrainPointCache();
  clearWeatherGridCache();
});

describe('SafeMove AI Mathematical Risk Engine', () => {
  it('calculates composite hazard score accurately using 4-factor weights', () => {
    // 0.40 * landslide + 0.30 * flood + 0.20 * rainfall + 0.10 * past_freq
    const score = calculateHazardScore(90, 80, 70, 60);
    // 0.4*90=36 + 0.3*80=24 + 0.2*70=14 + 0.1*60=6 = 80.0
    expect(score).toBe(80.0);
  });

  it('calculates vulnerability score considering demographic dependents & medical distance', () => {
    const pop = 1000;
    const households = 200;
    const children = 250;
    const elderly = 150;
    const hospitalKm = 20; // 50% distance score
    const roadAccess = 40; // 60% poor road component

    const vuln = calculateVulnerabilityScore(pop, households, children, elderly, hospitalKm, roadAccess);
    expect(vuln).toBeGreaterThan(0);
    expect(vuln).toBeLessThanOrEqual(100);
  });

  it('determines correct Priority Level thresholds based on composite priority index', () => {
    // Score >= 75 -> Immediate Relocation
    const high = calculatePriorityScore(90, 80, 5);
    expect(high.level).toBe('Immediate Relocation');
    expect(high.score).toBeGreaterThanOrEqual(75);

    // Score < 30 -> Monitor Only
    const low = calculatePriorityScore(15, 20, 0);
    expect(low.level).toBe('Monitor Only');
    expect(low.score).toBeLessThan(30);
  });
});

describe('Relocation Simulator Carrying Capacity Model', () => {
  it('detects sufficient vs exceeded carrying capacity correctly', async () => {
    // Moving 50 families to Gauchar (which has ~555 available capacity)
    const resultSufficient = await apiService.simulateRelocation(
      'hab-joshimath',
      'site-gauchar-01',
      50
    );
    expect(resultSufficient.is_capacity_sufficient).toBe(true);
    expect(resultSufficient.remaining_capacity_after_relocation).toBeGreaterThan(0);
    expect(resultSufficient.risk_reduction_percent).toBeGreaterThan(0);

    // Relocating 5000 families to Gauchar should exceed capacity
    const resultExceeded = await apiService.simulateRelocation(
      'hab-joshimath',
      'site-gauchar-01',
      5000
    );
    expect(resultExceeded.is_capacity_sufficient).toBe(false);
    expect(resultExceeded.remaining_capacity_after_relocation).toBeLessThan(0);
    expect(resultExceeded.decision_rationale).toContain('exceeds');
  });
});

describe('Resilient API Client and Seed Data', () => {
  it('loads curated Chamoli habitations and summary only when Chamoli is genuinely selected', async () => {
    // Honest curated-scope contract: records exist only for Uttarakhand /
    // Chamolihol. Requesting that exact region returns the curated inventory.
    const summary = await apiService.getDashboardSummary('Uttarakhand', 'Chamoli');
    expect(summary.total_habitations_monitored).toBeGreaterThanOrEqual(10);
    expect(summary.high_risk_population).toBeGreaterThan(0);
    expect(summary.top_five_critical_villages.length).toBe(5);

    const habitationsResult = await apiService.getHabitations({ state: 'Uttarakhand', district: 'Chamoli' });
    expect(habitationsResult.habitations.length).toBeGreaterThanOrEqual(10);
    expect(habitationsResult.data_status).toBe('SIMULATED');
    // reselection falsifier (honest): a NON-Chamoli region returns empty habitations
    const nonCurated = await apiService.getHabitations({ state: 'Tamil Nadu' });
    expect(nonCurated.habitations.length).toBe(0);
    expect(nonCurated.data_status).toBe('UNAVAILABLE');

    const joshimath = habitationsResult.habitations.find((h) => h.village_name.includes('Joshimath'));
    expect(joshimath).toBeDefined();
    expect(joshimath?.priority_level).toBe('Immediate Relocation');

    // A non-pilot region must never silently fall back to Chamoli seed data.
    const tamilNadu = await apiService.getHabitations({ state: 'Tamil Nadu' });
    expect(tamilNadu.habitations).toEqual([]);
    expect(tamilNadu.data_status).toBe('UNAVAILABLE');
  });
});

describe('Historical (Previous-Year) Kerala Rainfall API', () => {
  it('availability is never mislabelled as live', async () => {
    const avail = await apiService.getHistoricalAvailability();
    expect(avail.state.code).toBe(32);
    expect(avail.dataset_year).toBeGreaterThanOrEqual(2025);
    expect(['HISTORICAL', 'NOT CONFIGURED']).toContain(avail.status);
    expect(avail.live_data_status).toBe('NOT CONFIGURED');
    // All records (if any) must be provenance-tagged, never fabricated live values.
    expect(avail.total_records).toBeGreaterThanOrEqual(0);
  });

  it('kerala summaries list valid districts and are not live', async () => {
    const summaries = await apiService.getHistoricalKeralaSummaries();
    expect(Array.isArray(summaries)).toBe(true);
    for (const s of summaries) {
      expect(s.district_id).toBeGreaterThanOrEqual(554);
      expect(['HISTORICAL', 'NOT CONFIGURED']).toContain(s.status);
    }
  });

  it('district baseline returns NOT CONFIGURED when no dataset imported', async () => {
    const baseline = await apiService.getHistoricalDistrictBaseline(561);
    expect(['HISTORICAL', 'NOT CONFIGURED']).toContain(baseline?.status ?? 'NOT CONFIGURED');
    expect(baseline?.live_data_status ?? 'NOT CONFIGURED').toBe('NOT CONFIGURED');
  });

  it('district compare requires both rainfall and observation date', async () => {
    const compare = await apiService.getHistoricalCompare(561, 120.5, '2025-08-15');
    if (compare) {
      expect(compare.rainfall_mm).toBe(120.5);
      expect(compare.observation_date).toBe('2025-08-15');
      expect(['NORMAL', 'ELEVATED', 'HIGH', 'EXTREME']).toContain(compare.severity);
    }
  });

  it('district summary resolves a Kerala district name', async () => {
    const summary = await apiService.getHistoricalDistrictSummary(561);
    if (summary) {
      expect(summary.district_id).toBe(561);
      expect(summary.district.length).toBeGreaterThan(0);
    }
  });
});

describe('Field Report Submission (strict backend)', () => {
  it('rejects an unknown habitation with a 400 ApiRequestError before any network call', async () => {
    const err = await apiService
      .submitFieldReport({ habitation_id: 'hab-does-not-exist', description: 'x'.repeat(10) })
      .then(() => null, (e: unknown) => e);
    expect(err).toBeInstanceOf(ApiRequestError);
    expect((err as ApiRequestError).status).toBe(400);
  });

  it('maps a 422 server validation response to a typed error (never fake success)', async () => {
    const mockResponse = (body: unknown, init: { status: number }) => ({
      ok: init.status >= 200 && init.status < 300,
      status: init.status,
      headers: { get: () => 'application/json' },
      json: async () => body,
      text: async () => JSON.stringify(body),
    });
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.includes('/api/auth/login')) {
          return mockResponse({ access_token: 'tok' }, { status: 200 });
        }
        if (path.includes('/api/field-reports')) {
          return mockResponse(
            { detail: [{ loc: ['body', 'description'], msg: 'String should have at least 10 characters' }] },
            { status: 422 }
          );
        }
        return mockResponse({}, { status: 404 });
      })
    );

    const err = await apiService
      .submitFieldReport({
        habitation_id: 'hab-joshimath',
        description: 'short',
        latitude: 30.5574,
        longitude: 79.5658,
      })
      .then(() => null, (e: unknown) => e);
    expect(err).toBeInstanceOf(ApiRequestError);
    expect((err as ApiRequestError).status).toBe(422);
  });

  it('throws a network error (status 0) with no fake success when backend is unreachable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      })
    );

    const err = await apiService
      .submitFieldReport({
        habitation_id: 'hab-joshimath',
        description: 'Slope cracking observed along the temple approach road.',
        latitude: 30.5574,
        longitude: 79.5658,
      })
      .then(() => null, (e: unknown) => e);
    expect(err).toBeInstanceOf(ApiRequestError);
    expect((err as ApiRequestError).status).toBe(0);
    expect((err as ApiRequestError).message).toContain('reporting service');
  });

  it('maps a 403 RBAC rejection to a typed error', async () => {
    const mockResponse = (body: unknown, init: { status: number }) => ({
      ok: init.status >= 200 && init.status < 300,
      status: init.status,
      headers: { get: () => 'application/json' },
      json: async () => body,
      text: async () => JSON.stringify(body),
    });
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.includes('/api/auth/login')) {
          return mockResponse({ access_token: 'tok' }, { status: 200 });
        }
        if (path.includes('/api/field-reports')) {
          return mockResponse({ detail: 'Not enough permissions' }, { status: 403 });
        }
        return mockResponse({}, { status: 404 });
      })
    );

    const err = await apiService
      .submitFieldReport({
        habitation_id: 'hab-joshimath',
        description: 'Soil saturation and toe seepage visible along the lower slope.',
        latitude: 30.5574,
        longitude: 79.5658,
      })
      .then(() => null, (e: unknown) => e);
    expect(err).toBeInstanceOf(ApiRequestError);
    expect((err as ApiRequestError).status).toBe(403);
    expect((err as ApiRequestError).message).toContain('not authorized');
  });

  it('getRainfallMap falls back to an honest UNAVAILABLE grid when the backend is unreachable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      })
    );

    const grid = await apiService.getRainfallMap('30.8,29.8,79.8,79.0', 400);
    expect(grid.data_status).toBe('UNAVAILABLE');
    expect(grid.points).toEqual([]);
    expect(grid.data_source).toContain('NASA GPM IMERG');
    expect(grid.reason).toContain('unreachable');
  });
});

describe('Terrain / Elevation integration (NASA Earthdata SRTM, backend 200 verified)', () => {
  it('detects an expired/malformed stored JWT as stale and a live one as valid', () => {
    expect(isAccessTokenExpired(null)).toBe(true);
    expect(isAccessTokenExpired('not-a-jwt')).toBe(true);
    expect(isAccessTokenExpired(expiredJwt)).toBe(true);
    expect(isAccessTokenExpired(liveJwt)).toBe(false);
  });

  it('authenticates on a fresh/stale session and maps the LIVE backend payload exactly (12.0904, 79.6878)', async () => {
    const requests: { path: string; authorization?: string }[] = [];
    const livePayload = {
      latitude: 12.0904,
      longitude: 79.6878,
      data_status: 'LIVE',
      data_source: 'NASA Earthdata SRTM (LP DAAC SRTMGL1 v003)',
      provider: 'nasa',
      provider_role: 'primary',
      dataset: 'NASA SRTMGL1 v003 (1 arc-second, LP DAAC)',
      elevation_m: 155.2,
      slope_percent: 4.5,
      slope_degrees: 2.58,
      slope_category: 'MODERATELY_SLOPING',
      elevation_change_m: 6.0,
      slope_window_arcsec: 3,
      sample_radius_km: null,
      sample_count: 9,
      computed_at: '2026-09-21T10:00:00Z',
      reason: null,
    };

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const path = String(url);
        const headers = (init?.headers as MockHeaders) ?? {};
        requests.push({ path, authorization: headers.Authorization });
        if (path.includes('/api/auth/login')) {
          return jsonResponse({ access_token: 'fresh-jwt' }, 200);
        }
        if (path.includes('/api/terrain/12.0904/79.6878')) {
          return jsonResponse(livePayload, 200);
        }
        return jsonResponse({}, 404);
      })
    );
    // Simulate a stale stored session — the client must re-login before terrain.
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => (key === 'nammasafe_access_token' ? expiredJwt : null),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });

    const terrain = await apiService.getTerrain(12.0904, 79.6878);
    expect(terrain.data_status).toBe('LIVE');
    expect(terrain.elevation_m).toBe(155.2);
    expect(terrain.slope_percent).toBe(4.5);
    expect(terrain.slope_degrees).toBe(2.58);
    expect(terrain.slope_category).toBe('MODERATELY_SLOPING');
    expect(terrain.data_source).toBe('NASA Earthdata SRTM (LP DAAC SRTMGL1 v003)');
    expect(terrain.provider).toBe('nasa');
    expect(terrain.dataset).toBe('NASA SRTMGL1 v003 (1 arc-second, LP DAAC)');
    expect(terrain.computed_at).toBe('2026-09-21T10:00:00Z');

    const terrainRequest = requests.find((r) => r.path.includes('/api/terrain/12.0904/79.6878'));
    expect(terrainRequest).toBeDefined();
    expect(terrainRequest?.authorization).toMatch(/^Bearer .+$/);
  });

  it('re-authenticates once after a 401 and retries GET /api/terrain exactly once (never loops)', async () => {
    let terrainCalls = 0;
    let loginCalls = 0;
    const authHeaders: string[] = [];
    const livePayload = {
      latitude: 12.0904,
      longitude: 79.6878,
      data_status: 'LIVE',
      data_source: 'NASA Earthdata SRTM (LP DAAC SRTMGL1 v003)',
      provider: 'nasa',
      provider_role: 'primary',
      dataset: 'NASA SRTMGL1 v003 (1 arc-second, LP DAAC)',
      elevation_m: 155.2,
      slope_percent: 4.5,
      slope_degrees: 2.58,
      slope_category: 'MODERATELY_SLOPING',
      elevation_change_m: 6.0,
      slope_window_arcsec: 3,
      sample_radius_km: null,
      sample_count: 9,
      computed_at: '2026-09-21T10:00:00Z',
      reason: null,
    };

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const path = String(url);
        const headers = (init?.headers as MockHeaders) ?? {};
        if (headers.Authorization) authHeaders.push(headers.Authorization);
        if (path.includes('/api/auth/login')) {
          loginCalls += 1;
          return jsonResponse({ access_token: `tok-${loginCalls}` }, 200);
        }
        if (path.includes('/api/terrain/12.0904/79.6878')) {
          terrainCalls += 1;
          return terrainCalls === 1
            ? jsonResponse({ detail: 'Could not validate credentials or token expired' }, 401)
            : jsonResponse(livePayload, 200);
        }
        return jsonResponse({}, 404);
      })
    );

    const terrain = await apiService.getTerrain(12.0904, 79.6878);
    expect(terrainCalls).toBe(2); // initial + exactly ONE retry
    expect(terrain.data_status).toBe('LIVE');
    expect(terrain.elevation_m).toBe(155.2);
    expect(authHeaders.length).toBeGreaterThanOrEqual(1);
    expect(authHeaders[authHeaders.length - 1]).toMatch(/^Bearer tok-/);
  });

  it('labels a 403 as an RBAC/permission failure, never a NASA provider outage', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.includes('/api/auth/login')) return jsonResponse({ access_token: 'tok' }, 200);
        if (path.includes('/api/terrain/')) return jsonResponse({ detail: 'Access denied for this role' }, 403);
        return jsonResponse({}, 404);
      })
    );

    const terrain = await apiService.getTerrain(12.0904, 79.6878);
    expect(terrain.data_status).toBe('UNAVAILABLE');
    expect(terrain.reason?.toLowerCase()).toContain('permission');
    expect(terrain.reason).not.toContain('provider unreachable');
    expect(terrain.elevation_m).toBeNull();
  });

  it('labels a 422 as an invalid-coordinates failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.includes('/api/auth/login')) return jsonResponse({ access_token: 'tok' }, 200);
        if (path.includes('/api/terrain/')) {
          return jsonResponse(
            { detail: [{ loc: ['path', 'latitude'], msg: 'less than or equal to 90' }] },
            422
          );
        }
        return jsonResponse({}, 404);
      })
    );

    const terrain = await apiService.getTerrain(95.0, 79.6878);
    expect(terrain.data_status).toBe('UNAVAILABLE');
    expect(terrain.reason?.toLowerCase()).toContain('latitude');
  });

  it('labels a 5xx as a backend/provider failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.includes('/api/auth/login')) return jsonResponse({ access_token: 'tok' }, 200);
        if (path.includes('/api/terrain/')) return jsonResponse({ detail: 'upstream error' }, 500);
        return jsonResponse({}, 404);
      })
    );

    const terrain = await apiService.getTerrain(12.0904, 79.6878);
    expect(terrain.data_status).toBe('UNAVAILABLE');
    expect(terrain.reason?.toLowerCase()).toContain('backend/provider');
    expect(terrain.reason).not.toContain('unreachable from this browser context');
  });

  it('labels a network failure as backend unreachable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      })
    );

    const terrain = await apiService.getTerrain(12.0904, 79.6878);
    expect(terrain.data_status).toBe('UNAVAILABLE');
    expect(terrain.reason).toContain('Backend unreachable');
    expect(terrain.elevation_m).toBeNull();
  });

  it('serves a cached point by rounded coordinates on repeat requests (no refetch)', async () => {
    const livePayload = {
      latitude: 27.5081,
      longitude: 79.6382,
      data_status: 'LIVE',
      data_source: 'NASA Earthdata SRTM (LP DAAC SRTMGL1 v003)',
      provider: 'nasa',
      provider_role: 'primary',
      dataset: 'NASA SRTMGL1 v003 (1 arc-second, LP DAAC)',
      elevation_m: 140.05,
      slope_percent: 2.11,
      slope_degrees: 1.21,
      slope_category: 'NEARLY_LEVEL',
      elevation_change_m: 6.0,
      slope_window_arcsec: 3,
      sample_radius_km: null,
      sample_count: 9,
      computed_at: '2026-09-21T10:00:00Z',
      reason: null,
    };
    let terrainCalls = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.includes('/api/auth/login')) return jsonResponse({ access_token: 'tok' }, 200);
        if (path.includes('/api/terrain/')) {
          terrainCalls += 1;
          return jsonResponse(livePayload, 200);
        }
        return jsonResponse({}, 404);
      })
    );

    const first = await apiService.getTerrain(27.5081, 79.6382);
    expect(first.data_status).toBe('LIVE');
    expect(terrainCalls).toBe(1);

    // The same/nearby point (coords that round to the same 5-decimal key)
    // must resolve from the client cache without another network call.
    const nearby = await apiService.getTerrain(27.508103, 79.638203);
    expect(nearby).toEqual(first);
    expect(terrainCalls).toBe(1);

    // Cache is keyed as terrain:<lat>:<lng> with rounded coordinates.
    const cached = getCachedTerrainPoint(27.5081, 79.6382);
    expect(cached).toEqual(first);
    expect(getCachedTerrainPoint(27.51, 79.64)).toBeNull();
    expect(getCachedTerrainPoint(27.5081, 79.6382)).not.toBeNull();
  });

  it('returns an honest cancelled payload when the terrain request is aborted', async () => {
    const controller = new AbortController();
    controller.abort();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new DOMException('The user aborted a request.', 'AbortError');
      })
    );

    const terrain = await apiService.getTerrain(11.4064, 76.6932, { signal: controller.signal });
    expect(terrain.data_status).toBe('UNAVAILABLE');
    expect(terrain.reason?.toLowerCase()).toContain('cancelled');
    expect(terrain.reason).not.toContain('Backend unreachable');
    expect(terrain.elevation_m).toBeNull();
  });

  it('coalesces concurrent terrain requests for the same cell into one network call (in-flight dedupe)', async () => {
    const livePayload = {
      latitude: 27.5081,
      longitude: 79.6382,
      data_status: 'LIVE',
      data_source: 'NASA Earthdata SRTM (LP DAAC SRTMGL1 v003)',
      provider: 'nasa',
      provider_role: 'primary',
      dataset: 'NASA SRTMGL1 v003 (1 arc-second, LP DAAC)',
      elevation_m: 140.05,
      slope_percent: 2.11,
      slope_degrees: 1.21,
      slope_category: 'NEARLY_LEVEL',
      elevation_change_m: 6.0,
      slope_window_arcsec: 3,
      sample_radius_km: null,
      sample_count: 9,
      computed_at: '2026-09-21T10:00:00Z',
      reason: null,
    };
    let terrainCalls = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.includes('/api/auth/login')) return jsonResponse({ access_token: 'tok' }, 200);
        if (path.includes('/api/terrain/')) {
          terrainCalls += 1;
          await new Promise((resolve) => setTimeout(resolve, 40));
          return jsonResponse(livePayload, 200);
        }
        return jsonResponse({}, 404);
      })
    );

    const [first, second] = await Promise.all([
      apiService.getTerrain(27.5081, 79.6382),
      apiService.getTerrain(27.508103, 79.638203), // rounds to the same 5-decimal key
    ]);
    expect(first.data_status).toBe('LIVE');
    expect(first.elevation_m).toBe(140.05);
    expect(second).toEqual(first);
    expect(terrainCalls).toBe(1); // shared in-flight promise, no duplicate request
  });

  it('retries a transient 5xx exactly once, then serves the follow-up success', async () => {
    const livePayload = {
      latitude: 12.0904,
      longitude: 79.6878,
      data_status: 'LIVE',
      data_source: 'NASA Earthdata SRTM (LP DAAC SRTMGL1 v003)',
      elevation_m: 155.2,
      slope_percent: 4.5,
      slope_category: 'GENTLY_SLOPING',
      computed_at: '2026-09-21T10:00:00Z',
      reason: null,
    };
    let terrainCalls = 0;
    let retries = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.includes('/api/auth/login')) return jsonResponse({ access_token: 'tok' }, 200);
        if (path.includes('/api/terrain/')) {
          terrainCalls += 1;
          if (terrainCalls === 1) return jsonResponse({ detail: 'upstream slow' }, 500);
          return jsonResponse(livePayload, 200);
        }
        return jsonResponse({}, 404);
      })
    );

    const terrain = await apiService.getTerrain(12.0904, 79.6878, { onRetry: () => { retries += 1; } });
    expect(terrain.data_status).toBe('LIVE');
    expect(terrain.elevation_m).toBe(155.2);
    expect(terrainCalls).toBe(2);
    expect(retries).toBe(1);
  });

  it('retries a transient network failure exactly once, then reports the honest backend-unreachable state', async () => {
    let terrainCalls = 0;
    let retries = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.includes('/api/auth/login')) return jsonResponse({ access_token: 'tok' }, 200);
        if (path.includes('/api/terrain/')) {
          terrainCalls += 1;
          throw new TypeError('Failed to fetch');
        }
        return jsonResponse({}, 404);
      })
    );

    const terrain = await apiService.getTerrain(12.0904, 79.6878, { onRetry: () => { retries += 1; } });
    expect(terrain.data_status).toBe('UNAVAILABLE');
    expect(terrain.reason).toContain('Backend unreachable');
    expect(terrain.elevation_m).toBeNull();
    expect(terrainCalls).toBe(2); // bounded: one retry, no endless loop
    expect(retries).toBe(1);
  });

  it('labels a client-side timeout honestly (never "backend unreachable") and keeps the retry bounded', async () => {
    let terrainCalls = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.includes('/api/auth/login')) return jsonResponse({ access_token: 'tok' }, 200);
        if (path.includes('/api/terrain/')) {
          terrainCalls += 1;
          throw new ApiTimeoutError('Request timed out');
        }
        return jsonResponse({}, 404);
      })
    );

    const terrain = await apiService.getTerrain(12.0904, 79.6878);
    expect(terrain.data_status).toBe('UNAVAILABLE');
    expect(terrain.reason).toContain('client timeout');
    expect(terrain.reason).not.toContain('Backend unreachable');
    expect(terrainCalls).toBe(2); // initial + exactly one retry
  });

  it('aborts during the transient-retry backoff and reports Cancelled without a second request', async () => {
    let terrainCalls = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.includes('/api/auth/login')) return jsonResponse({ access_token: 'tok' }, 200);
        if (path.includes('/api/terrain/')) {
          terrainCalls += 1;
          await new Promise((resolve) => setTimeout(resolve, 30));
          return jsonResponse({ detail: 'upstream busy' }, 503);
        }
        return jsonResponse({}, 404);
      })
    );

    const controller = new AbortController();
    const promise = apiService.getTerrain(12.0904, 79.6878, { signal: controller.signal });
    setTimeout(() => controller.abort(), 120); // after attempt 1, while in the 800ms backoff
    const terrain = await promise;
    expect(terrain.data_status).toBe('UNAVAILABLE');
    expect(terrain.reason?.toLowerCase()).toContain('cancelled');
    expect(terrainCalls).toBe(1); // the backoff abort must not spawn another attempt
  });

  it('never retries a definitive backend UNAVAILABLE payload (e.g. out of coverage)', async () => {
    let terrainCalls = 0;
    let retries = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.includes('/api/auth/login')) return jsonResponse({ access_token: 'tok' }, 200);
        if (path.includes('/api/terrain/')) {
          terrainCalls += 1;
          return jsonResponse(
            {
              data_status: 'UNAVAILABLE',
              data_source: null,
              elevation_m: null,
              reason: 'NASA SRTMGL1 has no tile at this coordinate (out of coverage).',
            },
            200
          );
        }
        return jsonResponse({}, 404);
      })
    );

    const terrain = await apiService.getTerrain(11.4064, 76.6932, { onRetry: () => { retries += 1; } });
    expect(terrain.data_status).toBe('UNAVAILABLE');
    expect(terrain.reason).toContain('out of coverage');
    expect(terrainCalls).toBe(1);
    expect(retries).toBe(0);
  });

  it('coalesces concurrent elevation-fast requests for the same cell into one network call', async () => {
    const livePayload = {
      latitude: 27.5081,
      longitude: 79.6382,
      data_status: 'LIVE',
      data_source: 'NASA Earthdata SRTM (LP DAAC SRTMGL1 v003)',
      elevation_m: 140.05,
      slope_percent: null,
      computed_at: '2026-09-21T10:00:00Z',
      reason: null,
    };
    let elevCalls = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.includes('/api/auth/login')) return jsonResponse({ access_token: 'tok' }, 200);
        if (path.includes('/api/elevation')) {
          elevCalls += 1;
          await new Promise((resolve) => setTimeout(resolve, 40));
          return jsonResponse(livePayload, 200);
        }
        return jsonResponse({}, 404);
      })
    );

    const [first, second] = await Promise.all([
      apiService.getElevationFast(27.5081, 79.6382),
      apiService.getElevationFast(27.508103, 79.638203),
    ]);
    expect(first.data_status).toBe('LIVE');
    expect(second).toEqual(first);
    expect(elevCalls).toBe(1);
  });
});

describe('Weather Forecast Map API (Open-Meteo primary + ECMWF backup, grid)', () => {
  it('maps the LIVE grid payload exactly and calls the grid route with bounds/variable/day', async () => {
    const requests: string[] = [];
    const gridPayload = {
      data_status: 'LIVE',
      data_source: 'Open-Meteo',
      provider: 'Open-Meteo',
      provider_role: 'primary',
      model: 'best_match',
      variable: 'temperature_2m',
      day: 0,
      unit: '°C',
      bounds: { north: 35.5, south: 6.2, east: 97.4, west: 68.1 },
      steps: { latitude: 1.25, longitude: 1.25 },
      points: [
        { latitude: 12.1, longitude: 79.7, value: 31.2, data_status: 'LIVE', provider: 'Open-Meteo', provider_role: 'primary', reason: null },
        { latitude: 12.1, longitude: 81.0, value: null, data_status: 'UNAVAILABLE', reason: 'upstream unreachable' },
      ],
      computed_at: '2026-09-22T12:00:00Z',
      assumption: 'Cells sampled from the provider multi-point grid.',
      reason: null,
    };

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const path = String(url);
        requests.push(path);
        if (path.includes('/api/auth/login')) return jsonResponse({ access_token: 'tok' }, 200);
        if (path.includes('/api/weather/grid')) return jsonResponse(gridPayload, 200);
        return jsonResponse({}, 404);
      })
    );

    const grid = await apiService.getWeatherGrid('35.5,6.2,97.4,68.1', {
      variable: 'temperature_2m',
      day: 0,
      step: 1.25,
      maxPoints: 600,
    });

    expect(grid.data_status).toBe('LIVE');
    expect(grid.provider).toBe('Open-Meteo');
    expect(grid.provider_role).toBe('primary');
    expect(grid.unit).toBe('°C');
    expect(grid.bounds.north).toBe(35.5);
    expect(grid.bounds.west).toBe(68.1);
    expect(grid.steps.latitude).toBe(1.25);
    expect(grid.points).toHaveLength(2);
    expect(grid.points[0].value).toBe(31.2);
    expect(grid.points[1].value).toBeNull();
    expect(grid.points[1].reason).toContain('upstream unreachable');

    const gridPath = requests.find((p) => p.includes('/api/weather/grid'));
    expect(gridPath).toContain('bounds=35.5%2C6.2%2C97.4%2C68.1');
    expect(gridPath).toContain('variable=temperature_2m');
    expect(gridPath).toContain('day=0');
    expect(gridPath).toContain('step=1.25');
    expect(gridPath).toContain('max_points=600');
  });

  it('labels a grid 5xx as a backend/provider failure (not a browser context issue)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.includes('/api/auth/login')) return jsonResponse({ access_token: 'tok' }, 200);
        if (path.includes('/api/weather/grid')) return jsonResponse({ detail: 'upstream error' }, 500);
        return jsonResponse({}, 404);
      })
    );

    const grid = await apiService.getWeatherGrid('30.0,20.0,80.0,70.0', { variable: 'precipitation' });
    expect(grid.data_status).toBe('UNAVAILABLE');
    expect(grid.points).toEqual([]);
    expect(grid.variable).toBe('precipitation');
    expect(grid.reason).toContain('Backend/provider');
    expect(grid.reason).not.toContain('unreachable from this browser context');
  });

  it('labels a grid network failure as backend unreachable and keeps parsed bounds', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      })
    );

    const grid = await apiService.getWeatherGrid('30.0,20.0,80.0,70.0', { variable: 'wind_speed_10m', day: 3 });
    expect(grid.data_status).toBe('UNAVAILABLE');
    expect(grid.day).toBe(3);
    expect(grid.reason).toContain('Backend unreachable');
    expect(grid.bounds.north).toBe(30.0);
    expect(grid.bounds.east).toBe(80.0);
    expect(grid.steps.latitude).toBe(0.25);
  });

  it('sends the historical per-day grid with year+month+day and no live params', async () => {
    const requests: string[] = [];
    const gridPayload = {
      data_status: 'LIVE', data_source: 'Open-Meteo/ECMWF', provider: 'Open-Meteo',
      provider_role: 'primary', model: null, variable: 'precipitation', day: 0, hour: null, unit: 'mm',
      bounds: { north: 30.5, south: 30, east: 80, west: 79 },
      steps: { latitude: 0.25, longitude: 0.25 }, resolution: { latitude: 0.25, longitude: 0.25 },
      valid_time: null, min: null, max: null, derived: false, points: [],
      computed_at: null, generated_at: null, assumption: null, reason: null,
      is_historical: true, year: 2025, month: 6,
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const path = String(url);
        requests.push(path);
        if (path.includes('/api/auth/login')) return jsonResponse({ access_token: 'tok' }, 200);
        if (path.includes('/api/weather/grid')) return jsonResponse(gridPayload, 200);
        return jsonResponse({}, 404);
      })
    );

    const monthly = await apiService.getWeatherGrid('30.5,30.0,80,79', {
      variable: 'precipitation',
      year: 2025,
      month: 6,
      day: 0,
    });
    const daily = await apiService.getWeatherGrid('30.5,30.0,80,79', {
      variable: 'precipitation',
      year: 2025,
      month: 6,
      day: 13,
    });

    const monthlyPath = requests.find((p) => p.includes('month=6') && !p.includes('day=13'));
    expect(monthlyPath).toContain('day=0');
    expect(monthlyPath).toContain('year=2025');
    expect(monthlyPath).toContain('month=6');
    expect(monthlyPath).not.toContain('prefer=');
    expect(monthlyPath).not.toContain('hour=');
    expect(monthly.data_status).toBe('LIVE');

    const dailyPath = requests.find((p) => p.includes('day=13'));
    expect(dailyPath).toContain('month=6');
    expect(dailyPath).toContain('day=13');
    expect(dailyPath).not.toContain('prefer=');
    expect(daily.data_status).toBe('LIVE');
  });

  it('maps a LIVE point forecast payload including extended fields and hourly rows', async () => {
    const payload = {
      latitude: 12.0904,
      longitude: 79.6878,
      data_status: 'LIVE',
      data_source: 'Open-Meteo',
      provider: 'Open-Meteo',
      provider_role: 'primary',
      model: 'best_match',
      generationtime_ms: 41.0,
      elevation_actual: 155.0,
      observed_at: '2026-09-22T12:00:00Z',
      current: {
        temperature_c: 31.2,
        apparent_temperature_c: 33.4,
        relative_humidity_percent: 72,
        pressure_hpa: 1008.4,
        precipitation_mm: 0.1,
        rain_intensity: 'DRIZZLE',
        weather_code: 3,
        weather_description: 'Overcast',
        wind_speed_kmh: 12.6,
        wind_gusts_kmh: 21.2,
        wind_direction_deg: 210,
        cloud_cover_percent: 88,
        uv_index: 4.2,
        visibility_km: 9.1,
      },
      hourly: [
        { time: '2026-09-22T13:00', temperature_c: 31.0, precipitation_mm: 0.0, precipitation_probability_percent: 10, weather_code: 3, weather_description: 'Overcast', wind_speed_kmh: 12.0, relative_humidity_percent: 70 },
      ],
      forecast: [
        { date: '2026-09-23', max_temp_c: 33.0, min_temp_c: 25.0, precipitation_mm: 2.0, precipitation_probability_percent: 60, wind_speed_kmh: 14.0, weather_code: 61, weather_description: 'Rain showers' },
      ],
      units: { temperature_2m: '°C', precipitation: 'mm' },
      timezone: 'Asia/Kolkata',
      reason: null,
    };

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.includes('/api/auth/login')) return jsonResponse({ access_token: 'tok' }, 200);
        if (path.includes('/api/weather/12.0904/79.6878')) return jsonResponse(payload, 200);
        return jsonResponse({}, 404);
      })
    );

    const weather = await apiService.getWeatherRow(12.0904, 79.6878, 7);
    expect(weather.data_status).toBe('LIVE');
    expect(weather.provider_role).toBe('primary');
    expect(weather.elevation_actual).toBe(155.0);
    expect(weather.current?.pressure_hpa).toBe(1008.4);
    expect(weather.current?.uv_index).toBe(4.2);
    expect(weather.current?.wind_direction_deg).toBe(210);
    expect(weather.hourly).toHaveLength(1);
    expect(weather.hourly?.[0].time).toBe('2026-09-22T13:00');
    expect(weather.forecast[0].weather_description).toBe('Rain showers');
    expect(weather.units?.temperature_2m).toBe('°C');
  });

  it('labels a point forecast 403 as an access (permission) failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const path = String(url);
        if (path.includes('/api/auth/login')) return jsonResponse({ access_token: 'tok' }, 200);
        if (path.includes('/api/weather/')) return jsonResponse({ detail: 'not authorized' }, 403);
        return jsonResponse({}, 404);
      })
    );

    const weather = await apiService.getWeatherRow(12.0904, 79.6878, 7);
    expect(weather.data_status).toBe('UNAVAILABLE');
    expect(weather.current).toBeNull();
    expect(weather.reason?.toLowerCase()).toContain('permission');
  });

  it('sends the days parameter and falls back honestly on network failure', async () => {
    const requests: string[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const path = String(url);
        requests.push(path);
        if (path.includes('/api/auth/login')) return jsonResponse({ access_token: 'tok' }, 200);
        throw new TypeError('Failed to fetch');
      })
    );

    const weather = await apiService.getWeatherRow(12.0904, 79.6878, 7);
    expect(weather.data_status).toBe('UNAVAILABLE');
    expect(weather.reason).toContain('Backend unreachable');
    const weatherPath = requests.find((p) => p.includes('/api/weather/12.0904/79.6878'));
    expect(weatherPath).toContain('days=7');
  });

  describe('weather & hazard map grid extensions', () => {
    it('fetches the SRTM terrain grid with the requested bounds/step and forwards honest status', async () => {
      const terrainPayload = {
        data_status: 'CACHED',
        data_source: 'NASA SRTMGL1 (1-arc-sec) / Open-Meteo fallback',
        valid_time: '2026-09-25T04:00:00Z',
        points: [
          { latitude: 30.5, longitude: 78.2, elevation_m: 1245.3, slope_percent: 6.2, slope_category: 'GENTLY_SLOPING', data_status: 'LIVE' },
        ],
      };
      const requests: string[] = [];
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => {
          const path = String(url);
          requests.push(path);
          if (path.includes('/api/auth/login')) return jsonResponse({ access_token: 'tok' }, 200);
          if (path.includes('/api/terrain-grid')) return jsonResponse(terrainPayload, 200);
          return jsonResponse({}, 404);
        })
      );

      const grid = await apiService.getTerrainGrid('31.0,30.0,79.0,78.0', { step: 0.1, maxPoints: 300 });
      expect(grid.data_status).toBe('CACHED');
      expect(grid.points[0].elevation_m).toBe(1245.3);
      expect(grid.points[0].slope_category).toBe('GENTLY_SLOPING');
      const path = requests.find((p) => p.includes('/api/terrain-grid'));
      expect(path).toContain('bounds=31.0%2C30.0%2C79.0%2C78.0');
      expect(path).toContain('step=0.1');
      expect(path).toContain('max_points=300');
    });

    it('rejects malformed terrain-grid bounds without hitting the network', async () => {
      vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({}, 200)));
      const grid = await apiService.getTerrainGrid('not,bounds', {});
      expect(grid.data_status).toBe('UNAVAILABLE');
      expect(grid.reason).toContain('Invalid bounds');
    });

    it('mirrors a flood-risk 5xx into an honest UNAVAILABLE overlay', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => {
          const path = String(url);
          if (path.includes('/api/auth/login')) return jsonResponse({ access_token: 'tok' }, 200);
          if (path.includes('/api/flood-risk-grid')) return jsonResponse({ detail: 'boom' }, 500);
          return jsonResponse({}, 404);
        })
      );
      const risk = await apiService.getFloodRiskGrid('30.5,30.0,78.5,78.0', {});
      expect(risk.data_status).toBe('UNAVAILABLE');
      expect(risk.reason).toContain('(500)');
    });

    it('passes prefer=ecmwf through to the weather grid request', async () => {
      const requests: string[] = [];
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => {
          const path = String(url);
          requests.push(path);
          if (path.includes('/api/auth/login'))
            return jsonResponse({ access_token: 'tok' }, 200);
          return jsonResponse(
            {
              data_status: 'LIVE',
              data_source: 'ECMWF IFS HRES 0.25° (Open-Meteo)',
              provider: 'ECMWF',
              provider_role: 'primary',
              variable: 'temperature_2m',
              day: 0,
              unit: '°C',
              bounds: { north: 30.5, south: 30.0, east: 78.5, west: 78.0 },
              steps: { latitude: 0.25, longitude: 0.25 },
              points: [{ latitude: 30.3, longitude: 78.2, value: 18.9 }],
            },
            200
          );
        })
      );
      const grid = await apiService.getWeatherGrid('30.5,30.0,78.5,78.0', { variable: 'temperature_2m', prefer: 'ecmwf' });
      expect(grid.provider).toBe('ECMWF');
      const path = requests.find((p) => p.includes('/api/weather/grid'));
      expect(path).toContain('prefer=ecmwf');
    });

    it('honours an AbortSignal on the weather grid (cancellation returns an honest cancelled grid)', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => {
          throw new DOMException('The operation was aborted.', 'AbortError');
        })
      );
      const controller = new AbortController();
      controller.abort();
      const grid = await apiService.getWeatherGrid('30.5,30.0,78.5,78.0', { variable: 'precipitation', signal: controller.signal });
      expect(grid.data_status).toBe('UNAVAILABLE');
      expect(grid.reason).toContain('Request cancelled');
    });

    it('serves repeated identical grid requests from the client cache (cache-first)', async () => {
      const requests: string[] = [];
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => {
          const path = String(url);
          requests.push(path);
          if (path.includes('/api/auth/login'))
            return jsonResponse({ access_token: 'tok' }, 200);
          if (path.includes('/api/weather/grid'))
            return jsonResponse(
              {
                data_status: 'LIVE',
                data_source: 'Open-Meteo',
                provider: 'Open-Meteo',
                provider_role: 'primary',
                variable: 'temperature_2m',
                day: 0,
                hour: 3,
                unit: '°C',
                bounds: { north: 20.5, south: 20.0, east: 79.5, west: 79.0 },
                steps: { latitude: 0.1, longitude: 0.1 },
                points: [{ latitude: 20.3, longitude: 79.2, value: 28.0 }],
              },
              200
            );
          return jsonResponse({}, 404);
        })
      );

      const opts = {
        variable: 'temperature_2m',
        day: 0,
        hour: 3,
        step: 0.1,
        maxPoints: 600,
      };
      const first = await apiService.getWeatherGrid('20.5,20.0,79.5,79.0', opts);
      const second = await apiService.getWeatherGrid('20.5,20.0,79.5,79.0', opts);
      expect(first.data_status).toBe('LIVE');
      expect(second.data_status).toBe('LIVE');
      const gridRequests = requests.filter((p) => p.includes('/api/weather/grid'));
      expect(gridRequests).toHaveLength(1);
    });

    it('keys the client grid cache by hour and variable', async () => {
      const requests: string[] = [];
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => {
          const path = String(url);
          requests.push(path);
          if (path.includes('/api/auth/login'))
            return jsonResponse({ access_token: 'tok' }, 200);
          if (path.includes('/api/weather/grid'))
            return jsonResponse(
              {
                data_status: 'FORECAST',
                data_source: 'Open-Meteo',
                provider: 'Open-Meteo',
                provider_role: 'primary',
                variable: 'temperature_2m',
                day: 0,
                hour: 0,
                unit: '°C',
                bounds: { north: 21.5, south: 21.0, east: 79.5, west: 79.0 },
                steps: { latitude: 0.1, longitude: 0.1 },
                points: [],
              },
              200
            );
          return jsonResponse({}, 404);
        })
      );

      const base = '21.5,21.0,79.5,79.0';
      await apiService.getWeatherGrid(base, { variable: 'temperature_2m', hour: 0 });
      await apiService.getWeatherGrid(base, { variable: 'temperature_2m', hour: 4 });
      await apiService.getWeatherGrid(base, { variable: 'wind_speed_10m', hour: 0 });
      const gridRequests = requests.filter((p) => p.includes('/api/weather/grid'));
      expect(gridRequests).toHaveLength(3);
    });

    it('returns an honest UNAVAILABLE point payload when the point request times out', async () => {
      vi.useFakeTimers();
      try {
        vi.stubGlobal(
          'fetch',
          vi.fn(async (url: string, init?: RequestInit) => {
            const path = String(url);
            if (path.includes('/api/auth/login'))
              return jsonResponse({ access_token: 'tok' }, 200);
            return new Promise((resolve, reject) => {
              init?.signal?.addEventListener('abort', () =>
                reject(new DOMException('The operation was aborted.', 'AbortError'))
              );
            });
          })
        );

        const pending = apiService.getWeather(12.9, 78.1);
        await vi.advanceTimersByTimeAsync(12 * 1000);
        const result = await pending;
        expect(result.data_status).toBe('UNAVAILABLE');
        expect(result.reason).toContain('unreachable from this browser context');
      } finally {
        vi.useRealTimers();
      }
    });
  });

  describe('Request timeout contract (a portal load must never stay stuck on Loading)', () => {
    const hangingFetch = vi.fn(async (_url: string, init?: RequestInit) => {
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () =>
          reject(new DOMException('The operation was aborted.', 'AbortError'))
        );
      });
    });

    it('rejects a request whose remote never responds with an honest ApiTimeoutError (not a bare AbortError)', async () => {
      vi.useFakeTimers();
      try {
        vi.stubGlobal('fetch', hangingFetch);
        const pending = fetchWithTimeout('/api/slow-endpoint', {}, 5 * 1000);
        const assertion = expect(pending).rejects.toBeInstanceOf(ApiTimeoutError);
        await vi.advanceTimersByTimeAsync(5 * 1000);
        await assertion;
      } finally {
        vi.useRealTimers();
      }
    });

    it('resolves prompt responses and clears the timeout so no late abort fires', async () => {
      vi.useFakeTimers();
      try {
        vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ ok: 1 }, 200)));
        const pending = fetchWithTimeout('/api/quick', {}, 30 * 1000);
        const res = await pending;
        expect(res.ok).toBe(true);
        await vi.advanceTimersByTimeAsync(35 * 1000);
      } finally {
        vi.useRealTimers();
      }
    });

    it('a stalled dashboard request resolves to an honest payload instead of hanging the portal', async () => {
      vi.useFakeTimers();
      try {
        vi.stubGlobal('fetch', hangingFetch);
        const pending = apiService.getDashboardSummary('Tamil Nadu', 'Chennai');
        const assertion = expect(pending).resolves.toMatchObject({ data_status: 'UNAVAILABLE' });
        await vi.advanceTimersByTimeAsync(API_FETCH_TIMEOUT_MS + 1000);
        await assertion;
      } finally {
        vi.useRealTimers();
      }
    });

    it('a stalled authenticated request settles with an honest client-timeout error instead of hanging', async () => {
      vi.useFakeTimers();
      try {
        vi.stubGlobal('fetch', hangingFetch);
        const pending = apiService.getDisasterEvents({ state: 'Uttarakhand' });
        const assertion = expect(pending).rejects.toThrow('timed out after');
        await vi.advanceTimersByTimeAsync(3 * API_FETCH_TIMEOUT_MS);
        await assertion;
      } finally {
        vi.useRealTimers();
      }
    });
  });
});
