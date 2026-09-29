import { describe, it, expect } from 'vitest';
import {
  WEATHER_LAYERS,
  WEATHER_LAYER_ORDER,
  HAZARD_LAYERS,
  TERRAIN_LAYERS,
  colorForValue,
  interpolateRamp,
  formatVariableValue,
  variableLabel,
  FLOOD_RISK_COLORS,
  RAINFALL_STOPS,
  RAINFALL_COLORS,
  legendTickLabels,
  isHistoricalVariableAvailable,
  HISTORICAL_GRID_VARIABLES,
  HISTORICAL_PER_DAY_VARIABLES,
} from './weatherLayers';

describe('weather layer metadata & colour mapping', () => {
  it('includes all grid weather variables with palettes', () => {
    const ids = Object.keys(WEATHER_LAYERS);
    expect(ids).toContain('temperature_2m');
    expect(ids).toContain('wind_speed_10m');
    expect(ids).toContain('wind_direction_10m');
    expect(ids).toContain('wind_u');
    expect(ids).toContain('wind_v');
    expect(ids).toContain('apparent_temperature');
    expect(ids).toContain('visibility');
    expect(ids).toContain('storm_indicator');
    for (const meta of Object.values(WEATHER_LAYERS)) {
      expect(meta.colors.length).toBeGreaterThan(0);
      expect(meta.domain[0]).toBeLessThan(meta.domain[1]);
    }
  });

  it('clamps value colour mapping to the domain edges', () => {
    expect(colorForValue(-999, WEATHER_LAYERS.temperature_2m)).toBe(
      WEATHER_LAYERS.temperature_2m.colors[0]
    );
    expect(colorForValue(999, WEATHER_LAYERS.temperature_2m)).toBe(
      WEATHER_LAYERS.temperature_2m.colors[WEATHER_LAYERS.temperature_2m.colors.length - 1]
    );
  });

  it('interpolates continuous ramps (elevation) monotonically', () => {
    const low = interpolateRamp(['#000000', '#ffffff'], [0, 100], 0);
    const mid = interpolateRamp(['#000000', '#ffffff'], [0, 100], 50);
    const high = interpolateRamp(['#000000', '#ffffff'], [0, 100], 100);
    expect(low).toBe('#000000');
    expect(high).toBe('#ffffff');
    expect(mid).not.toBe(low);
    expect(mid).not.toBe(high);
  });

  it('has the weather & hazard categories and flood-risk palette', () => {
    expect(HAZARD_LAYERS.map((h) => h.id)).toEqual(['flood_risk', 'heavy_rain', 'storm', 'extreme_wind']);
    expect(TERRAIN_LAYERS.map((t) => t.id)).toEqual(['elevation', 'slope']);
    expect(Object.keys(FLOOD_RISK_COLORS)).toEqual(['LOW', 'MODERATE', 'HIGH', 'EXTREME']);
  });

  it('formats storm_indicator categorically and temperature with unit', () => {
    expect(formatVariableValue('storm_indicator', 2)).toBe('Storm');
    expect(formatVariableValue('temperature_2m', 28.1234)).toMatch(/28\.1 °C/);
    expect(variableLabel('wind_u')).toBe('Wind U (eastward)');
  });
});

describe('rainfall default layer & windy-style scale', () => {
  it('relabels precipitation as Rainfall', () => {
    expect(WEATHER_LAYERS.precipitation.label).toBe('Rainfall');
  });

  it('orders weather layers with Rainfall first (user-specified order)', () => {
    expect(WEATHER_LAYER_ORDER[0]).toBe('precipitation');
    expect(WEATHER_LAYER_ORDER).toEqual([
      'precipitation',
      'temperature_2m',
      'apparent_temperature',
      'wind_speed_10m',
      'wind_direction_10m',
      'wind_gusts_10m',
      'wind_u',
      'wind_v',
      'precipitation_probability',
      'precipitation_accumulation',
      'storm_indicator',
      'relative_humidity',
      'pressure_msl',
      'cloud_cover',
      'visibility',
    ]);
  });

  it('defines Windy-style rainfall stops with a rainbow ramp ending in purple', () => {
    expect(RAINFALL_STOPS).toEqual([0, 1, 5, 10, 20, 50, 100, 200]);
    expect(WEATHER_LAYERS.precipitation.stops).toEqual(RAINFALL_STOPS);
    expect(WEATHER_LAYERS.precipitation.colors[0]).toBe(RAINFALL_COLORS[0]);
    expect(RAINFALL_COLORS[0]).toBe('#0908a8');
    expect(RAINFALL_COLORS[RAINFALL_COLORS.length - 1]).toBe('#7a0177');
  });

  it('renders rainfall legend ticks with a trailing over-threshold label', () => {
    expect(legendTickLabels(WEATHER_LAYERS.precipitation)).toEqual([
      '0', '1', '5', '10', '20', '50', '100', '200+',
    ]);
  });

  it('falls back to a two-point gradient for non-rainfall layers', () => {
    expect(legendTickLabels(WEATHER_LAYERS.temperature_2m)).toEqual(['-10', '50']);
  });
});

describe('historical ERA5 availability gates (honest — nothing fabricated)', () => {
  it('monthly view: the daily-archive aggregates are available', () => {
    expect([...HISTORICAL_GRID_VARIABLES]).toEqual([
      'temperature_2m',
      'precipitation',
      'precipitation_accumulation',
      'wind_speed_10m',
      'wind_gusts_10m',
      'pressure_msl',
      'storm_indicator',
      'apparent_temperature',
      'cloud_cover',
    ]);
    for (const v of HISTORICAL_GRID_VARIABLES) {
      expect(isHistoricalVariableAvailable(v, false)).toBe(true);
    }
  });

  it('humidity / visibility / rain-probability stay unavailable in every historical view', () => {
    for (const v of ['relative_humidity', 'visibility', 'precipitation_probability'] as const) {
      expect(isHistoricalVariableAvailable(v, false)).toBe(false);
      expect(isHistoricalVariableAvailable(v, true)).toBe(false);
    }
  });

  it('per-day-only wind fields require the Daily view', () => {
    expect([...HISTORICAL_PER_DAY_VARIABLES]).toEqual(['wind_direction_10m', 'wind_u', 'wind_v']);
    for (const v of HISTORICAL_PER_DAY_VARIABLES) {
      expect(isHistoricalVariableAvailable(v, false)).toBe(false);
      expect(isHistoricalVariableAvailable(v, true)).toBe(true);
    }
  });
});