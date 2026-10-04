import { describe, expect, it } from 'vitest';
import {
  DEFAULT_RASTER_OPACITY,
  RASTER_OPACITY_PRESETS,
  gridRasterGeometry,
  rasterOpacityValue,
  toOpaqueColor,
  paintGridRaster,
} from './WeatherGridRaster';

const INDIA_LIKE = { north: 37, south: 8, east: 97, west: 68 };

describe('gridRasterGeometry', () => {
  it('derives column/row counts from bounds and step', () => {
    // 29 deg of longitude at 0.25 deg steps => 116 columns, likewise for rows.
    expect(gridRasterGeometry(INDIA_LIKE, 0.25, 0.25)).toEqual({ cols: 116, rows: 116 });
  });

  it('handles the flood layer 0.3 deg step', () => {
    expect(gridRasterGeometry(INDIA_LIKE, 0.3, 0.3)).toEqual({ cols: 97, rows: 97 });
  });

  it('rejects a zero step', () => {
    expect(gridRasterGeometry(INDIA_LIKE, 0, 0.25)).toBeNull();
    expect(gridRasterGeometry(INDIA_LIKE, 0.25, 0)).toBeNull();
  });

  it('normalises a negative step rather than rejecting it', () => {
    // Some providers report a negative step; only the magnitude is meaningful.
    expect(gridRasterGeometry(INDIA_LIKE, -0.25, -0.25)).toEqual({ cols: 116, rows: 116 });
  });

  it('rejects non-finite bounds', () => {
    expect(gridRasterGeometry({ north: NaN, south: 8, east: 97, west: 68 }, 0.25, 0.25)).toBeNull();
  });

  it('rejects inverted bounds', () => {
    expect(gridRasterGeometry({ north: 8, south: 37, east: 97, west: 68 }, 0.25, 0.25)).toBeNull();
    expect(gridRasterGeometry({ north: 37, south: 8, east: 68, west: 97 }, 0.25, 0.25)).toBeNull();
  });

  it('refuses an oversized canvas instead of trying to allocate it', () => {
    // 360x180 at 0.0001 deg would be 6.48 billion pixels.
    expect(gridRasterGeometry({ north: 90, south: -90, east: 180, west: -180 }, 0.0001, 0.0001)).toBeNull();
  });

  it('always produces at least one pixel for a tiny window', () => {
    expect(gridRasterGeometry({ north: 10, south: 9.99, east: 70.01, west: 70 }, 0.25, 0.25)).toEqual({
      cols: 1,
      rows: 1,
    });
  });
});

describe('toOpaqueColor', () => {
  it('strips alpha from rgba colours so layer opacity alone controls visibility', () => {
    // Flood palette values carry alpha (0.38-0.55); compounding that with a 0.3
    // layer opacity would make the overlay effectively invisible.
    expect(toOpaqueColor('rgba(39,174,96,0.38)')).toBe('rgb(39, 174, 96)');
    expect(toOpaqueColor('rgba(192,57,43,0.55)')).toBe('rgb(192, 57, 43)');
  });

  it('normalises integer alpha and rgb() without alpha', () => {
    expect(toOpaqueColor('rgba(230,126,34,1)')).toBe('rgb(230, 126, 34)');
    expect(toOpaqueColor('rgb(15,23,42)')).toBe('rgb(15, 23, 42)');
  });

  it('leaves hex colours untouched', () => {
    expect(toOpaqueColor('#facc15')).toBe('#facc15');
  });
});

describe('raster opacity presets', () => {
  it('offers Off / Low(30%) / Medium(60%) / High(85%)', () => {
    expect(RASTER_OPACITY_PRESETS.map((p) => p.value)).toEqual([0, 0.3, 0.6, 0.85]);
  });

  it('defaults to the light wash so the street map stays readable', () => {
    expect(DEFAULT_RASTER_OPACITY).toBe('low');
    expect(rasterOpacityValue(DEFAULT_RASTER_OPACITY)).toBe(0.3);
  });

  it('maps Off to a fully hidden overlay', () => {
    expect(rasterOpacityValue('off')).toBe(0);
  });
});

describe('paintGridRaster', () => {
  it('returns null when every cell is no-data', () => {
    const cells = [
      { lat: 10, lng: 70, color: null },
      { lat: 10.25, lng: 70.25, color: null },
    ];
    expect(paintGridRaster(cells, INDIA_LIKE, 0.25, 0.25)).toBeNull();
  });

  it('returns null for an empty cell list', () => {
    expect(paintGridRaster([], INDIA_LIKE, 0.25, 0.25)).toBeNull();
  });

  it('returns null when the geometry is unusable', () => {
    const cells = [{ lat: 10, lng: 70, color: '#fff' }];
    expect(paintGridRaster(cells, INDIA_LIKE, 0, 0)).toBeNull();
  });
});