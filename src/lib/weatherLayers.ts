import type { WeatherVariable } from '../types';

/** Shared layer metadata for the Weather & Hazard Map. Mirrors the backend
 *  grid variables: names, units, colour ramps, mapping gamma, whether a layer
 *  only exists for current conditions (accurate_NOW), formatting. */
export interface VariableMeta {
  id: WeatherVariable;
  label: string;
  unit: string;
  domain: [number, number];
  colors: string[];
  gamma?: number;
  categorical?: boolean;
  currentOnly?: boolean;
  /** Discrete legend breakpoints (value labels) when this layer uses a
   *  stepped scale instead of a continuous gradient. */
  stops?: number[];
  /** Suffix for the final legend stop, e.g. 'over' renders the last tick as
   *  "200+". */
  stopsPrefix?: 'over';
}

/** Windy-style rainfall rainbow (light blue → blue → cyan → green → yellow →
 *  orange → red → purple). Used for the default Rainfall layer. */
export const RAINFALL_COLORS = [
  '#0908a8',
  '#1a4fb7',
  '#1fb7e8',
  '#2ad4a4',
  '#d3e63a',
  '#f7b32b',
  '#e5112e',
  '#7a0177',
];

export const RAINFALL_STOPS = [0, 1, 5, 10, 20, 50, 100, 200];

export const WEATHER_LAYERS: Record<WeatherVariable, VariableMeta> = {
  temperature_2m: {
    id: 'temperature_2m', label: 'Temperature', unit: '°C',
    domain: [-10, 50],
    colors: ['#3b4cc0', '#4daf4a', '#ffffbf', '#f46d43', '#a50026'],
  },
  apparent_temperature: {
    id: 'apparent_temperature', label: 'Feels-like', unit: '°C',
    domain: [-10, 50],
    colors: ['#3b4cc0', '#4daf4a', '#ffffbf', '#f46d43', '#a50026'],
  },
  wind_speed_10m: {
    id: 'wind_speed_10m', label: 'Wind speed', unit: 'km/h',
    domain: [0, 80],
    colors: ['#154a2e', '#2e8b57', '#ffd966', '#f28c28', '#c0392b'],
  },
  wind_gusts_10m: {
    id: 'wind_gusts_10m', label: 'Wind gusts', unit: 'km/h',
    domain: [0, 120],
    colors: ['#d1f2eb', '#85c1e9', '#5499c7', '#f5b041', '#ca6f1e', '#943126'],
  },
  wind_direction_10m: {
    id: 'wind_direction_10m', label: 'Wind direction', unit: '°',
    domain: [0, 360],
    colors: ['#2c3e50', '#1abc9c', '#f1c40f', '#e67e22', '#c0392b'],
  },
  wind_u: {
    id: 'wind_u', label: 'Wind U (eastward)', unit: 'm/s',
    domain: [-30, 30],
    colors: ['#2166ac', '#67a9cf', '#f7f7f7', '#ef8a62', '#b2182b'],
  },
  wind_v: {
    id: 'wind_v', label: 'Wind V (northward)', unit: 'm/s',
    domain: [-30, 30],
    colors: ['#2166ac', '#67a9cf', '#f7f7f7', '#ef8a62', '#b2182b'],
  },
  precipitation: {
    id: 'precipitation', label: 'Rainfall', unit: 'mm',
    domain: [0, 200], gamma: 0.45, stops: RAINFALL_STOPS, stopsPrefix: 'over',
    colors: RAINFALL_COLORS,
  },
  precipitation_probability: {
    id: 'precipitation_probability', label: 'Rain probability', unit: '%',
    domain: [0, 100],
    colors: ['#f7fbff', '#c6dbef', '#6baed6', '#2171b5', '#08519c'],
  },
  precipitation_accumulation: {
    id: 'precipitation_accumulation', label: 'Rain accumulation', unit: 'mm',
    domain: [0, 200], gamma: 0.5,
    colors: ['#f7fbff', '#bdd7e7', '#6baed6', '#3182bd', '#08519c', '#08306b'],
  },
  storm_indicator: {
    id: 'storm_indicator', label: 'Thunderstorm', unit: 'index', categorical: true,
    domain: [0, 2],
    colors: ['#64748b', '#f59e0b', '#dc2626'],
  },
  relative_humidity: {
    id: 'relative_humidity', label: 'Humidity', unit: '%', currentOnly: true,
    domain: [0, 100],
    colors: ['#ffffcc', '#a1dab4', '#41b6c4', '#2c7fb8', '#253494'],
  },
  pressure_msl: {
    id: 'pressure_msl', label: 'Pressure', unit: 'hPa',
    domain: [980, 1040],
    colors: ['#5e3c99', '#b2abd2', '#f7f7f7', '#fdbb84', '#e34a33'],
  },
  cloud_cover: {
    id: 'cloud_cover', label: 'Cloud cover', unit: '%',
    domain: [0, 100],
    colors: ['#fdfdff', '#c9d6e7', '#93add0', '#5b7ba8', '#3a5472'],
  },
  visibility: {
    id: 'visibility', label: 'Visibility', unit: 'km', currentOnly: true,
    domain: [0, 60],
    colors: ['#67001f', '#d6604d', '#f4a582', '#92c5de', '#053061'],
  },
};

export const WEATHER_LAYER_ORDER: WeatherVariable[] = [
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
];

/** Discrete legend tick labels for a layer, or falls back to the two domain
 *  endpoints for continuous-gradient layers. */
export function legendTickLabels(meta: VariableMeta): string[] {
  if (meta.stops) {
    return meta.stops.map((s, i) =>
      i === meta.stops!.length - 1 && meta.stopsPrefix === 'over'
        ? `${s}+`
        : `${s}`
    );
  }
  return [`${meta.domain[0]}`, `${meta.domain[1]}`];
}

// Variables the ERA5 *daily* archive exposes as real monthly aggregates. Every
// other variable is honestly reported unavailable in historical mode — never
// substituted with live or fabricated values.
export const HISTORICAL_GRID_VARIABLES: ReadonlySet<WeatherVariable> = new Set([
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

// Variables the ERA5 archive only holds per single day (no monthly aggregate)
// — playable in the Daily view, honestly unavailable for the whole-month view.
export const HISTORICAL_PER_DAY_VARIABLES: ReadonlySet<WeatherVariable> = new Set([
  'wind_direction_10m',
  'wind_u',
  'wind_v',
]);

export function isHistoricalVariableAvailable(v: WeatherVariable, daily = false): boolean {
  return HISTORICAL_GRID_VARIABLES.has(v) || (daily && HISTORICAL_PER_DAY_VARIABLES.has(v));
}

// ---------------- hazards & terrain ----------------

export interface HazardLayer {
  id: 'flood_risk' | 'heavy_rain' | 'storm' | 'extreme_wind';
  label: string;
  description: string;
  gridVariable?: WeatherVariable;
  kind: 'grid' | 'computed';
}

export const HAZARD_LAYERS: HazardLayer[] = [
  {
    id: 'flood_risk', label: 'Flood risk', kind: 'computed',
    description: 'Rule-based overlay from live precip + SRTM terrain',
  },
  { id: 'heavy_rain', label: 'Heavy rain', kind: 'grid', gridVariable: 'precipitation', description: 'Rainfall intensity' },
  { id: 'storm', label: 'Thunderstorm', kind: 'grid', gridVariable: 'storm_indicator', description: 'Storm-weather-code map' },
  { id: 'extreme_wind', label: 'Extreme wind', kind: 'grid', gridVariable: 'wind_gusts_10m', description: 'Gust thresholds' },
];

export interface TerrainLayer {
  id: 'elevation' | 'slope';
  label: string;
  description: string;
}

export const TERRAIN_LAYERS: TerrainLayer[] = [
  { id: 'elevation', label: 'Elevation (SRTM)', description: 'Real NASA SRTM elevation' },
  { id: 'slope', label: 'Slope', description: 'Derived ground steepness' },
];

export const FLOOD_RISK_COLORS: Record<string, string> = {
  LOW: 'rgba(39,174,96,0.38)',
  MODERATE: 'rgba(241,196,15,0.42)',
  HIGH: 'rgba(230,126,34,0.48)',
  EXTREME: 'rgba(192,57,43,0.55)',
};

export const ELEVATION_COLORS = ['#14532d', '#22c55e', '#facc15', '#b45309', '#7c2d12', '#f8fafc'];
export const ELEVATION_DOMAIN: [number, number] = [0, 4000];
export const SLOPE_COLORS = ['#f7fbff', '#c6dbef', '#6baed6', '#fb6a4a', '#b2182b'];
export const SLOPE_DOMAIN: [number, number] = [0, 30];

// ---------------- colour + formatting helpers ----------------

export function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '');
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
  return [
    parseInt(full.slice(0, 2), 16),
    parseInt(full.slice(2, 4), 16),
    parseInt(full.slice(4, 6), 16),
  ];
}

export function lerpHex(a: string, b: string, t: number): string {
  const [r1, g1, b1] = hexToRgb(a);
  const [r2, g2, b2] = hexToRgb(b);
  const r = Math.round(r1 + (r2 - r1) * t);
  const g = Math.round(g1 + (g2 - g1) * t);
  const bl = Math.round(b1 + (b2 - b1) * t);
  return `#${[r, g, bl].map((v) => Math.max(0, Math.min(255, v)).toString(16).padStart(2, '0')).join('')}`;
}

export function colorForValue(value: number, meta: VariableMeta): string {
  if (meta.categorical) {
    const idx = Math.max(0, Math.min(Math.round(value), meta.colors.length - 1));
    return meta.colors[idx];
  }
  const [min, max] = meta.domain;
  let t = (value - min) / (max - min);
  t = Math.max(0, Math.min(1, t));
  if (meta.gamma != null) t = Math.pow(t, meta.gamma);
  const { colors } = meta;
  if (colors.length === 1) return colors[0];
  const scaled = t * (colors.length - 1);
  const i = Math.min(Math.floor(scaled), colors.length - 2);
  return lerpHex(colors[i], colors[i + 1], scaled - i);
}

export function interpolateRamp(colors: string[], domain: [number, number], value: number): string {
  const [min, max] = domain;
  let t = (value - min) / (max - min);
  t = Math.max(0, Math.min(1, t));
  const scaled = t * (colors.length - 1);
  const i = Math.min(Math.floor(scaled), colors.length - 2);
  return lerpHex(colors[i], colors[i + 1], scaled - i);
}

export function variableLabel(v: WeatherVariable): string {
  return WEATHER_LAYERS[v]?.label ?? v;
}

export function formatVariableValue(v: WeatherVariable, value: number): string {
  const meta = WEATHER_LAYERS[v];
  if (!meta) return `${value}`;
  if (v === 'storm_indicator') {
    const n = Math.round(value);
    return n === 2 ? 'Storm' : n === 1 ? 'Thunderstorm' : 'None';
  }
  if (meta.categorical) return `${value}`;
  const decimals = meta.unit === 'mm' || meta.unit === '°C' ? 1 : 0;
  return `${value.toFixed(decimals)} ${meta.unit}`;
}