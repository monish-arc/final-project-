// Data-domain clipping for weather grid requests.
//
// The backend weather grid (Open-Meteo / ECMWF via Open-Meteo) only holds data
// over India's service window. MAP bounds are whatever the user pans to — that
// is the happy global view. DATA bounds are clipped here BEFORE the request so
// the backend never receives degenerate/invalid bounds and a global view still
// pulls the full Indian window instead of erroring out. Views entirely outside
// the data domain are reported honestly (empty grid, not fabricated cells).

export const WEATHER_DATA_BOUNDS = {
  north: 37.4,
  south: 6.0,
  east: 98.5,
  west: 68.0,
} as const;

export interface ClipWeatherBoundsResult {
  /** 'north,south,east,west' clipped to the data domain, or null when the
   *  requested area has no overlap with India. */
  clipped: string | null;
  north: number;
  south: number;
  east: number;
  west: number;
  clippedNorth: number;
  clippedSouth: number;
  clippedEast: number;
  clippedWest: number;
  /** true when at least one edge was moved inward to the data domain. */
  clippedToDataDomain: boolean;
  /** true when the requested area lies entirely outside the data domain. */
  entirelyOutside: boolean;
}

export function clipWeatherGridBounds(bounds: string): ClipWeatherBoundsResult {
  const parts = bounds.split(',').map((part) => Number(part));
  const [north, south, east, west] = [parts[0], parts[1], parts[2], parts[3]];
  if (![north, south, east, west].every(Number.isFinite)) {
    return {
      clipped: null,
      north, south, east, west,
      clippedNorth: north, clippedSouth: south, clippedEast: east, clippedWest: west,
      clippedToDataDomain: false,
      entirelyOutside: true,
    };
  }
  const clippedNorth = Math.min(north, WEATHER_DATA_BOUNDS.north);
  const clippedSouth = Math.max(south, WEATHER_DATA_BOUNDS.south);
  const clippedEast = Math.min(east, WEATHER_DATA_BOUNDS.east);
  const clippedWest = Math.max(west, WEATHER_DATA_BOUNDS.west);
  const entirelyOutside = clippedNorth <= clippedSouth || clippedEast <= clippedWest;
  return {
    clipped: entirelyOutside
      ? null
      : `${clippedNorth},${clippedSouth},${clippedEast},${clippedWest}`,
    north,
    south,
    east,
    west,
    clippedNorth,
    clippedSouth,
    clippedEast,
    clippedWest,
    clippedToDataDomain:
      clippedNorth !== north || clippedSouth !== south || clippedEast !== east || clippedWest !== west,
    entirelyOutside,
  };
}