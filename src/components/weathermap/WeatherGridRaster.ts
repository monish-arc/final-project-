/**
 * Grid raster rendering for the Weather & Hazard Map.
 *
 * The weather and flood layers used to draw one SVG `L.rectangle` per grid
 * cell. Over India at 0.25 deg that is ~13,000 rectangles (and ~9,400 more for
 * the flood layer at 0.3 deg). That has three bad effects:
 *
 *   1. At the fill opacities used, the cells blanket the OpenStreetMap base
 *      tiles, so roads, place names and the outline of India disappear and the
 *      map reads as a flat block of colour rather than a map.
 *   2. Every cell carried a popup and a click handler, so the cell layer
 *      swallowed map clicks and the point picker could not be used.
 *   3. Thousands of SVG nodes saturate the main thread, which makes pinch-zoom
 *      and dragging stutter on mobile until the map feels like a static image.
 *
 * Instead we paint the same values into a single 1px-per-cell canvas and hand
 * Leaflet one `L.imageOverlay`. Same colours, same geometry, one DOM node, and
 * the overlay is non-interactive so map interaction passes straight through.
 *
 * The grid is a regular latitude/longitude lattice; `L.imageOverlay` maps an
 * image linearly in Web Mercator projected space, so the raster is very slightly
 * non-linear in latitude. Across India (roughly 8-37 N) that error is far below
 * one grid cell and is not perceptible.
 */

export interface RasterBounds {
  north: number;
  south: number;
  east: number;
  west: number;
}

export interface RasterCell {
  lat: number;
  lng: number;
  /** null means "no data" and is painted fully transparent. */
  color: string | null;
}

export interface RasterGeometry {
  cols: number;
  rows: number;
}

export interface GridRaster {
  url: string;
  bounds: RasterBounds;
  cols: number;
  rows: number;
}

/** Refuse to build a canvas larger than this; guards against a pathological
 *  bounds/step combination asking for hundreds of megapixels. */
const MAX_RASTER_PIXELS = 4_000_000;

/** Smallest usable cell count, so a degenerate request cannot throw. */
const MIN_RASTER_PIXELS = 1;

/**
 * Number of raster columns/rows needed to cover `bounds` at the given step.
 * Pure and DOM-free so it can be unit tested directly.
 */
export function gridRasterGeometry(
  bounds: RasterBounds,
  stepLat: number,
  stepLng: number
): RasterGeometry | null {
  const latStep = Math.abs(stepLat);
  const lngStep = Math.abs(stepLng);
  if (!Number.isFinite(latStep) || !Number.isFinite(lngStep)) return null;
  if (latStep <= 0 || lngStep <= 0) return null;

  const { north, south, east, west } = bounds;
  if (![north, south, east, west].every((v) => Number.isFinite(v))) return null;
  if (north <= south || east <= west) return null;

  const cols = Math.max(MIN_RASTER_PIXELS, Math.round((east - west) / lngStep));
  const rows = Math.max(MIN_RASTER_PIXELS, Math.round((north - south) / latStep));
  if (cols * rows > MAX_RASTER_PIXELS) return null;

  return { cols, rows };
}

/**
 * Paint `cells` into a single canvas and return it as a data URL together with
 * the bounds it covers. Returns null when there is nothing to draw, when the
 * geometry is degenerate, or when no DOM canvas is available (e.g. SSR/tests).
 */
export function paintGridRaster(
  cells: readonly RasterCell[],
  bounds: RasterBounds,
  stepLat: number,
  stepLng: number
): GridRaster | null {
  const drawable = cells.filter((c) => c.color != null);
  if (drawable.length === 0) return null;

  const geometry = gridRasterGeometry(bounds, stepLat, stepLng);
  if (!geometry) return null;

  if (typeof document === 'undefined' || typeof document.createElement !== 'function') {
    return null;
  }

  const { cols, rows } = geometry;
  const canvas = document.createElement('canvas');
  canvas.width = cols;
  canvas.height = rows;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;

  ctx.clearRect(0, 0, cols, rows);

  const { north, south, east, west } = bounds;
  for (const cell of cells) {
    if (cell.color == null) continue;
    if (!Number.isFinite(cell.lat) || !Number.isFinite(cell.lng)) continue;

    // Column/row of the cell's lattice position. Row 0 is the northern edge so
    // the raster is north-up, matching how the grid values are indexed.
    const col = Math.round((cell.lng - west) / Math.abs(stepLng));
    const row = Math.round((north - cell.lat) / Math.abs(stepLat));
    if (col < 0 || col >= cols || row < 0 || row >= rows) continue;

    ctx.fillStyle = cell.color;
    ctx.fillRect(col, row, 1, 1);
  }

  return { url: canvas.toDataURL('image/png'), bounds, cols, rows };
}

/**
 * Strip any alpha from a colour so the raster is painted fully opaque and
 * visibility is governed solely by the layer opacity control.
 *
 * This matters for the flood layer: `FLOOD_RISK_COLORS` already carries alpha
 * (0.38-0.55) for the old per-cell rectangles. Painting those into the canvas
 * and then applying a 0.3 layer opacity would compound to roughly 0.11 and the
 * flood overlay would all but disappear.
 */
export function toOpaqueColor(color: string): string {
  const match = color.trim().match(/^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)/i);
  if (!match) return color;
  const [, r, g, b] = match;
  return `rgb(${Math.round(Number(r))}, ${Math.round(Number(g))}, ${Math.round(Number(b))})`;
}

/** Opacity presets offered for the raster overlay. `off` hides the raster
 *  entirely so the base map is completely unobstructed. */
export const RASTER_OPACITY_PRESETS = [
  { id: 'off', label: 'Off', value: 0 },
  { id: 'low', label: 'Low (30%)', value: 0.3 },
  { id: 'medium', label: 'Medium (60%)', value: 0.6 },
  { id: 'high', label: 'High (85%)', value: 0.85 },
] as const;

export type RasterOpacityId = (typeof RASTER_OPACITY_PRESETS)[number]['id'];

export const DEFAULT_RASTER_OPACITY: RasterOpacityId = 'low';

export function rasterOpacityValue(id: RasterOpacityId): number {
  const preset = RASTER_OPACITY_PRESETS.find((p) => p.id === id);
  return preset ? preset.value : 0.3;
}