import { Habitation, RegionSelection } from '../types';

export interface RegionViewportFocus {
  lat: number;
  lng: number;
  zoom: number;
  /** South, West, North, East bounding box — preferred over center+zoom when present. */
  bounds?: [number, number, number, number];
  /** Monotonic key to force a re-fly even for identical targets. */
  key: string;
  label: string;
  /** Habitation id when the target resolves to a known habitation record. */
  habitationId?: string;
  /**
   * True when the map was centred on an approximate cached landmark because the
   * selected location could not be geocoded. Approximate anchors must NEVER be
   * used to fetch provider data — the app reports "Data unavailable" instead.
   */
  approximate?: boolean;
}

interface GeoPoint {
  lat: number;
  lng: number;
  zoom: number;
}

// Approximate centroids for all 36 LGD states/UTs (offline, zoom ~6 pan target).
// Keyed by LGD state code — see src/data/regions/hierarchy.ts.
export const STATE_CENTROIDS: Record<number, GeoPoint> = {
  35: { lat: 11.74, lng: 92.66, zoom: 6 }, // Andaman And Nicobar Islands
  28: { lat: 15.91, lng: 79.74, zoom: 6 }, // Andhra Pradesh
  12: { lat: 28.22, lng: 94.73, zoom: 6 }, // Arunachal Pradesh
  18: { lat: 26.2, lng: 92.94, zoom: 6 }, // Assam
  10: { lat: 25.59, lng: 85.14, zoom: 6 }, // Bihar
  4: { lat: 30.73, lng: 76.78, zoom: 11 }, // Chandigarh
  22: { lat: 21.3, lng: 81.63, zoom: 6 }, // Chhattisgarh
  7: { lat: 28.61, lng: 77.21, zoom: 10 }, // Delhi
  30: { lat: 15.3, lng: 74.12, zoom: 9 }, // Goa
  24: { lat: 22.26, lng: 71.19, zoom: 6 }, // Gujarat
  6: { lat: 29.06, lng: 76.09, zoom: 7 }, // Haryana
  2: { lat: 31.1, lng: 77.17, zoom: 7 }, // Himachal Pradesh
  1: { lat: 33.78, lng: 76.58, zoom: 6 }, // Jammu And Kashmir
  20: { lat: 23.61, lng: 85.28, zoom: 6 }, // Jharkhand
  29: { lat: 15.32, lng: 75.71, zoom: 6 }, // Karnataka
  32: { lat: 10.5, lng: 76.34, zoom: 7 }, // Kerala
  37: { lat: 34.1, lng: 77.6, zoom: 6 }, // Ladakh
  31: { lat: 10.6, lng: 72.63, zoom: 8 }, // Lakshadweep
  23: { lat: 23.47, lng: 77.95, zoom: 6 }, // Madhya Pradesh
  27: { lat: 19.75, lng: 75.71, zoom: 6 }, // Maharashtra
  14: { lat: 24.82, lng: 93.94, zoom: 7 }, // Manipur
  17: { lat: 25.47, lng: 91.37, zoom: 7 }, // Meghalaya
  15: { lat: 23.16, lng: 92.94, zoom: 7 }, // Mizoram
  13: { lat: 26.16, lng: 94.56, zoom: 7 }, // Nagaland
  21: { lat: 20.95, lng: 85.1, zoom: 6 }, // Odisha
  34: { lat: 11.94, lng: 79.81, zoom: 9 }, // Puducherry
  3: { lat: 31.15, lng: 75.34, zoom: 7 }, // Punjab
  8: { lat: 27.39, lng: 73.43, zoom: 6 }, // Rajasthan
  11: { lat: 27.53, lng: 88.51, zoom: 8 }, // Sikkim
  33: { lat: 11.13, lng: 78.66, zoom: 6 }, // Tamil Nadu
  36: { lat: 18.11, lng: 79.02, zoom: 6 }, // Telangana
  38: { lat: 20.18, lng: 73.02, zoom: 9 }, // Dadra And Nagar Haveli And Daman And Diu
  16: { lat: 23.94, lng: 91.99, zoom: 7 }, // Tripura
  9: { lat: 26.85, lng: 80.95, zoom: 6 }, // Uttar Pradesh
  5: { lat: 30.07, lng: 79.02, zoom: 7 }, // Uttarakhand
  19: { lat: 22.99, lng: 87.86, zoom: 6 }, // West Bengal
};

// Approximate centroid for the all-India overview (used when no region is
// selected — the application lands on a nationwide disaster overview).
export const INDIA_OVERVIEW: RegionViewportFocus = {
  lat: 22.5,
  lng: 78.9,
  zoom: 5,
  bounds: [6.2, 68.1, 35.5, 97.4],
  key: '',
  label: 'All of India',
};

// LGD code hints that an offline centroid is a coarse approximation only.
// The offline table is used solely to centre the map when geocoding is
// unreachable — never as a source location for live data.

const GEO_CACHE_KEY = 'namsafe-region-geocode-cache';

function normalizeName(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().replace(/\s+/g, ' ');
}

interface GeocodeCacheEntry {
  lat: number;
  lng: number;
  zoom: number;
  bounds?: [number, number, number, number];
}

function readGeocodeCache(): Record<string, GeocodeCacheEntry> {
  try {
    const raw = localStorage.getItem(GEO_CACHE_KEY);
    return raw ? (JSON.parse(raw) as Record<string, GeocodeCacheEntry>) : {};
  } catch {
    return {};
  }
}

function writeGeocodeCache(cache: Record<string, GeocodeCacheEntry>) {
  try {
    localStorage.setItem(GEO_CACHE_KEY, JSON.stringify(cache));
  } catch {
    // ignore quota / private-mode failures
  }
}

interface GeocodeResultItem {
  latitude?: number;
  longitude?: number;
  lat?: string;
  lon?: string;
  boundingbox?: [string, string, string, string];
  display_name?: string;
}

function readAuthToken(): string | null {
  try {
    return localStorage.getItem('nammasafe_access_token');
  } catch {
    return null;
  }
}

function withTimeout(url: string, init: RequestInit, ms: number): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  return fetch(url, { ...init, signal: controller.signal }).finally(() => clearTimeout(timer));
}

// Resolves a query to a point using the backend geocode proxy first (cached,
// rate-limited, country-scoped), falling back to a direct Nominatim call for the
// SAME query when the proxy is unreachable/unauthenticated. Both targets geocode
// the selected location — neither substitutes another location's data.
async function geocodeRegion(query: string, zoom: number): Promise<GeocodeCacheEntry | null> {
  const cache = readGeocodeCache();
  const cached = cache[query];
  if (cached) return cached;

  const adopt = (item: GeocodeResultItem): GeocodeCacheEntry => {
    const lat = item.latitude ?? (item.lat ? parseFloat(item.lat) : NaN);
    const lng = item.longitude ?? (item.lon ? parseFloat(item.lon) : NaN);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null as unknown as GeocodeCacheEntry;
    const entry: GeocodeCacheEntry = {
      lat,
      lng,
      zoom,
      bounds: item.boundingbox
        ? [
            parseFloat(item.boundingbox[0]),
            parseFloat(item.boundingbox[2]),
            parseFloat(item.boundingbox[1]),
            parseFloat(item.boundingbox[3]),
          ]
        : undefined,
    };
    cache[query] = entry;
    writeGeocodeCache(cache);
    return entry;
  };

  // 1) Backend proxy (/api/geocode → Nominatim, cached + rate-limited).
  const token = readAuthToken();
  try {
    const res = await withTimeout(
      `/api/geocode?format=json&limit=1&q=${encodeURIComponent(query)}&country=in`,
      {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      },
      8000
    );
    if (res.ok) {
      const payload = (await res.json()) as { places?: GeocodeResultItem[]; data_status?: string };
      const first = payload.places?.[0];
      if (first && payload.data_status !== 'UNAVAILABLE') {
        return adopt(first);
      }
    }
  } catch {
    // fall through to direct Nominatim
  }

  // 2) Direct Nominatim (same query — never a different location).
  try {
    const res = await withTimeout(
      'https://nominatim.openstreetmap.org/search?format=json&limit=1&q=' +
        encodeURIComponent(query),
      { headers: { Accept: 'application/json' } },
      8000
    );
    if (!res.ok) return null;
    const results = (await res.json()) as GeocodeResultItem[];
    if (!results.length) return null;
    return adopt(results[0]);
  } catch {
    return null;
  }
}

function makeFocus(
  point: { lat: number; lng: number; zoom: number; bounds?: [number, number, number, number] },
  label: string,
  habitationId?: string
): RegionViewportFocus {
  return {
    lat: point.lat,
    lng: point.lng,
    zoom: point.zoom,
    bounds: point.bounds,
    key: '',
    label,
    habitationId,
  };
}

export interface FocusTargetInput {
  lat?: number;
  lng?: number;
  zoom?: number;
  bounds?: [number, number, number, number];
}

// Builder for an explicit map-focus request (key stamped by the caller so
// repeated targets still retrigger the fly animation).
export function buildFocus(
  target: FocusTargetInput,
  label: string,
  habitationId?: string
): RegionViewportFocus {
  return {
    lat: target.lat ?? 0,
    lng: target.lng ?? 0,
    zoom: target.zoom ?? 10,
    bounds: target.bounds,
    key: '',
    label,
    habitationId,
  };
}

interface LatLngInput {
  latitude: number;
  longitude: number;
}

// Bounds focus computed from a list of points (route polylines, alerts, etc.).
// Degenerate (single-point) inputs fall back to a centered point focus.
export function focusFromPoints(
  points: LatLngInput[],
  fallback: { lat: number; lng: number; zoom: number },
  label: string
): RegionViewportFocus | null {
  if (points.length === 0) return null;
  const lats = points.map((p) => p.latitude);
  const lngs = points.map((p) => p.longitude);
  const bounds: [number, number, number, number] = [
    Math.min(...lats),
    Math.min(...lngs),
    Math.max(...lats),
    Math.max(...lngs),
  ];
  const spanLat = bounds[2] - bounds[0];
  const spanLng = bounds[3] - bounds[1];
  if (spanLat < 1e-5 && spanLng < 1e-5) {
    return buildFocus(
      { lat: bounds[0], lng: bounds[1], zoom: Math.max(fallback.zoom, 14) },
      label
    );
  }
  return buildFocus(
    { lat: (bounds[0] + bounds[2]) / 2, lng: (bounds[1] + bounds[3]) / 2, zoom: 11, bounds },
    label
  );
}

// Resolves the current region selection to its ACTUAL latitude/longitude via
// geocoding. The selected location is the single source of truth: the returned
// coordinates drive every live-data request. Returns null when the location
// cannot be resolved; a state-only selection may return an approximate map
// centre (approximate: true) that must NOT be used to fetch provider data.
export async function resolveRegionViewport(
  region: RegionSelection,
  habitations: Habitation[]
): Promise<RegionViewportFocus | null> {
  // No region selected → all-India overview (national landing).
  if (!region.state) {
    return { ...INDIA_OVERVIEW };
  }

  const stateName = region.state?.name ?? '';
  const districtName = region.district?.name ?? '';
  const subDistrictName = region.subDistrict?.name ?? '';

  // Rich "Village, District, State, India" query priority: the more specific the
  // selection, the more specific the geocode hit.
  const queryParts = [region.place?.[1], subDistrictName, districtName, stateName, 'India'].filter(
    Boolean
  );
  const query = queryParts.join(', ');
  const zoom = region.place ? 14 : region.subDistrict ? 12 : region.district ? 10 : 7;
  const label = region.place?.[1] ?? subDistrictName ?? districtName ?? stateName;

  const geo = await geocodeRegion(query, zoom);
  if (geo) {
    let habitationId: string | undefined;
    if (region.place) {
      const placeName = normalizeName(region.place[1]);
      const match = habitations.find(
        (h) => normalizeName(h.village_name) === placeName || normalizeName(h.village_name).includes(placeName)
      );
      habitationId = match?.id;
    }
    return makeFocus(
      { lat: geo.lat, lng: geo.lng, zoom: geo.zoom, bounds: geo.bounds },
      label,
      habitationId
    );
  }

  // Offline last resort — centre the map only, never fetch live data from a
  // hard-coded coordinate. Only honoured for a state-level (coarse) selection.
  if (region.state && !region.district && !region.subDistrict && !region.place) {
    const centroid = STATE_CENTROIDS[region.state.code];
    if (centroid) {
      return { ...makeFocus(centroid, stateName), approximate: true };
    }
  }

  return null;
}