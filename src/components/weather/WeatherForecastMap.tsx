import React, { useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import { CloudSun, Loader2, Map as MapIcon, Mountain, Pause, Play, Satellite } from 'lucide-react';
import {
  BasemapKey,
  DataStatusEntry,
  WeatherGridPoint,
  WeatherGridResponse,
  WeatherResponse,
  WeatherVariable,
} from '../../types';
import type { RegionViewportFocus } from '../../lib/regionViewport';
import { INDIA_OVERVIEW } from '../../lib/regionViewport';
import { apiService } from '../../services/api';
import { DataSourceStatus } from '../DataSourceStatus';

const MAX_GRID_POINTS = 600;
/** day 0 = current conditions, 1..7 = forecast day (slider stops). */
const FORECAST_DAY_MAX = 7;
const STEP_CANDIDATES = [0.05, 0.075, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5];

interface VariableMeta {
  id: WeatherVariable;
  label: string;
  unit: string;
  domain: [number, number];
  colors: string[];
  /** Non-linear colour mapping: gamma < 1 expands the low end (drizzle etc.). */
  gamma?: number;
  /** Discrete categories (no gradients) — colour picked by Math.round(value). */
  categorical?: boolean;
  /** Only served for day 0 (current conditions) by the backend — and for
   *  intraday layers, only the exact instant the variable exists (Now). */
  currentOnly?: boolean;
  format: (v: number) => string;
}

const VARIABLE_META: Record<WeatherVariable, VariableMeta> = {
  temperature_2m: {
    id: 'temperature_2m', label: 'Temperature', unit: '°C',
    domain: [-10, 50],
    colors: ['#3b4cc0', '#4daf4a', '#ffffbf', '#f46d43', '#a50026'],
    format: (v) => `${v.toFixed(1)}°C`,
  },
  precipitation: {
    id: 'precipitation', label: 'Precipitation', unit: 'mm',
    domain: [0, 50], gamma: 0.5,
    colors: ['#f7fbff', '#c6dbef', '#6baed6', '#2171b5', '#08306b'],
    format: (v) => `${v.toFixed(1)} mm`,
  },
  precipitation_probability: {
    id: 'precipitation_probability', label: 'Rain probability', unit: '%',
    domain: [0, 100],
    colors: ['#f7fbff', '#c6dbef', '#6baed6', '#2171b5', '#08519c'],
    format: (v) => `${Math.round(v)}%`,
  },
  wind_speed_10m: {
    id: 'wind_speed_10m', label: 'Wind speed', unit: 'km/h',
    domain: [0, 80],
    colors: ['#4daf4a', '#ffffbf', '#f46d43', '#a50026'],
    format: (v) => `${v.toFixed(1)} km/h`,
  },
  wind_gusts_10m: {
    id: 'wind_gusts_10m', label: 'Wind gusts', unit: 'km/h',
    domain: [0, 120],
    colors: ['#d1f2eb', '#85c1e9', '#5499c7', '#f5b041', '#ca6f1e', '#943126'],
    format: (v) => `${v.toFixed(1)} km/h`,
  },
  cloud_cover: {
    id: 'cloud_cover', label: 'Cloud cover', unit: '%',
    domain: [0, 100],
    colors: ['#fdfdff', '#c9d6e7', '#93add0', '#5b7ba8', '#3a5472'],
    format: (v) => `${Math.round(v)}%`,
  },
  precipitation_accumulation: {
    id: 'precipitation_accumulation', label: 'Rainfall accumulation', unit: 'mm',
    domain: [0, 200], gamma: 0.5,
    colors: ['#f7fbff', '#bdd7e7', '#6baed6', '#3182bd', '#08519c', '#08306b'],
    format: (v) => `${v.toFixed(1)} mm`,
  },
  storm_indicator: {
    id: 'storm_indicator', label: 'Storm risk', unit: 'index',
    domain: [0, 2], categorical: true,
    colors: ['#64748b', '#f59e0b', '#dc2626'],
    format: (v) => {
      const n = Math.round(v);
      return n === 2 ? 'Storm (wind gusts)' : n === 1 ? 'Thunderstorm' : 'No storm';
    },
  },
  relative_humidity: {
    id: 'relative_humidity', label: 'Humidity', unit: '%',
    domain: [0, 100], currentOnly: true,
    colors: ['#ffffcc', '#a1dab4', '#41b6c4', '#2c7fb8', '#253494'],
    format: (v) => `${Math.round(v)}%`,
  },
  pressure_msl: {
    id: 'pressure_msl', label: 'Pressure', unit: 'hPa',
    domain: [980, 1040], currentOnly: true,
    colors: ['#5e3c99', '#b2abd2', '#f7f7f7', '#fdbb84', '#e34a33'],
    format: (v) => `${v.toFixed(0)} hPa`,
  },
  wind_direction_10m: {
    id: 'wind_direction_10m', label: 'Wind direction', unit: '°',
    domain: [0, 360],
    colors: ['#2c3e50', '#1abc9c', '#f1c40f', '#e67e22', '#c0392b'],
    format: (v) => `${v.toFixed(0)}°`,
  },
  wind_u: {
    id: 'wind_u', label: 'Wind U (eastward)', unit: 'm/s',
    domain: [-30, 30],
    colors: ['#2166ac', '#67a9cf', '#f7f7f7', '#ef8a62', '#b2182b'],
    format: (v) => `${v.toFixed(1)} m/s`,
  },
  wind_v: {
    id: 'wind_v', label: 'Wind V (northward)', unit: 'm/s',
    domain: [-30, 30],
    colors: ['#2166ac', '#67a9cf', '#f7f7f7', '#ef8a62', '#b2182b'],
    format: (v) => `${v.toFixed(1)} m/s`,
  },
  apparent_temperature: {
    id: 'apparent_temperature', label: 'Feels-like', unit: '°C',
    domain: [-10, 50], currentOnly: true,
    colors: ['#3b4cc0', '#4daf4a', '#ffffbf', '#f46d43', '#a50026'],
    format: (v) => `${v.toFixed(1)}°C`,
  },
  visibility: {
    id: 'visibility', label: 'Visibility', unit: 'km',
    domain: [0, 60], currentOnly: true,
    colors: ['#67001f', '#d6604d', '#f4a582', '#92c5de', '#053061'],
    format: (v) => `${v.toFixed(0)} km`,
  },
};

const VARIABLE_ORDER: WeatherVariable[] = [
  'temperature_2m',
  'precipitation',
  'precipitation_probability',
  'wind_speed_10m',
  'wind_gusts_10m',
  'cloud_cover',
  'precipitation_accumulation',
  'storm_indicator',
  'relative_humidity',
  'pressure_msl',
  'wind_direction_10m',
  'wind_u',
  'wind_v',
  'apparent_temperature',
  'visibility',
];

const escHtml = (value: string | number | null | undefined): string =>
  String(value ?? '').replace(
    /[&<>"']/g,
    (c) => (({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }) as Record<string, string>)[c]
  );

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '');
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
  return [
    parseInt(full.slice(0, 2), 16),
    parseInt(full.slice(2, 4), 16),
    parseInt(full.slice(4, 6), 16),
  ];
}

function lerpHex(a: string, b: string, t: number): string {
  const [r1, g1, b1] = hexToRgb(a);
  const [r2, g2, b2] = hexToRgb(b);
  const r = Math.round(r1 + (r2 - r1) * t);
  const g = Math.round(g1 + (g2 - g1) * t);
  const bl = Math.round(b1 + (b2 - b1) * t);
  return `#${[r, g, bl].map((v) => Math.max(0, Math.min(255, v)).toString(16).padStart(2, '0')).join('')}`;
}

function colorForValue(value: number, meta: VariableMeta): string {
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

/** Finest grid step (degrees) whose rows×cols stays within the point budget. */
function chooseGridStep(spanLat: number, spanLng: number, maxPoints = MAX_GRID_POINTS): number {
  for (const step of STEP_CANDIDATES) {
    const rows = Math.floor(spanLat / step) + 1;
    const cols = Math.floor(spanLng / step) + 1;
    if (rows * cols <= maxPoints) return step;
  }
  return STEP_CANDIDATES[STEP_CANDIDATES.length - 1];
}

function forecastDayLabel(offset: number): string {
  if (offset <= 0) return 'Now';
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return d.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' });
}

/** Intraday + daily timeline. Intraday stops are hour offsets from "now"
 *  (served via the grid `hour` parameter); daily stops are forecast days. */
interface TimelineStop {
  key: string;
  label: string;
  day: number;
  hour?: number;
}

function buildTimelineStops(): TimelineStop[] {
  return [
    { key: 'now', label: 'Now', day: 0 },
    { key: 'h1', label: '+1h', day: 0, hour: 1 },
    { key: 'h3', label: '+3h', day: 0, hour: 3 },
    { key: 'h6', label: '+6h', day: 0, hour: 6 },
    { key: 'h12', label: '+12h', day: 0, hour: 12 },
    { key: 'h24', label: '+24h', day: 0, hour: 24 },
    { key: 'd2', label: `Day 2 · ${forecastDayLabel(2)}`, day: 2 },
    { key: 'd3', label: `Day 3 · ${forecastDayLabel(3)}`, day: 3 },
    { key: 'd5', label: `Day 5 · ${forecastDayLabel(5)}`, day: 5 },
    { key: 'd7', label: `Day 7 · ${forecastDayLabel(7)}`, day: 7 },
  ];
}

function providerBadgeHtml(
  provider: string | null | undefined,
  role: string | null | undefined,
  model: string | null | undefined
): string {
  if (!provider && !model) return '';
  const roleLabel =
    role === 'backup' ? 'BACKUP' : role === 'legacy' ? 'LEGACY' : role === 'primary' ? 'PRIMARY' : '';
  const roleColor =
    role === 'backup' ? '#b45309' : role === 'legacy' ? '#6d28d9' : role === 'primary' ? '#047857' : '#475569';
  return `<span style="display:inline-block;font-size:9px;font-weight:800;letter-spacing:0.05em;color:#fff;background:${roleColor};border-radius:999px;padding:1px 7px;margin-right:4px;vertical-align:middle">${
    escHtml(provider ?? '')}${roleLabel ? ` · ${roleLabel}` : ''}</span>${
    model ? `<span style="font-size:10px;color:#64748b">${escHtml(model)}</span>` : ''}`;
}

function statusColorOf(status: string): string {
  if (status === 'LIVE' || status === 'FORECAST') return '#047857';
  if (status.replace(/_/g, ' ').toUpperCase() === 'NOT CONFIGURED') return '#b45309';
  return '#b91c1c';
}

function weatherPopupHtml(w: WeatherResponse, lat: number, lng: number): string {
  const status = String(w.data_status);
  const isLive = status === 'LIVE' || status === 'FORECAST';
  const rows: string[] = [];
  const c = w.current;

  if (c) {
    if (c.temperature_c != null) {
      const feels = c.apparent_temperature_c != null ? ` (feels ${c.apparent_temperature_c.toFixed(1)}°)` : '';
      rows.push(`<div>Temperature: <b>${c.temperature_c.toFixed(1)}°C</b>${feels}</div>`);
    }
    if (c.weather_description) rows.push(`<div>${escHtml(c.weather_description)}</div>`);
    if (c.relative_humidity_percent != null) rows.push(`<div>Humidity: <b>${Math.round(c.relative_humidity_percent)}%</b></div>`);
    if (c.pressure_hpa != null) rows.push(`<div>Pressure: <b>${c.pressure_hpa.toFixed(0)} hPa</b></div>`);
    if (c.wind_speed_kmh != null) {
      const gust = c.wind_gusts_kmh != null ? `, gusts ${c.wind_gusts_kmh.toFixed(0)}` : '';
      const dir = c.wind_direction_deg != null ? ` @ ${Math.round(c.wind_direction_deg)}°` : '';
      rows.push(`<div>Wind: <b>${c.wind_speed_kmh.toFixed(1)} km/h</b>${dir}${gust}</div>`);
    }
    if (c.precipitation_mm != null) {
      const intensity = c.rain_intensity ? ` (${escHtml(c.rain_intensity)})` : '';
      rows.push(`<div>Precipitation: <b>${c.precipitation_mm.toFixed(1)} mm</b>${intensity}</div>`);
    }
    if (c.cloud_cover_percent != null) rows.push(`<div>Cloud cover: <b>${Math.round(c.cloud_cover_percent)}%</b></div>`);
    if (c.uv_index != null) rows.push(`<div>UV index: <b>${c.uv_index.toFixed(1)}</b></div>`);
    if (c.visibility_km != null) rows.push(`<div>Visibility: <b>${c.visibility_km.toFixed(1)} km</b></div>`);
  }

  const forecastRows = w.forecast.slice(0, FORECAST_DAY_MAX).map((d) => {
    const desc = d.weather_description ? ` <span style="color:#64748b">${escHtml(d.weather_description)}</span>` : '';
    const prob = d.precipitation_probability_percent != null ? ` (${Math.round(d.precipitation_probability_percent)}%)` : '';
    const min = d.min_temp_c != null ? d.min_temp_c.toFixed(0) : '—';
    const max = d.max_temp_c != null ? d.max_temp_c.toFixed(0) : '—';
    return `<div style="display:flex;justify-content:space-between;gap:8px"><span>${escHtml(d.date.slice(5))}</span><span><b>${min}–${max}°C</b>${prob}</span></div>${desc ? `<div style="font-size:10px;color:#475569">${desc}</div>` : ''}`;
  });

  const hourlyRows = (w.hourly ?? []).slice(0, 8).map((h) => {
    const t = h.temperature_c != null ? `${h.temperature_c.toFixed(0)}°` : '—';
    const p = h.precipitation_probability_percent != null ? `${Math.round(h.precipitation_probability_percent)}%` : '—';
    return `<span style="white-space:nowrap"><b>${escHtml(h.time.slice(11, 16))}</b> ${t} ${p}</span>`;
  });

  const metaRows: string[] = [];
  if (isLive) metaRows.push(`<div style="color:#64748b">Source: <b>${escHtml(w.data_source)}</b></div>`);
  const badge = providerBadgeHtml(w.provider, w.provider_role, w.model);
  if (badge) metaRows.push(`<div style="margin-top:2px">${badge}</div>`);
  if (w.observed_at) {
    const observed = new Date(w.observed_at);
    metaRows.push(
      `<div style="color:#64748b">Observed: ${Number.isNaN(observed.getTime()) ? escHtml(w.observed_at) : observed.toLocaleString()}</div>`
    );
  }
  if (w.elevation_actual != null) metaRows.push(`<div style="color:#64748b">Elevation: ${w.elevation_actual.toFixed(0)} m (actual)</div>`);

  const reason =
    !isLive && w.reason
      ? `<div style="color:#b91c1c;margin-top:4px;font-size:11px">${escHtml(w.reason)}</div>`
      : '';

  return `<div style="min-width:210px;max-width:280px;font-size:12px">
    <div style="font-weight:700;color:#0f172a">Weather — ${lat.toFixed(4)}, ${lng.toFixed(4)}</div>
    <div style="margin:4px 0;color:#334155">${rows.length ? rows.join('') : 'No current values.'}</div>
    ${metaRows.join('')}
    <div style="font-size:10px;font-weight:700;color:${statusColorOf(status)};margin-top:2px">${status.replace(/_/g, ' ')}</div>
    ${reason}
    ${
      forecastRows.length
        ? `<div style="margin-top:6px;border-top:1px solid #e2e8f0;padding-top:4px"><div style="font-size:10px;font-weight:700;color:#334155;text-transform:uppercase;letter-spacing:0.04em">7-day forecast</div>${forecastRows.join('')}</div>`
        : ''
    }
    ${
      hourlyRows.length
        ? `<div style="margin-top:6px;border-top:1px solid #e2e8f0;padding-top:4px"><div style="font-size:10px;font-weight:700;color:#334155;text-transform:uppercase;letter-spacing:0.04em;margin-bottom:2px">Next hours (temp · rain%)</div><div style="display:flex;flex-wrap:wrap;gap:6px;font-size:10px;color:#475569">${hourlyRows.join('')}</div></div>`
        : ''
    }
  </div>`;
}

function gridCellPopupHtml(
  p: WeatherGridPoint,
  meta: VariableMeta,
  grid: WeatherGridResponse
): string {
  const status = String(p.data_status ?? grid.data_status);
  const timeTag =
    grid.hour != null && grid.hour > 0
      ? ` · +${grid.hour}h`
      : grid.day > 0
        ? ` · ${escHtml(forecastDayLabel(grid.day))}`
        : ' · Now';
  const valueRow =
    p.value != null
      ? `<div style="font-size:18px;font-weight:800;color:#0f172a">${meta.format(p.value)}</div>`
      : `<div style="font-size:13px;font-weight:700;color:#b91c1c">No data for this cell</div>`;
  const badge = providerBadgeHtml(p.provider ?? grid.provider, p.provider_role ?? grid.provider_role, grid.model);
  const reason =
    p.value == null && (p.reason ?? grid.reason)
      ? `<div style="color:#b91c1c;font-size:11px;margin-top:3px">${escHtml(p.reason ?? grid.reason ?? '')}</div>`
      : '';
  return `<div style="min-width:170px;font-size:12px">
    <div style="font-weight:700;color:#0f172a">${escHtml(meta.label)}${timeTag}</div>
    ${valueRow}
    <div style="color:#64748b;font-size:11px">${p.latitude.toFixed(2)}°, ${p.longitude.toFixed(2)}°</div>
    ${badge ? `<div style="margin-top:3px">${badge}</div>` : ''}
    <div style="font-size:10px;font-weight:700;color:${statusColorOf(status)};margin-top:2px">${status.replace(/_/g, ' ')}</div>
    ${reason}
  </div>`;
}

interface WeatherForecastMapProps {
  focus?: RegionViewportFocus | null;
  regionLabel?: string;
  dataStatus?: DataStatusEntry[] | null;
}

export const WeatherForecastMap: React.FC<WeatherForecastMapProps> = ({
  focus = null,
  regionLabel = 'All of India',
  dataStatus = null,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const basemapLayerRef = useRef<L.Layer | null>(null);
  const gridLayerRef = useRef<L.LayerGroup | null>(null);
  const suppressMapClickRef = useRef<number>(0);
  const retryRef = useRef<number>(0);

  const [basemap, setBasemap] = useState<BasemapKey['id']>('street');
  const [variable, setVariable] = useState<WeatherVariable>('temperature_2m');
  const [stopIndex, setStopIndex] = useState<number>(0);
  const [grid, setGrid] = useState<WeatherGridResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [playing, setPlaying] = useState<boolean>(false);
  const gridCacheRef = useRef<Map<string, WeatherGridResponse>>(new Map());
  const inFlightRef = useRef<Set<string>>(new Set());
  const [viewport, setViewport] = useState<[number, number, number, number]>(() => {
    const [s, w, n, e] = focus?.bounds ?? INDIA_OVERVIEW.bounds;
    return [n, s, e, w];
  });

  const viewportKey = useMemo(
    () => viewport.map((v) => v.toFixed(3)).join(','),
    [viewport]
  );

  const timelineStops = useMemo(() => buildTimelineStops(), []);
  const stop = timelineStops[Math.max(0, Math.min(stopIndex, timelineStops.length - 1))];

  const gridCacheKey = (vars: WeatherVariable, s: TimelineStop): string =>
    `${viewportKey}|${vars}|${s.key}`;

  const weatherStatusLayers = useMemo(() => {
    const relevant = ['weather', 'weather_forecast', 'terrain', 'satellite_tiles'];
    return (dataStatus ?? []).filter((e) => relevant.includes(e.layer));
  }, [dataStatus]);

  // ----- Map bootstrap -------------------------------------------------
  const destroyMap = () => {
    const map = mapRef.current;
    if (!map) return;
    map.remove();
    mapRef.current = null;
    gridLayerRef.current = null;
    basemapLayerRef.current = null;
  };

  // Leaflet computes its viewport projection from the container size at
  // construction. If the canvas measures 0px (height collapses inside
  // auto-height parents), the first fitBounds computes a NaN zoom and every
  // moveend getBounds() call throws "Invalid LatLng (NaN, NaN)" — uncaught,
  // it unmounts the whole app → blank white page. Wait until the element
  // actually has non-zero size before creating the map.
  useEffect(() => {
    const container = containerRef.current;
    if (!container || mapRef.current) return;

    let cancelled = false;
    let attempts = 0;
    const proceed = () => {
      if (cancelled || mapRef.current) return;
      if (container.offsetWidth === 0 || container.offsetHeight === 0) {
        attempts += 1;
        if (attempts > 120) return;
        window.requestAnimationFrame(proceed);
        return;
      }
      createMap(container);
    };
    const raf = window.requestAnimationFrame(proceed);

    return () => {
      cancelled = true;
      window.cancelAnimationFrame(raf);
      destroyMap();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const createMap = (container: HTMLDivElement) => {
    const finiteOr = (value: number | undefined | null, fallback: number): number =>
      typeof value === 'number' && Number.isFinite(value) ? value : fallback;

    const initialCenter: [number, number] = focus
      ? [
          finiteOr(focus.lat, INDIA_OVERVIEW.lat),
          finiteOr(focus.lng, INDIA_OVERVIEW.lng),
        ]
      : [INDIA_OVERVIEW.lat, INDIA_OVERVIEW.lng];
    const map = L.map(container, {
      center: initialCenter,
      zoom: finiteOr(focus?.zoom, INDIA_OVERVIEW.zoom),
      zoomControl: false,
    });
    L.control.zoom({ position: 'topright' }).addTo(map);
    gridLayerRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;

    (window as unknown as { __namsafeWeatherMap?: L.Map }).__namsafeWeatherMap = map;

    map.on('moveend', () => {
      try {
        const b = map.getBounds();
        if (!b || !b.isValid()) return;
        const n = Number(b.getNorth().toFixed(3));
        const s = Number(b.getSouth().toFixed(3));
        const e = Number(b.getEast().toFixed(3));
        const w = Number(b.getWest().toFixed(3));
        if ([n, s, e, w].every((v) => Number.isFinite(v))) {
          setViewport([n, s, e, w]);
        }
      } catch {
        // Transiently degenerate map state (zero-size container during layout)
        // must never propagate — the page stays visible.
      }
    });

    map.on('click', (event: L.LeafletMouseEvent) => {
      if (Date.now() < suppressMapClickRef.current) return;
      const { lat, lng } = event.latlng;
      const popup = L.popup({ className: 'leaflet-custom-tooltip', maxWidth: 300 })
        .setLatLng(event.latlng)
        .setContent('<div style="font-size:12px;color:#475569">Loading weather…</div>')
        .openOn(map);
      apiService
        .getWeatherRow(lat, lng, FORECAST_DAY_MAX)
        .then((weather) => popup.setContent(weatherPopupHtml(weather, lat, lng)))
        .catch(() =>
          popup.setContent('<div style="font-size:12px;color:#b91c1c">Weather unavailable.</div>')
        );
    });

    const resizeObserver = new ResizeObserver(() => map.invalidateSize());
    resizeObserver.observe(containerRef.current);
  };

  // ----- Region focus ----------------------------------------------------
  useEffect(() => {
    if (!focus) return;

    // The map is created asynchronously (deferred bootstrap waiting for a
    // non-zero container size); a zero-size map also makes fitBounds compute a
    // NaN zoom. Retry until both the map and a real size exist, instead of
    // crashing or silently skipping the focus.
    let attempts = 0;
    const apply = () => {
      const current = mapRef.current;
      if (!current || !current.getSize || current.getSize().x <= 0 || current.getSize().y <= 0) {
        attempts += 1;
        if (attempts > 300) return;
        retryRef.current = window.requestAnimationFrame(apply);
        return;
      }
      try {
        if (focus.bounds) {
          const [s, w, n, e] = focus.bounds;
          if ([s, w, n, e].every((v) => typeof v === 'number' && Number.isFinite(v))) {
            current.fitBounds(
              [
                [s, w],
                [n, e],
              ],
              { padding: [24, 24], animate: true }
            );
          }
        } else if (focus.lat != null && focus.lng != null && Number.isFinite(focus.lat) && Number.isFinite(focus.lng)) {
          const safeZoom =
            typeof focus.zoom === 'number' && Number.isFinite(focus.zoom)
              ? focus.zoom % 1 === 0
                ? focus.zoom
                : Math.round(focus.zoom)
              : INDIA_OVERVIEW.zoom;
          current.flyTo([focus.lat, focus.lng], safeZoom, {
            duration: 0.8,
          });
        }
      } catch {
        // Never let a degenerate map state escape this effect.
      }
    };
    const raf = window.requestAnimationFrame(apply);
    return () => {
      window.cancelAnimationFrame(raf);
      if (retryRef.current) window.cancelAnimationFrame(retryRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus]);

  // ----- Basemap switcher (same providers as the GIS map) ---------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (basemapLayerRef.current) {
      map.removeLayer(basemapLayerRef.current);
      basemapLayerRef.current = null;
    }

    const googleKey = (import.meta as { env?: Record<string, string> }).env?.VITE_GOOGLE_MAPS_API_KEY || '';

    if (googleKey) {
      const lyrsMap: Record<BasemapKey['id'], string> = { street: 'm', satellite: 'y', terrain: 't' };
      const url = `https://maps.googleapis.com/maps/vt?lyrs=${lyrsMap[basemap] ?? 'm'}&x={x}&y={y}&z={z}&key=${googleKey}`;
      basemapLayerRef.current = L.tileLayer(url, {
        attribution: 'Map data &copy; <a href="https://www.google.com/maps">Google</a> | SafeMove AI',
        maxZoom: 21,
        subdomains: [],
      }).addTo(map);
    } else if (basemap === 'street') {
      basemapLayerRef.current = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors | SafeMove AI',
        maxZoom: 18,
      }).addTo(map);
    } else {
      const imagery = L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        {
          attribution: 'Tiles &copy; Esri — Source: Esri, Maxar, Earthstar Geographics | SafeMove AI',
          maxZoom: 18,
        }
      );
      const labels = L.tileLayer('https://basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}.png', {
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/">CARTO</a>',
        maxZoom: 18,
      });
      basemapLayerRef.current = L.layerGroup([imagery, labels]).addTo(map);
    }
  }, [basemap]);

  // ----- Grid fetch (load-once local cache + neighbour prefetch) -----------
  // Each (viewport, variable, timeline-stop) pair is cached in memory so the
  // timeline plays back without re-hitting the backend. The next stop is
  // prefetched in the background so stepping forward is instant.
  const fetchGridCached = async (vars: WeatherVariable, idx: number): Promise<WeatherGridResponse | null> => {
    const s = timelineStops[idx];
    if (!s) return null;
    const [n, sBound, e, w] = viewport;
    const spanLat = n - sBound;
    const spanLng = e - w;
    if (!(spanLat > 0 && spanLng > 0)) return null;
    const key = gridCacheKey(vars, s);
    const hit = gridCacheRef.current.get(key);
    if (hit) return hit;
    if (inFlightRef.current.has(key)) return null;
    inFlightRef.current.add(key);
    try {
      const step = chooseGridStep(spanLat, spanLng);
      const boundsStr = `${n.toFixed(3)},${sBound.toFixed(3)},${e.toFixed(3)},${w.toFixed(3)}`;
      const result = await apiService.getWeatherGrid(boundsStr, {
        variable: vars,
        day: s.day,
        hour: s.hour,
        step,
        maxPoints: MAX_GRID_POINTS,
      });
      gridCacheRef.current.set(key, result);
      return result;
    } finally {
      inFlightRef.current.delete(key);
    }
  };

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      const key = gridCacheKey(variable, stop);
      const cached = gridCacheRef.current.get(key);
      if (cached) {
        if (!cancelled) {
          setGrid(cached);
          setLoading(false);
        }
        return;
      }
      setLoading(true);
      const result = await fetchGridCached(variable, stopIndex);
      if (cancelled || !result) return;
      setGrid(result);
      setLoading(false);
    }, 350);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [variable, stopIndex, viewportKey]);

  // Prefetch the neighbouring stop so playback/manual stepping is instant.
  useEffect(() => {
    if (stopIndex >= timelineStops.length - 1) return;
    const key = gridCacheKey(variable, timelineStops[stopIndex + 1]);
    if (gridCacheRef.current.has(key) || inFlightRef.current.has(key)) return;
    window.setTimeout(() => {
      void fetchGridCached(variable, stopIndex + 1);
    }, 450);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [variable, stopIndex, viewportKey]);

  // Timeline animation — steps locally over the cache (loads drivers load on
  // demand per stop), looping back to Now once the 7-day horizon is reached.
  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      setStopIndex((i) => (i + 1) % timelineStops.length);
    }, 1000);
    return () => window.clearInterval(id);
  }, [playing, timelineStops.length]);

  // ----- Grid rendering ---------------------------------------------------
  useEffect(() => {
    const layer = gridLayerRef.current;
    if (!layer) return;
    layer.clearLayers();
    if (!grid || grid.points.length === 0) return;

    const meta = VARIABLE_META[(grid.variable as WeatherVariable) ?? variable] ?? VARIABLE_META.temperature_2m;
    const stepLat = grid.steps?.latitude || 0.25;
    const stepLng = grid.steps?.longitude || 0.25;
    const halfLat = stepLat / 2;
    const halfLng = stepLng / 2;
    const { north, south, east, west } = grid.bounds;

    for (const p of grid.points) {
      const s = Math.max(south, p.latitude - halfLat);
      const n = Math.min(north, p.latitude + halfLat);
      const w = Math.max(west, p.longitude - halfLng);
      const e = Math.min(east, p.longitude + halfLng);
      if (!(n > s && e > w)) continue;

      const hasValue = p.value != null;
      const rect = L.rectangle(
        [
          [s, w],
          [n, e],
        ],
        {
          color: 'rgba(15,23,42,0.25)',
          weight: 0.4,
          fillColor: hasValue ? colorForValue(p.value as number, meta) : '#94a3b8',
          fillOpacity: hasValue ? 0.7 : 0.15,
        }
      );
      rect.bindPopup(gridCellPopupHtml(p, meta, grid), { maxWidth: 260 });
      rect.on('click', () => {
        suppressMapClickRef.current = Date.now() + 400;
      });
      rect.addTo(layer);
    }
  }, [grid, variable]);

  // ----- UI handlers ------------------------------------------------------
  const handleVariableChange = (next: WeatherVariable) => {
    // Humidity/pressure only exist for the exact current moment; jumping to an
    // hour/day stop would honestly render an all-null "unavailable" grid.
    if (VARIABLE_META[next].currentOnly && stopIndex !== 0) setStopIndex(0);
    setVariable(next);
  };

  const handleStopChange = (next: number) => {
    setStopIndex(next);
    setPlaying(false);
    if (next !== 0 && VARIABLE_META[variable].currentOnly) setVariable('temperature_2m');
  };

  const togglePlay = () => {
    if (VARIABLE_META[variable].currentOnly) return;
    setPlaying((p) => !p);
  };

  const status = grid?.data_status ?? 'UNAVAILABLE';
  const isUnavailable = status === 'UNAVAILABLE';
  const meta = VARIABLE_META[variable];
  const [domainMin, domainMax] = meta.domain;
  const gradient = meta.colors.join(', ');

  return (
    <div
      id="weather-map-component"
      className="relative w-full h-[460px] lg:h-[560px] rounded-xl overflow-hidden border border-sm-border shadow-inner bg-sm-bg"
    >
      <div ref={containerRef} id="weather-map-canvas" className="absolute inset-0 z-0" />

      {/* Variable layer switcher (top-left) */}
      <div className="absolute top-3 left-3 z-20 bg-sm-panel/95 backdrop-blur-md rounded-xl border border-sm-border shadow-lg p-2.5 w-[196px]">
        <div className="flex items-center gap-1.5 mb-2">
          <CloudSun className="w-4 h-4 text-sky-400" />
          <span className="text-[11px] font-bold uppercase tracking-wider text-sm-text">Weather layer</span>
        </div>
        <div className="flex flex-col gap-1">
          {VARIABLE_ORDER.map((id) => {
            const m = VARIABLE_META[id];
            const disabled = Boolean(m.currentOnly && stopIndex !== 0);
            const active = variable === id;
            return (
              <button
                key={id}
                id={`weather-layer-${id}`}
                type="button"
                disabled={disabled}
                onClick={() => handleVariableChange(id)}
                title={disabled ? 'Current conditions only (day 0)' : m.label}
                className={`text-left text-[11px] px-2 py-1 rounded-md border transition flex items-center justify-between gap-2 ${
                  active
                    ? 'bg-sky-500/20 text-sky-300 border-sky-500/40 font-bold'
                    : disabled
                      ? 'bg-sm-panel-2 text-sm-muted/50 border-sm-border cursor-not-allowed'
                      : 'bg-sm-panel-2 text-sm-text border-sm-border hover:bg-sm-panel-2/60 cursor-pointer'
                }`}
              >
                <span>{m.label}</span>
                <span className={`text-[9px] font-semibold ${active ? 'text-sky-300' : 'text-sm-muted'}`}>{m.unit}</span>
              </button>
            );
          })}
        </div>
        <div
          id="weather-grid-status"
          className="mt-2 pt-2 border-t border-sm-border text-[10px] leading-tight"
          title={grid?.reason ?? undefined}
        >
          <div className="flex items-center justify-between gap-1">
            <span className="font-bold" style={{ color: statusColorOf(status) }}>
              {status.replace(/_/g, ' ')}
            </span>
            {grid?.provider_role === 'backup' && (
              <span className="text-[8px] font-extrabold tracking-wide bg-amber-500/20 text-amber-300 px-1.5 py-0.5 rounded-full">
                ECMWF BACKUP
              </span>
            )}
            {grid?.provider_role === 'primary' && (
              <span className="text-[8px] font-extrabold tracking-wide bg-emerald-500/20 text-emerald-300 px-1.5 py-0.5 rounded-full">
                OPEN-METEO
              </span>
            )}
          </div>
          <p className="text-sm-muted mt-0.5 truncate">{grid?.data_source ?? 'Loading…'}</p>
          <p className="text-sm-muted/60 truncate">
            {escHtml(regionLabel)} · {grid && grid.steps?.latitude ? `${grid.steps.latitude.toFixed(2)}° grid` : ''}
          </p>
        </div>
      </div>

      {/* Basemap toggle (below Leaflet zoom control, top-right) */}
      <div className="absolute top-[76px] right-2 z-20 flex flex-col gap-1">
        <button
          id="weather-basemap-street"
          type="button"
          onClick={() => setBasemap('street')}
          title="Street basemap"
          className={`w-9 h-9 flex items-center justify-center rounded-lg border shadow transition cursor-pointer ${
            basemap === 'street'
              ? 'bg-sm-green text-slate-900 border-sm-green'
              : 'bg-sm-panel-2/95 text-sm-text border-sm-border hover:bg-sm-panel-2'
          }`}
        >
          <MapIcon className="w-4 h-4" />
        </button>
        <button
          id="weather-basemap-satellite"
          type="button"
          onClick={() => setBasemap('satellite')}
          title="Satellite basemap"
          className={`w-9 h-9 flex items-center justify-center rounded-lg border shadow transition cursor-pointer ${
            basemap === 'satellite'
              ? 'bg-sm-green text-slate-900 border-sm-green'
              : 'bg-sm-panel-2/95 text-sm-text border-sm-border hover:bg-sm-panel-2'
          }`}
        >
          <Satellite className="w-4 h-4" />
        </button>
      </div>

      {/* Loading indicator */}
      {loading && (
        <div className="absolute top-3 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2 bg-sm-panel-2/95 text-sm-text text-[11px] font-semibold px-3 py-1.5 rounded-lg shadow-lg">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          Loading weather grid…
        </div>
      )}

      {/* Honest failure banner */}
      {isUnavailable && !loading && (
        <div
          id="weather-unavailable-banner"
          className="absolute top-14 left-1/2 -translate-x-1/2 z-20 bg-red-900/90 text-red-100 text-[11px] font-bold px-3 py-1.5 rounded-lg border border-red-700 shadow-lg max-w-[85%] text-center"
        >
          WEATHER GRID UNAVAILABLE — {grid?.reason ?? 'Weather upstream unreachable or rejected the request.'}
        </div>
      )}

      {/* Timeline slider (bottom-center) — intraday hours + forecast days */}
      <div className="absolute bottom-3 left-1/2 -translate-x-1/2 z-20 bg-sm-panel/95 backdrop-blur-md rounded-xl border border-sm-border shadow-lg px-4 py-2.5 w-[min(440px,calc(100%-1.5rem))] sm:w-[440px]">
        <div className="flex items-center justify-between text-[10px] font-bold text-sm-muted uppercase tracking-wider mb-1">
          <span>Timeline</span>
          <span id="weather-day-label" className="text-sky-400">
            {stopIndex === 0 ? 'Now (current conditions)' : `${stop.hour != null ? `Forecast · +${stop.hour}h` : `Forecast · ${stop.label}`}`}
          </span>
        </div>
        <input
          id="weather-day-slider"
          type="range"
          min={0}
          max={timelineStops.length - 1}
          step={1}
          value={stopIndex}
          onChange={(e) => handleStopChange(Number(e.target.value))}
          className="w-full accent-sm-green cursor-pointer"
          aria-label="Forecast timeline"
        />
        <div className="flex justify-between text-[9px] text-sm-muted mt-0.5">
          <span>Now</span>
          <span className="hidden sm:inline">+3h</span>
          <span className="hidden sm:inline">+24h · Day 2 · Day 7</span>
          <span className="sm:hidden">+1h … +7d</span>
        </div>
        <div className="flex items-center gap-2 mt-1.5 pt-1.5 border-t border-sm-border">
          <button
            id="weather-play-button"
            type="button"
            onClick={togglePlay}
            disabled={VARIABLE_META[variable].currentOnly}
            title={VARIABLE_META[variable].currentOnly ? 'Current-conditions layer — animation disabled' : playing ? 'Pause timeline' : 'Play timeline animation'}
            className={`flex items-center justify-center w-7 h-7 rounded-lg border shadow-sm transition cursor-pointer disabled:cursor-not-allowed ${
              playing
                ? 'bg-sm-green text-slate-900 border-sm-green'
                : 'bg-sm-panel-2 text-sm-text border-sm-border hover:bg-sm-panel-2/60'
            }`}
          >
            {playing ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
          </button>
          <span className="text-[9px] text-sm-muted leading-tight">
            {playing ? 'Animating through the timeline…' : 'Click play to animate NOW → +24h → the 7-day forecast.'}
          </span>
        </div>
      </div>

      {/* Colour legend (bottom-right) */}
      <div
        id="weather-legend"
        className="absolute bottom-3 right-3 z-20 bg-sm-panel/95 backdrop-blur-md rounded-xl border border-sm-border shadow-lg px-3 py-2 w-[190px]"
      >
        <div className="text-[10px] font-bold text-sm-text uppercase tracking-wider mb-1">
          {meta.label} <span className="text-sm-muted font-semibold normal-case">({meta.unit})</span>
        </div>
        {meta.categorical ? (
          <div className="flex flex-col gap-1">
            {meta.colors.map((color, i) => (
              <div key={`${color}-${i}`} className="flex items-center gap-1.5 text-[9px] text-sm-muted">
                <span className="w-3 h-3 rounded-sm border border-sm-border inline-block" style={{ background: color }} />
                <span>{meta.format(i)}</span>
              </div>
            ))}
          </div>
        ) : (
          <>
            <div
              className="h-3 rounded border border-sm-border"
              style={{ background: `linear-gradient(to right, ${gradient})` }}
            />
            <div className="flex justify-between text-[9px] text-sm-muted mt-0.5">
              <span>{domainMin}</span>
              <span>{domainMax}</span>
            </div>
          </>
        )}
        <div className="flex items-center gap-1.5 mt-1.5 text-[9px] text-sm-muted">
          <span className="w-3 h-3 rounded-sm border border-sm-border inline-block" style={{ background: '#94a3b8', opacity: 0.4 }} />
          <span>No data (cell not returned)</span>
        </div>
        <p className="text-[9px] text-sm-muted mt-1 leading-tight">
          Click the map for point forecast details.
        </p>
      </div>

      {/* Data-source panel (bottom-left) */}
      <DataSourceStatus layers={weatherStatusLayers} />
    </div>
  );
};
