import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import {
  CalendarDays,
  ChevronDown,
  ChevronUp,
  CloudSun,
  Expand,
  Layers,
  Loader2,
  LocateFixed,
  Map as MapIcon,
  Pause,
  Play,
  Search,
  SkipBack,
  SkipForward,
  SlidersHorizontal,
  Waves,
  Wind,
  X,
} from 'lucide-react';
import type {
  BasemapKey,
  FloodRiskGridResponse,
  HistoricalAvailabilitySummary,
  HistoricalWeatherResponse,
  WeatherGridResponse,
  WeatherResponse,
  WeatherVariable,
} from '../../types';
import type { RegionViewportFocus } from '../../lib/regionViewport';
import { INDIA_OVERVIEW } from '../../lib/regionViewport';
import { apiService } from '../../services/api';
import { clipWeatherGridBounds } from '../../lib/weatherBounds';
import { WindCanvas, type WindField } from './WindCanvas';
import { WeatherLegend } from './WeatherLegend';
import { MonthTimeline } from './MonthTimeline';
import { DateControl, type DayMode } from './DateControl';
import { WeatherSettingsPanel, type WeatherDataSource } from './WeatherSettingsPanel';
import { completedMonthsFor, completedPeriodCaption, fmtDateLabel } from '../../lib/historicalDates';
import {
  FLOOD_RISK_COLORS,
  HAZARD_LAYERS,
  WEATHER_LAYERS,
  WEATHER_LAYER_ORDER,
  colorForValue,
  formatVariableValue,
  isHistoricalVariableAvailable,
  variableLabel,
} from '../../lib/weatherLayers';

const MAX_GRID_POINTS = 400;
const STEP_CANDIDATES = [0.05, 0.075, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5];
const HOURLY_MAX = 47;
const HISTORICAL_YEAR_DEFAULT = 2025;

type Feed =
  | { kind: 'weather'; variable: WeatherVariable }
  | { kind: 'flood' };

function chooseGridStep(spanLat: number, spanLng: number, maxPoints = MAX_GRID_POINTS): number {
  for (const step of STEP_CANDIDATES) {
    const rows = Math.floor(spanLat / step) + 1;
    const cols = Math.floor(spanLng / step) + 1;
    if (rows * cols <= maxPoints) return step;
  }
  return STEP_CANDIDATES[STEP_CANDIDATES.length - 1];
}

function boundsStringFromFocus(focus: RegionViewportFocus | null | undefined): string {
  const b = focus?.bounds ?? INDIA_OVERVIEW.bounds;
  if (!b || b.length !== 4) return '37.4,6.0,98.5,68.0';
  return `${b[2].toFixed(4)},${b[0].toFixed(4)},${b[3].toFixed(4)},${b[1].toFixed(4)}`;
}

// Point picker snaps to the nearest already-fetched grid cell (within one
// grid step) so the value appears instantly instead of waiting on a fresh
// upstream call. Returns null when the grid is empty/unavailable or the point
// is not covered by any cell.
function pickCellValue(
  grid: WeatherGridResponse | null,
  lat: number,
  lng: number
): { value: number | null; unit: string } | null {
  if (!grid || !grid.points || grid.points.length === 0) return null;
  const latStep = grid.steps?.latitude ?? 0.25;
  const lngStep = grid.steps?.longitude ?? 0.25;
  const tolerance = Math.max(latStep, lngStep) * 1.5;
  let best: { d: number; p: { value: number | null; latitude: number; longitude: number } } | null = null;
  for (const p of grid.points) {
    if (p.value === null || p.latitude == null || p.longitude == null) continue;
    const d = Math.abs(p.latitude - lat) + Math.abs(p.longitude - lng);
    if (!best || d < best.d) best = { d, p: { value: p.value, latitude: p.latitude, longitude: p.longitude } };
  }
  if (!best || best.d > tolerance) return null;
  return { value: best.p.value, unit: grid.unit ?? '' };
}

function monthPeriodLabel(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, '0')}`;
}

function hourClockLabel(hourOffset: number): string {
  const d = new Date(Date.now() + hourOffset * 3600_000);
  return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
}

function statusColor(status: string): string {
  const s = status.replace(/_/g, ' ').toUpperCase();
  if (['LIVE', 'FORECAST', 'CALCULATED'].includes(s)) return '#34d399';
  if (s === 'HISTORICAL') return '#a78bfa';
  if (s === 'CACHED') return '#38bdf8';
  if (s === 'API NOT ADDED' || s === 'NOT CONFIGURED') return '#fbbf24';
  return '#f87171';
}

function StatusChip({ status }: { status: string }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-bold text-[10px] tracking-wide uppercase"
      style={{ color: statusColor(status), backgroundColor: `${statusColor(status)}1f` }}
      title={status}
    >
      <span
        className="w-1.5 h-1.5 rounded-full"
        style={{ backgroundColor: statusColor(status), boxShadow: `0 0 6px ${statusColor(status)}` }}
      />
      {status.replace(/_/g, ' ')}
    </span>
  );
}

const WIND_LAYER: WeatherVariable = 'wind_speed_10m';

export interface WeatherMapProps {
  focus?: RegionViewportFocus | null;
  regionLabel?: string;
  canManageLiveProviders?: boolean;
}

function gridCellBounds(
  p: { latitude: number; longitude: number },
  stepLat: number,
  stepLng: number,
  bounds: { north: number; south: number; east: number; west: number }
): L.LatLngBoundsExpression {
  const halfLat = Math.max(stepLat / 2, 0.01);
  const halfLng = Math.max(stepLng / 2, 0.01);
  const s = Math.max(bounds.south, p.latitude - halfLat);
  const n = Math.min(bounds.north, p.latitude + halfLat);
  const w = Math.max(bounds.west, p.longitude - halfLng);
  const e = Math.min(bounds.east, p.longitude + halfLng);
  return [
    [s, w],
    [n, e],
  ];
}

export const WeatherMap: React.FC<WeatherMapProps> = ({
  focus = null,
  regionLabel = 'India',
  canManageLiveProviders = true,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const weatherLayerRef = useRef<L.LayerGroup | null>(null);
  const floodLayerRef = useRef<L.LayerGroup | null>(null);
  const windLayerRef = useRef<WindCanvas | null>(null);
  const markerRef = useRef<L.CircleMarker | null>(null);
  const basemapLayerRef = useRef<L.Layer | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const [basemap, setBasemap] = useState<BasemapKey['id']>('street');
  const [category, setCategory] = useState<'weather' | 'hazards'>('weather');
  const [weatherVariable, setWeatherVariable] = useState<WeatherVariable>('precipitation');
  const [hazard, setHazard] = useState<Feed | null>(null);
  const [hour, setHour] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [windOn, setWindOn] = useState(false);

  // Historical (ERA5 archive) mode. The map opens in historical mode on the
  // default archive year so NO live forecast request is ever armed implicitly;
  // `dataSource` is the only way to opt into live (and defaults to historical).
  const [historicalYear, setHistoricalYear] = useState<number | null>(HISTORICAL_YEAR_DEFAULT);
  const [historicalMonth, setHistoricalMonth] = useState<number | null>(1);
  const [historicalDay, setHistoricalDay] = useState<number>(1);
  const [dayMode, setDayMode] = useState<DayMode>('monthly');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [dataSource, setDataSource] = useState<WeatherDataSource>('historical');
  const [yearAvail, setYearAvail] = useState<HistoricalAvailabilitySummary[]>([]);
  const isHistorical = historicalYear != null && historicalMonth != null;

  const [grid, setGrid] = useState<WeatherGridResponse | null>(null);
  const [floodGrid, setFloodGrid] = useState<FloodRiskGridResponse | null>(null);
  const [windField, setWindField] = useState<WindField | null>(null);
  const [loading, setLoading] = useState(false);

  const [picker, setPicker] = useState<{
    lat: number;
    lng: number;
    value: number | null;
    label: string;
    unit: string;
    weather?: WeatherResponse | HistoricalWeatherResponse;
  } | null>(null);
  // Latest grid seen by the picker handler (avoids rebinding on every fetch).
  const pickerGridRef = useRef<WeatherGridResponse | null>(null);
  pickerGridRef.current = grid;
  // Monotonic guard so a slow point enrichment can never land on a NEWER click.
  const pickerSeqRef = useRef(0);

  const [layersOpen, setLayersOpen] = useState(true);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<Array<{ name: string; lat: number; lng: number }>>([]);
  const [searching, setSearching] = useState(false);
  const [movedViewport, setMovedViewport] = useState<string | null>(null);
  const [viewOutsideIndia, setViewOutsideIndia] = useState(false);
  const viewportMoveTimerRef = useRef<number | null>(null);

  // Load historical availability once and default the selector to 2025.
  useEffect(() => {
    let live = true;
    void apiService.getHistoricalYears().then((res) => {
      if (!live) return;
      const avail = res.availability ?? [];
      setYearAvail(avail);
      if (avail.length > 0) {
        const def = avail.find((a) => a.year === HISTORICAL_YEAR_DEFAULT) ?? avail[avail.length - 1];
        if (def) {
          setHistoricalYear(def.year);
          setHistoricalMonth(Math.max(1, Math.min(def.completed_through_month ?? 12, 12)));
        }
      }
    });
    return () => {
      live = false;
    };
  }, []);

  // Map pan/zoom drives the data window: `movedViewport` (clipped to India)
  // takes over from the focus-derived bounds once the user moves the map.
  const viewportBounds = useMemo(
    () => movedViewport ?? boundsStringFromFocus(focus),
    [movedViewport, focus]
  );
  const viewportKey = useMemo(() => viewportBounds.replace(/[.]/g, '_'), [viewportBounds]);

  const feed: Feed = useMemo<Feed>(() => {
    if (hazard) return hazard;
    return { kind: 'weather', variable: weatherVariable };
  }, [hazard, weatherVariable]);

  const currentOnly = feed.kind === 'weather' && (WEATHER_LAYERS[feed.variable]?.currentOnly ?? false);
  const effectiveHour = currentOnly || isHistorical ? 0 : hour;

  // ---------------- map init ----------------
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const map = L.map(el, {
      zoomControl: false,
      attributionControl: true,
      zoomSnap: 0.5,
      minZoom: 3,
    });
    map.attributionControl.setPrefix(false);
    mapRef.current = map;
    weatherLayerRef.current = L.layerGroup().addTo(map);
    floodLayerRef.current = L.layerGroup().addTo(map);

    const invalidate = (): void => {
      map.invalidateSize();
    };
    const ro = new ResizeObserver(invalidate);
    ro.observe(el);
    const t = window.setTimeout(invalidate, 120);

    return () => {
      window.clearTimeout(t);
      ro.disconnect();
      if (windLayerRef.current) {
        map.removeLayer(windLayerRef.current as unknown as L.Layer);
        windLayerRef.current = null;
      }
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // ---------------- viewport pan/zoom ----------------
  // `moveend` covers pan+zoom-end on the zoom snap; `zoomend` catches the
  // final zoom. Bounds are debounced (500ms) so a drag that fires many
  // events still issues at most one data request when the user settles.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const onMoveEndDebounced = (): void => {
      if (viewportMoveTimerRef.current !== null) {
        window.clearTimeout(viewportMoveTimerRef.current);
      }
      viewportMoveTimerRef.current = window.setTimeout(() => {
        viewportMoveTimerRef.current = null;
        const b = map.getBounds();
        const raw = `${b.getNorth()},${b.getSouth()},${b.getEast()},${b.getWest()}`;
        const clipped = clipWeatherGridBounds(raw);
        if (!clipped.entirelyOutside && clipped.clipped) {
          setViewOutsideIndia(false);
          setMovedViewport(clipped.clipped);
        } else {
          setViewOutsideIndia(true);
        }
      }, 500);
    };
    map.on('moveend zoomend', onMoveEndDebounced);
    return () => {
      map.off('moveend zoomend', onMoveEndDebounced);
      if (viewportMoveTimerRef.current !== null) {
        window.clearTimeout(viewportMoveTimerRef.current);
        viewportMoveTimerRef.current = null;
      }
    };
  }, []);

  // ---------------- basemap ----------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (basemapLayerRef.current) {
      map.removeLayer(basemapLayerRef.current);
      basemapLayerRef.current = null;
    }
    let layer: L.Layer;
    if (basemap === 'street') {
      layer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
        maxZoom: 18,
      });
    } else if (basemap === 'satellite') {
      const imagery = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Tiles &copy; Esri, Maxar, Earthstar Geographics',
        maxZoom: 18,
      });
      const labels = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
        maxZoom: 18,
        opacity: 0.6,
      });
      layer = L.layerGroup([imagery, labels]);
    } else {
      // Dark: keyless Esri dark-gray reference tiles (no CARTO API key needed).
      layer = L.layerGroup([
        L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
          attribution: 'Tiles &copy; Esri, USGS, NOAA',
          maxZoom: 18,
        }),
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
          attribution: '&copy; OpenStreetMap contributors',
          maxZoom: 18,
          opacity: 0.18,
        }),
      ]);
    }
    basemapLayerRef.current = layer;
    layer.addTo(map);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [basemap, viewportKey]);

  // ---------------- focus / initial view ----------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = (): void => {
      const b = focus?.bounds ?? INDIA_OVERVIEW.bounds;
      if (b && b.length === 4) {
        map.fitBounds(
          [
            [b[0], b[1]],
            [b[2], b[3]],
          ],
          { padding: [12, 12], animate: false }
        );
      } else if (focus) {
        const z = Number.isFinite(focus.zoom) ? Math.round(focus.zoom) : INDIA_OVERVIEW.zoom;
        map.setView([focus.lat, focus.lng], z, { animate: false });
      } else {
        map.fitBounds(
          [
            [INDIA_OVERVIEW.bounds![0], INDIA_OVERVIEW.bounds![1]],
            [INDIA_OVERVIEW.bounds![2], INDIA_OVERVIEW.bounds![3]],
          ],
          { animate: false }
        );
      }
    };
    const raf = window.requestAnimationFrame(apply);
    return () => window.cancelAnimationFrame(raf);
  }, [focus, viewportKey]);

  // ---------------- grid fetch ----------------
  const fetchGrid = useCallback(
    async (f: Feed, h: number, withAbort: AbortSignal): Promise<WeatherGridResponse | null> => {
      if (f.kind === 'flood') return null;
      const [n, s, e, w] = viewportBounds.split(',').map(Number);
      const spanLat = n - s;
      const spanLng = e - w;
      if (!(spanLat > 0 && spanLng > 0)) return null;
      const step = chooseGridStep(spanLat, spanLng);
      return apiService.getWeatherGrid(viewportBounds, {
        variable: f.variable,
        hour: currentOnly ? 0 : h,
        step,
        maxPoints: MAX_GRID_POINTS,
        prefer: 'ecmwf',
        year: isHistorical ? historicalYear ?? undefined : undefined,
        month: isHistorical ? historicalMonth ?? undefined : undefined,
        day: isHistorical ? (dayMode === 'daily' ? historicalDay : 0) : 0,
        signal: withAbort,
      });
    },
    [viewportBounds, currentOnly, isHistorical, historicalYear, historicalMonth, dayMode, historicalDay]
  );

  useEffect(() => {
    if (feed.kind === 'flood') {
      setGrid(null);
      return;
    }
    let cancelled = false;
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const timer = window.setTimeout(async () => {
      setLoading(true);
      const result = await fetchGrid(feed, effectiveHour, controller.signal);
      if (cancelled || controller.signal.aborted) return;
      setGrid(result);
      setLoading(false);
    }, 320);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
    // fetchGrid closes over viewportBounds/month/year (its own memo deps), so
    // month/year/viewport changes recreate it and re-run this effect.
  }, [feed, effectiveHour, fetchGrid, isHistorical]);

  // flood feed
  useEffect(() => {
    if (feed.kind === 'flood') {
      setGrid(null);
      setFloodGrid(null);
      setLoading(true);
      let cancelled = false;
      if (abortRef.current) abortRef.current.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      apiService
        .getFloodRiskGrid(viewportBounds, {
          step: 0.15,
          signal: controller.signal,
          year: isHistorical ? historicalYear ?? undefined : undefined,
          month: isHistorical ? historicalMonth ?? undefined : undefined,
        })
        .then((f) => {
          if (!cancelled && !controller.signal.aborted) {
            setFloodGrid(f);
            setLoading(false);
          }
        })
        .catch(() => {
          if (!cancelled && !controller.signal.aborted) {
            setFloodGrid(null);
            setLoading(false);
          }
        });
      return () => {
        cancelled = true;
        controller.abort();
      };
    }
    setFloodGrid(null);
    // month/year drive the ERA5 flood overlay — refetch when they change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feed, viewportKey, isHistorical, historicalYear, historicalMonth]);

  // ---------------- wind particles (live forecasts; historical per-day playback) ----------------
  const windActive =
    feed.kind === 'weather' &&
    feed.variable === WIND_LAYER &&
    windOn &&
    (!isHistorical || dayMode === 'daily');
  useEffect(() => {
    if (!windActive) {
      if (windLayerRef.current) {
        windLayerRef.current.pause();
      }
      setWindField(null);
      return;
    }
    let cancelled = false;
    const build = async (): Promise<void> => {
      const [n, s, e, w] = viewportBounds.split(',').map(Number);
      const step = chooseGridStep(n - s, e - w, MAX_GRID_POINTS);
      const common = {
        step,
        maxPoints: MAX_GRID_POINTS,
        prefer: 'ecmwf' as const,
        ...(isHistorical
          ? { day: historicalDay, year: historicalYear ?? undefined, month: historicalMonth ?? undefined }
          : { hour: 0 }),
      };
      const [speed, dir] = await Promise.all([
        apiService.getWeatherGrid(viewportBounds, { variable: 'wind_speed_10m', ...common }),
        apiService.getWeatherGrid(viewportBounds, { variable: 'wind_direction_10m', ...common }),
      ]);
      if (cancelled) return;
      const dirMap = new Map<string, number | null>();
      for (const p of dir.points) dirMap.set(`${p.latitude.toFixed(5)},${p.longitude.toFixed(5)}`, p.value);

      const latSet: number[] = [];
      const lonSet: number[] = [];
      const uRows: number[][] = [];
      const vRows: number[][] = [];
      let rowIdx = -1;
      let lastLat: number | null = null;
      for (const p of speed.points) {
        if (lastLat === null || Math.abs(p.latitude - lastLat) > 1e-6) {
          rowIdx += 1;
          lastLat = p.latitude;
          latSet.push(p.latitude);
          uRows.push([]);
          vRows.push([]);
        }
        if (!lonSet.includes(p.longitude)) lonSet.push(p.longitude);
        const spdKmh = p.value;
        const deg = spdKmh != null ? dirMap.get(`${p.latitude.toFixed(5)},${p.longitude.toFixed(5)}`) : null;
        if (spdKmh == null || deg == null) {
          uRows[rowIdx].push(0);
          vRows[rowIdx].push(0);
        } else {
          const ws = spdKmh / 3.6;
          const rad = (deg * Math.PI) / 180;
          uRows[rowIdx].push(-ws * Math.sin(rad));
          vRows[rowIdx].push(-ws * Math.cos(rad));
        }
      }
      const sortedLat = [...latSet].sort((a, b) => b - a);
      const sortedLon = [...lonSet].sort((a, b) => a - b);
      const latIndex = new Map<number, number>();
      latSet.forEach((lat, i) => latIndex.set(lat, i));
      const lonIndex = new Map<number, number>();
      lonSet.forEach((lon, i) => lonIndex.set(lon, i));
      const u: number[][] = Array.from({ length: sortedLat.length }, () => Array(sortedLon.length).fill(0));
      const v: number[][] = Array.from({ length: sortedLat.length }, () => Array(sortedLon.length).fill(0));
      let ok = true;
      for (let i = 0; i < latSet.length; i++) {
        const ri = latIndex.get(latSet[i]);
        if (ri === undefined) {
          ok = false;
          break;
        }
        for (let j = 0; j < uRows[i].length; j++) {
          const sj = lonIndex.get(lonSet[j]);
          if (sj === undefined) {
            ok = false;
            break;
          }
          u[ri][sj] = uRows[i][j];
          v[ri][sj] = vRows[i][j];
        }
        if (!ok) break;
      }
      if (!ok || !u.length || u[0].length !== sortedLon.length) {
        setWindField(null);
        return;
      }
      setWindField({
        lat: sortedLat,
        lon: sortedLon,
        u,
        v,
        validTime: speed.valid_time,
        source: isHistorical
          ? `${speed.data_source} · wind_u/v derived from that day's archived speed+direction (ERA5 reanalysis)`
          : `${speed.data_source} · wind_u/v derived from speed+direction (hour 0 run)`,
      });
    };
    void build();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [windActive, viewportKey, isHistorical, historicalYear, historicalMonth, historicalDay]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (windActive && windField && windLayerRef.current === null) {
      windLayerRef.current = new WindCanvas({ particleCount: 2400 }).addTo(map);
    }
    if (windActive && windField && windLayerRef.current) {
      windLayerRef.current.setData(windField);
      windLayerRef.current.resume();
    }
    if (!windActive && windLayerRef.current) {
      windLayerRef.current.pause();
    }
  }, [windActive, windField]);

  // ---------------- rendering weather/hazard grid ----------------
  useEffect(() => {
    const layer = weatherLayerRef.current;
    if (!layer) return;
    layer.clearLayers();
    if (feed.kind === 'flood') return;
    const g = grid;
    if (!g || g.points.length === 0) return;
    const v = g.variable as WeatherVariable;
    const meta = WEATHER_LAYERS[v] ?? WEATHER_LAYERS.temperature_2m;
    const stepLat = g.steps?.latitude || 0.25;
    const stepLng = g.steps?.longitude || 0.25;
    for (const p of g.points) {
      const hasValue = p.value != null;
      const rect = L.rectangle(gridCellBounds(p, stepLat, stepLng, g.bounds), {
        color: 'rgba(15,23,42,0.25)',
        weight: 0.4,
        fillColor: hasValue ? colorForValue(p.value as number, meta) : '#94a3b8',
        fillOpacity: hasValue ? 0.72 : 0.12,
      });
      rect.bindPopup(
        `<div style="font-size:11px;line-height:1.5">
          <b>${escapeHtml(meta.label)}</b><br/>
          ${p.latitude.toFixed(3)}, ${p.longitude.toFixed(3)}<br/>
          <b style="font-size:12px">${hasValue ? formatVariableValue(v, p.value as number) : 'no data'}</b>
          ${p.data_status ? `<br/><span style="color:#64748b">${escapeHtml(String(p.data_status))}</span>` : ''}
        </div>`,
        { maxWidth: 240 }
      );
      rect.on('click', () => {
        const marker = markerRef.current;
        if (marker) marker.remove();
        markerRef.current = L.circleMarker([p.latitude, p.longitude], {
          radius: 6,
          color: '#e2e8f0',
          weight: 1.5,
          fillColor: hasValue ? colorForValue(p.value as number, meta) : '#64748b',
          fillOpacity: 0.95,
        }).addTo(mapRef.current!);
      });
      rect.addTo(layer);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [grid, feed]);

  // ---------------- rendering flood overlay ----------------
  useEffect(() => {
    const layer = floodLayerRef.current;
    if (!layer) return;
    layer.clearLayers();
    if (feed.kind !== 'flood' || !floodGrid) return;
    for (const p of floodGrid.points) {
      if (p.risk_score == null) continue;
      const color = FLOOD_RISK_COLORS[p.risk_level ?? 'LOW'] ?? 'rgba(148,163,184,0.3)';
      const rect = L.rectangle(gridCellBounds(p, 0.3, 0.3, { north: Number(viewportBounds.split(',')[0]), south: Number(viewportBounds.split(',')[1]), east: Number(viewportBounds.split(',')[2]), west: Number(viewportBounds.split(',')[3]) }), {
        color: 'rgba(15,23,42,0.3)',
        weight: 0.4,
        fillColor: color,
        fillOpacity: 0.6,
      });
      rect.bindPopup(
        `<div style="font-size:11px;line-height:1.6">
          <b style="color:#b91c1c">Flood risk: ${p.risk_level}</b><br/>
          Score: <b>${p.risk_score}</b>/100<br/>
          Factors: ${escapeHtml((p.contributing_factors ?? []).join(', ') || '—')}<br/>
          <span style="color:#64748b">Rule-based overlay (${isHistorical ? `ERA5 ${monthPeriodLabel(historicalYear!, historicalMonth!)} + ` : ''}SRTM terrain)</span>
        </div>`,
        { maxWidth: 260 }
      );
      rect.addTo(layer);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [floodGrid, feed, viewportKey, isHistorical, historicalYear, historicalMonth]);

  // ---------------- picker ----------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const onClick = (e: L.LeafletMouseEvent): void => {
      const marker = markerRef.current;
      if (marker) marker.remove();
      markerRef.current = L.circleMarker([e.latlng.lat, e.latlng.lng], {
        radius: 6,
        color: '#f1f5f9',
        weight: 1.5,
        fillColor: '#38bdf8',
        fillOpacity: 0.95,
      }).addTo(map);
      // Read the already-fetched grid cell first → instant, cache-first value.
      const cell = pickCellValue(pickerGridRef.current, e.latlng.lat, e.latlng.lng);
      const cellUnit = cell?.unit ?? '';
      const cellValue = cell?.value ?? null;
      setPicker({
        lat: e.latlng.lat,
        lng: e.latlng.lng,
        value: cellValue,
        label: cellValue != null ? `${cellValue.toFixed(1)} ${cellUnit}`.trim() : '',
        unit: cellUnit,
      });
      // Enrichment: a single point request supplies the rich payload. The panel
      // no longer waits on this to show the value — the cell value is rendered
      // immediately and the request itself is bounded by a 12s client timeout.
      // The seq + coordinate guard drops a stale response on a newer click.
      const clickSeq = ++pickerSeqRef.current;
      const { lat: clickLat, lng: clickLng } = e.latlng;
      if (isHistorical && historicalYear != null && historicalMonth != null) {
        void apiService.getWeatherHistorical(clickLat, clickLng, historicalYear, historicalMonth).then((w) => {
          setPicker((p) =>
            p && p.lat === clickLat && p.lng === clickLng && pickerSeqRef.current === clickSeq
              ? { ...p, weather: w }
              : p
          );
        });
      } else {
        void apiService.getWeather(clickLat, clickLng).then((w) => {
          setPicker((p) =>
            p && p.lat === clickLat && p.lng === clickLng && pickerSeqRef.current === clickSeq
              ? { ...p, weather: w }
              : p
          );
        });
      }
    };
    map.on('click', onClick);
    return () => {
      map.off('click', onClick);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewportKey, isHistorical, historicalYear, historicalMonth]);

  // Re-sync the picker's grid cell whenever the grid refreshes (a pan/zoom or
  // timeline step can land AFTER the click). The cell value appears as soon as
  // the new grid arrives — cache-first, no extra request needed.
  useEffect(() => {
    if (!picker) return;
    const cell = pickCellValue(grid, picker.lat, picker.lng);
    const nextValue = cell?.value ?? null;
    const nextUnit = cell?.unit ?? '';
    setPicker((p) => {
      if (!p || p.value === nextValue) return p;
      return {
        ...p,
        value: nextValue,
        label: nextValue != null ? `${nextValue.toFixed(1)} ${nextUnit}`.trim() : '',
        unit: nextUnit,
      };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [grid, picker?.lat, picker?.lng]);

  // ---------------- timeline helpers ----------------
  const togglePlay = (): void => {
    if (currentOnly || isHistorical || feed.kind !== 'weather') return;
    setPlaying((p) => !p);
  };
  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      setHour((h) => (h >= HOURLY_MAX ? 0 : h + 1));
    }, 900);
    return () => window.clearInterval(id);
  }, [playing]);

  const changeHour = (h: number): void => {
    setHour(Math.max(0, Math.min(HOURLY_MAX, h)));
    setPlaying(false);
  };

  const handleWeatherVariable = (v: WeatherVariable): void => {
    setHazard(null);
    setCategory('weather');
    if (WEATHER_LAYERS[v].currentOnly) setHour(0);
    setWeatherVariable(v);
  };
  const handleHazard = (h: Feed): void => {
    setCategory('hazards');
    setHazard(h);
  };
  const resetFeed = (): void => {
    setHazard(null);
    setCategory('weather');
    setWeatherVariable('temperature_2m');
    setHour(0);
    setPlaying(false);
  };

  // ---------------- historical mode switcher ----------------
  const handleHistoricalYear = (year: number | null): void => {
    if (year == null) {
      setHistoricalYear(null);
      setHistoricalMonth(null);
      setHistoricalDay(1);
      setHour(0);
      setPlaying(false);
      return;
    }
    const entry = yearAvail.find((a) => a.year === year);
    setHistoricalYear(year);
    setHistoricalMonth(Math.max(1, Math.min(entry?.completed_through_month || 12, 12)));
    setHistoricalDay(1);
    setHour(0);
    setPlaying(false);
  };
  const historicalMonthsFor = (year: number): number =>
    Math.max(1, Math.min(yearAvail.find((a) => a.year === year)?.completed_through_month ?? 12, 12));
  const apiNotAdded = grid?.data_status != null && ['API_NOT_ADDED', 'API NOT ADDED'].includes(String(grid.data_status));
  // Honest period label derived from the real availability response.
  const availPeriodLabel =
    yearAvail.length > 1
      ? `${yearAvail[0].year}–${yearAvail[yearAvail.length - 1].year}`
      : yearAvail.length === 1
        ? `${yearAvail[0].year}`
        : '';

  // ---------------- search ----------------
  const runSearch = async (): Promise<void> => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    const res = await apiService.geocode(searchQuery.trim(), 5, 'in');
    setSearchResults(
      (res.places ?? []).map((p) => ({
        name: p.display_name ?? `${p.latitude.toFixed(4)}, ${p.longitude.toFixed(4)}`,
        lat: p.latitude,
        lng: p.longitude,
      }))
    );
    setSearching(false);
  };
  const applySearch = (lat: number, lng: number): void => {
    mapRef.current?.flyTo([lat, lng], Math.max(mapRef.current?.getZoom() ?? 6, 8), { duration: 0.8 });
    setSearchQuery('');
    setSearchResults([]);
    setSearchOpen(false);
  };
  const locateMe = (): void => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        mapRef.current?.flyTo([pos.coords.latitude, pos.coords.longitude], 10, { duration: 0.8 });
      },
      () => undefined,
      { enableHighAccuracy: true, timeout: 8000 }
    );
  };
  const toggleFullscreen = (): void => {
    if (document.fullscreenElement) {
      void document.exitFullscreen();
    } else {
      void containerRef.current?.closest('[data-weather-map-root]')?.requestFullscreen?.();
    }
  };

  // ---------------- derived render values ----------------
  const activeMeta = feed.kind === 'weather' ? WEATHER_LAYERS[feed.variable] : undefined;
  const showWeatherStatus = feed.kind === 'weather' && activeMeta;
  const gridStatus = feed.kind === 'weather' ? grid?.data_status : floodGrid?.data_status;
  const unavailableReason =
    feed.kind === 'weather'
      ? grid && grid.points.length === 0 ? grid.reason ?? 'No data in this window.' : null
      : feed.kind === 'flood'
        ? floodGrid && floodGrid.points.length === 0 ? floodGrid.reason ?? 'No data in this window.' : null
        : null;

  return (
    <div data-weather-map-root className="absolute inset-0 rounded-xl overflow-hidden border border-slate-700 shadow-2xl bg-[#0a0e1a] select-none">
      <div ref={containerRef} id="weather-hazard-map-canvas" className="absolute inset-0 z-0" />

      {/* ------------ Top bar ------------ */}
      <div className="absolute top-0 left-0 right-0 z-30 pointer-events-none">
        <div className="m-2 sm:m-3 flex flex-wrap items-center gap-2">
          <div className="pointer-events-auto flex items-center gap-2 bg-slate-950/80 backdrop-blur-md border border-slate-700/80 rounded-xl px-3 py-1.5">
            <CloudSun className="w-4 h-4 text-sky-400" />
            <span className="text-xs font-bold text-slate-100 whitespace-nowrap">{regionLabel}</span>
            {gridStatus && <StatusChip status={gridStatus} />}
            {isHistorical && (
              <span
                className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-bold text-[10px] tracking-wide uppercase"
                style={{ color: statusColor('HISTORICAL'), backgroundColor: `${statusColor('HISTORICAL')}1f` }}
                id="weather-historical-badge"
                title={`Historical ERA5 reanalysis, completed month ${monthPeriodLabel(historicalYear!, historicalMonth!)}`}
              >
                <CalendarDays className="w-3 h-3" />
                {monthPeriodLabel(historicalYear!, historicalMonth!)}
              </span>
            )}
            {isHistorical && (
              <span
                className="inline-flex items-center rounded-full px-2 py-0.5 font-bold text-[10px] tracking-wide uppercase text-amber-300 border border-amber-500/50 bg-amber-950/70"
                id="weather-archival-chip"
              >
                HISTORICAL DATA · ERA5 ARCHIVE · NOT LIVE
              </span>
            )}
          </div>

          {viewOutsideIndia && (
            <div
              className="pointer-events-auto flex items-center gap-2 bg-amber-900/60 backdrop-blur-md border border-amber-600/70 rounded-xl px-3 py-1.5"
              data-coverage-badge
            >
              <Waves className="w-3.5 h-3.5 text-amber-300" />
              <span className="text-[11px] font-medium text-amber-100 whitespace-nowrap">
                Outside India — showing empty grid
              </span>
            </div>
          )}

          {/* Historical year + month selector (near location search) */}
          {yearAvail.length > 0 && (
            <div className="pointer-events-auto flex items-center gap-1.5 bg-slate-950/80 backdrop-blur-md border border-violet-700/60 rounded-xl px-2 py-1.5" id="weather-historical-selector">
              <CalendarDays className="w-3.5 h-3.5 text-violet-400 shrink-0" />
              <select
                aria-label="Weather data mode"
                className="text-[10px] font-bold bg-transparent text-slate-100 outline-none cursor-pointer"
                value={historicalYear ?? 'live'}
                onChange={(e) => {
                  const v = e.target.value;
                  handleHistoricalYear(v === 'live' ? null : Number(v));
                }}
              >
                <option value="live">Live (today)</option>
                {yearAvail.map((a) => (
                  <option key={a.year} value={a.year}>
                    {a.label} · through {String(a.completed_through_month).padStart(2, '0')}
                  </option>
                ))}
              </select>
              {isHistorical && (
                <select
                  aria-label="Historical month"
                  className="text-[10px] font-bold bg-transparent text-slate-100 outline-none cursor-pointer"
                  value={historicalMonth ?? 1}
                  onChange={(e) => {
                  setHistoricalMonth(Number(e.target.value));
                  setHistoricalDay(1);
                }}
                >
                  {Array.from({ length: historicalMonthsFor(historicalYear!) }, (_, i) => i + 1).map((m) => (
                    <option key={m} value={m}>
                      {new Date(0, m - 1, 1).toLocaleString('en-IN', { month: 'short' }).toLowerCase()}
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}

          {/* Weather settings gear */}
          <button
            type="button"
            onClick={() => setSettingsOpen((s) => !s)}
            id="weather-settings-btn"
            aria-label="Weather settings"
            title="Weather settings"
            className="pointer-events-auto inline-flex items-center gap-1.5 rounded-xl border border-slate-700/80 bg-slate-950/80 px-2.5 py-1.5 text-slate-300 hover:text-white hover:border-slate-500"
          >
            <SlidersHorizontal className="w-3.5 h-3.5" />
            <span className="text-[10px] font-bold hidden sm:inline">Settings</span>
          </button>

          <WeatherSettingsPanel
            open={settingsOpen}
            source={dataSource}
            onSourceChange={setDataSource}
            onClose={() => setSettingsOpen(false)}
            canManageLiveProviders={canManageLiveProviders}
          />

          {/* Search */}
          <div className="pointer-events-auto relative flex-1 max-w-xs min-w-[160px]">
            {searchOpen ? (
              <div className="bg-slate-950/85 backdrop-blur-md border border-slate-700/80 rounded-xl overflow-hidden">
                <div className="flex items-center gap-2 px-2.5 py-1.5">
                  <Search className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                  <input
                    id="weather-map-search-input"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') void runSearch();
                    }}
                    placeholder="Search a place in India"
                    autoFocus
                    className="bg-transparent text-xs text-slate-100 placeholder:text-slate-500 outline-none w-full"
                  />
                  <button type="button" onClick={runSearch} className="text-slate-400 hover:text-slate-100">
                    <Search className="w-3.5 h-3.5" />
                  </button>
                  <button type="button" onClick={() => setSearchOpen(false)} className="text-slate-500 hover:text-slate-200">
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
                {searchResults.length > 0 && (
                  <ul className="border-t border-slate-700/70 max-h-44 overflow-y-auto">
                    {searchResults.map((r, i) => (
                      <li key={`${r.name}-${i}`}>
                        <button
                          type="button"
                          onClick={() => applySearch(r.lat, r.lng)}
                          className="w-full text-left text-[11px] px-3 py-1.5 text-slate-200 hover:bg-slate-800/80 flex items-center justify-between gap-2"
                        >
                          <span className="truncate">{r.name}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {searching && (
                  <div className="px-3 py-1.5 text-[10px] text-slate-500 flex items-center gap-1.5">
                    <Loader2 className="w-3 h-3 animate-spin" /> searching…
                  </div>
                )}
              </div>
            ) : (
              <button
                id="weather-map-search-toggle"
                type="button"
                onClick={() => setSearchOpen(true)}
                className="bg-slate-950/80 backdrop-blur-md border border-slate-700/80 rounded-xl px-3 py-1.5 flex items-center gap-2 text-slate-300 hover:border-slate-500"
              >
                <Search className="w-3.5 h-3.5" />
                <span className="text-[11px]">Search place…</span>
              </button>
            )}
          </div>

          <div className="pointer-events-auto ml-auto flex items-center gap-1.5">
            <button type="button" onClick={locateMe} title="Use my location" className="icon-btn">
              <LocateFixed className="w-4 h-4" />
            </button>
            <button type="button" onClick={toggleFullscreen} title="Fullscreen" className="icon-btn">
              <Expand className="w-4 h-4" />
            </button>
            {(['dark', 'street', 'satellite'] as const).map((b) => (
              <button
                key={b}
                type="button"
                onClick={() => setBasemap(b)}
                className={`text-[10px] font-bold uppercase tracking-wide px-2.5 py-1.5 rounded-lg border transition ${
                  basemap === b
                    ? 'bg-sky-600 text-white border-sky-500'
                    : 'bg-slate-950/75 text-slate-300 border-slate-700/80 hover:border-slate-500'
                }`}
              >
                {b === 'street' ? 'Streets' : b === 'satellite' ? 'Satellite' : 'Dark'}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Wind particles toggle + controls (top-right below basemap) — live, and historical per-day playback */}
      {(!isHistorical || dayMode === 'daily') && feed.kind === 'weather' && feed.variable === WIND_LAYER && (
        <div className="absolute top-14 right-[220px] z-40 pointer-events-auto flex flex-col items-start gap-1.5">
          <div className="bg-slate-950/80 backdrop-blur-md border border-slate-700/80 rounded-xl p-1.5 flex items-center gap-1">
            <button
              type="button"
              onClick={() => setWindOn((w) => !w)}
              title="Toggle animated wind particles"
              className={`flex items-center gap-1.5 text-[10px] font-bold px-2 py-1 rounded-lg transition ${
                windOn ? 'bg-sky-600/90 text-white' : 'bg-slate-900 text-slate-300'
              }`}
            >
              <Wind className="w-3.5 h-3.5" /> Particles
            </button>
            {windOn && windLayerRef.current && (
              <>
                <button type="button" onClick={() => (windLayerRef.current!.isRunning() ? windLayerRef.current!.pause() : windLayerRef.current!.resume())} className="text-slate-300 hover:text-white p-1" title="Pause / play">
                  {windLayerRef.current!.isRunning() ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                </button>
                <button type="button" onClick={() => { if (windLayerRef.current) windLayerRef.current.setSpeed(0.5); }} className="factor-btn" title="Slow">½×</button>
                <button type="button" onClick={() => { if (windLayerRef.current) windLayerRef.current.setSpeed(1); }} className="factor-btn" title="Normal">1×</button>
                <button type="button" onClick={() => { if (windLayerRef.current) windLayerRef.current.setSpeed(2); }} className="factor-btn" title="Fast">2×</button>
              </>
            )}
          </div>
        </div>
      )}

      {/* ------------ Layer panel (right) ------------ */}
      <div className="absolute top-16 bottom-20 right-3 z-30 pointer-events-auto w-[208px] flex flex-col gap-2">
        <div className="bg-slate-950/85 backdrop-blur-md border border-slate-700/80 rounded-xl shadow-xl overflow-hidden">
          <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800">
            <button
              type="button"
              onClick={() => setLayersOpen((o) => !o)}
              className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-200"
            >
              <Layers className="w-3.5 h-3.5 text-sky-400" /> Layers
              {layersOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronUp className="w-3.5 h-3.5" />}
            </button>
            <button type="button" onClick={resetFeed} title="Reset to temperature" className="text-slate-500 hover:text-sky-300">
              <MapIcon className="w-3.5 h-3.5" />
            </button>
          </div>

          {layersOpen && (
            <div className="p-2 space-y-2.5 max-h-[44vh] overflow-y-auto">
              {/* Category tabs */}
              <div className="grid grid-cols-2 gap-1">
                {(['weather', 'hazards'] as const).map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => setCategory(c)}
                    className={`text-[9px] font-bold uppercase tracking-wide py-1 rounded-md border ${
                      category === c ? 'bg-sky-600 border-sky-500 text-white' : 'bg-slate-900 border-slate-700 text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    {c}
                  </button>
                ))}
              </div>

              {/* Weather list */}
              {category === 'weather' && (
                <div className="space-y-1">
                  {WEATHER_LAYER_ORDER.map((id) => {
                    const m = WEATHER_LAYERS[id];
                    const active = feed.kind === 'weather' && feed.variable === id && !hazard;
                    const unavailable = isHistorical && !isHistoricalVariableAvailable(id, dayMode === 'daily');
                    const disabled = unavailable || Boolean(m.currentOnly && effectiveHour !== 0);
                    return (
                      <button
                        key={id}
                        type="button"
                        id={`weather-hazard-layer-${id}`}
                        disabled={disabled}
                        onClick={() => handleWeatherVariable(id)}
                        className={`w-full text-left text-[10px] px-2 py-1 rounded-md border transition flex items-center justify-between gap-1 ${
                          active
                            ? 'bg-sky-600 text-white border-sky-500 font-bold'
                            : disabled
                              ? 'bg-slate-900 text-slate-600 border-slate-800 cursor-not-allowed'
                              : 'bg-slate-900/60 text-slate-300 border-slate-800 hover:border-slate-600 hover:text-white'
                        }`}
                        title={
                          unavailable
                            ? dayMode === 'daily'
                              ? `${m.label} is not exposed by the ERA5 daily archive — honestly unavailable, never substituted.`
                              : `${m.label} is archived per-day only — switch to Daily view to play it back.`
                            : disabled
                              ? 'Current conditions only (Now)'
                              : m.label
                        }
                      >
                        <span className="truncate">{m.label}</span>
                        <span className={`text-[8px] font-semibold shrink-0 ${active ? 'text-sky-100' : 'text-slate-500'}`}>
                          {unavailable ? '—' : m.unit}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}

              {/* Hazards list */}
              {category === 'hazards' && (
                <div className="space-y-1">
                  {HAZARD_LAYERS.map((h) => {
                    const active = feed.kind === 'flood'
                      ? h.kind === 'computed'
                      : feed.kind === 'weather' && h.gridVariable === feed.variable && Boolean(hazard);
                    return (
                      <button
                        key={h.id}
                        type="button"
                        id={`weather-hazard-layer-${h.id}`}
                        onClick={() => {
                          if (h.kind === 'computed') {
                            handleHazard({ kind: 'flood' });
                          } else if (h.gridVariable) {
                            setHazard({ kind: 'weather', variable: h.gridVariable });
                            setCategory('hazards');
                          }
                        }}
                        className={`w-full text-left px-2 py-1.5 rounded-md border transition ${
                          active ? 'bg-rose-600 text-white border-rose-500' : 'bg-slate-900/60 text-slate-300 border-slate-800 hover:border-rose-500/60'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-1">
                          <span className="text-[10px] font-bold">{h.label}</span>
                          {h.kind === 'computed' && <Waves className="w-3 h-3 text-rose-400" />}
                        </div>
                        <p className="text-[8px] text-slate-400 leading-tight mt-0.5">
                          {h.kind === 'computed' && isHistorical
                            ? `Rule-based from ERA5 ${monthPeriodLabel(historicalYear!, historicalMonth!)} + SRTM terrain`
                            : h.description}
                        </p>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Sources / provenance */}
        <div className="bg-slate-950/85 backdrop-blur-md border border-slate-700/80 rounded-xl shadow-xl overflow-hidden">
          <button
            type="button"
            id="weather-hazard-sources"
            onClick={() => setSourcesOpen((o) => !o)}
            className="w-full flex items-center justify-between px-3 py-2 text-[11px] font-bold uppercase tracking-wider text-slate-200"
          >
            Sources & provenance
            {sourcesOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronUp className="w-3.5 h-3.5" />}
          </button>
          {sourcesOpen && (
            <div className="px-3 pb-3 pt-0 space-y-1.5 text-[10px] leading-relaxed text-slate-400 border-t border-slate-800 max-h-[26vh] overflow-y-auto">
              {feed.kind === 'weather' && grid && (
                <>
                  <div className="flex items-center gap-2 flex-wrap">
                    <StatusChip status={grid.data_status} />
                    {isHistorical && grid.data_status !== 'UNAVAILABLE' && (
                      <span className="text-violet-300 font-bold text-[9px]">ERA5 REANALYSIS</span>
                    )}
                    {grid.provider_role === 'backup' && <span className="text-amber-400 font-bold text-[9px]">ECMWF BACKUP</span>}
                    {grid.provider_role === 'primary' && <span className="text-emerald-400 font-bold text-[9px]">PRIMARY</span>}
                  </div>
                  <p>Provider: <b className="text-slate-200">{grid.provider ?? '—'}</b></p>
                  <p>Source: <b className="text-slate-200">{grid.data_source}</b></p>
                  {grid.model && <p>Model: <b className="text-slate-200">{grid.model}</b></p>}
                  {isHistorical && (
                    <>
                      <p>
                        Period: <b className="text-violet-200">
                          {dayMode === 'daily'
                            ? `Day ${historicalDay} · ${fmtDateLabel(historicalYear!, historicalMonth!, historicalDay)}`
                            : `${monthPeriodLabel(historicalYear!, historicalMonth!)} (completed month, archived)`}
                        </b>
                      </p>
                      {grid.data_provenance?.source && (
                        <p className="text-[9px] text-slate-500">Provenance: {grid.data_provenance.source}</p>
                      )}
                    </>
                  )}
                  {grid.valid_time && <p>Valid: <b className="text-slate-200">{grid.valid_time}</b></p>}
                  {grid.bounds && (
                    <p>
                      Bounds: <b className="text-slate-200">{grid.bounds.south.toFixed(2)}°S–{grid.bounds.north.toFixed(2)}°N, {grid.bounds.west.toFixed(2)}°W–{grid.bounds.east.toFixed(2)}°E</b>
                    </p>
                  )}
                  {grid.steps?.latitude && <p>Grid: ~{grid.steps.latitude.toFixed(2)}° cells, {grid.points.length} cells</p>}
                  <p>
                    {isHistorical
                      ? dayMode === 'daily'
                        ? `Day ${historicalDay} · ${fmtDateLabel(historicalYear!, historicalMonth!, historicalDay)}`
                          + (grid.data_provenance?.aggregation ? ` · ${grid.data_provenance.aggregation}` : ' · per-day value')
                        : `${monthPeriodLabel(historicalYear!, historicalMonth!)} monthly aggregate`
                      : `${grid.day === 0 ? 'Now' : `Day ${grid.day}`}${grid.hour != null ? ` · +${grid.hour}h` : ''}`}
                    {' · unit '}{grid.unit ?? '—'}
                  </p>
                  {grid.points.some((p) => p.value != null) && grid.min != null && grid.max != null && (
                    <p>
                      Range: <b className="text-slate-200">{grid.min.toFixed(1)}–{grid.max.toFixed(1)} {grid.unit}</b>
                    </p>
                  )}
                  {grid.derived && <p className="text-amber-300">Derived from speed + direction (u/v), never fabricated.</p>}
                  {isHistorical && grid.data_status === 'UNAVAILABLE' && (
                    <p className="text-rose-400">This variable is not exposed by the ERA5 daily archive — reported honestly, never substituted.</p>
                  )}
                </>
              )}
              {feed.kind === 'flood' && floodGrid && (
                <>
                  <p>Status: <StatusChip status={floodGrid.data_status} /></p>
                  <p className="text-amber-300">Transparent rule-based overlay (CALCULATED).</p>
                  <p>Source: {floodGrid.data_source}</p>
                  {isHistorical && (
                    <p>
                      Period: <b className="text-violet-200">{monthPeriodLabel(historicalYear!, historicalMonth!)} (ERA5 + SRTM)</b>
                    </p>
                  )}
                  {floodGrid.weights && (
                    <p>
                      Weights: {Object.entries(floodGrid.weights)
                        .map(([k, w]) => `${k.replace(/_/g, ' ')} ${(Number(w) * 100).toFixed(0)}%`)
                        .join(' · ')}
                    </p>
                  )}
                </>
              )}
              {windActive && windField && (
                <p className="text-sky-300">Wind particles: {windField.source}</p>
              )}
              {grid?.reason && <p className="text-rose-400">{grid.reason}</p>}
              {floodGrid?.reason && <p className="text-rose-400">{floodGrid.reason}</p>}
              {feed.kind === 'weather' && !isHistorical && (
                <p className="pt-1 text-slate-500">Timeline: Now + hourly {HOURLY_MAX}h forecast. Open-Meteo/ECMWF chain, prefer=ecmwf.</p>
              )}
              {feed.kind === 'weather' && isHistorical && (
                <p className="pt-1 text-slate-500">
                  Historical mode: {dayMode === 'daily'
                    ? `per-day playback for ${fmtDateLabel(historicalYear!, historicalMonth!, historicalDay)}`
                    : `monthly aggregates`} from the Open-Meteo ERA5 archive (completed months only, never invented).
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ------------ Legend (bottom-right) ------------ */}
      <WeatherLegend
        meta={feed.kind === 'weather' ? activeMeta : undefined}
        flood={feed.kind === 'flood'}
        isHistorical={isHistorical}
        historicalLabel={isHistorical ? (dayMode === 'daily' ? fmtDateLabel(historicalYear!, historicalMonth!, historicalDay) : monthPeriodLabel(historicalYear!, historicalMonth!)) : ''}
      />

      {/* ------------ API NOT ADDED hint (live disabled in this build) ------------ */}
      {!loading && !isHistorical && apiNotAdded && yearAvail.length > 0 && (
        <div className="absolute inset-x-0 top-24 z-20 flex justify-center pointer-events-none">
          <div className="bg-amber-950/85 backdrop-blur-md border border-amber-500/40 rounded-xl px-4 py-3 text-amber-100 shadow-2xl max-w-sm text-center">
            <p className="text-xs font-bold tracking-wide">LIVE WEATHER NOT ADDED IN THIS BUILD</p>
            <p className="text-[10px] mt-1 text-amber-200/90 leading-relaxed">
              The live forecast layer is not enabled here. {availPeriodLabel ? `Historical ERA5 monthly aggregates (${availPeriodLabel}) are available` : 'Historical ERA5 monthly aggregates are available'} — switch to see real archive data.
            </p>
            {yearAvail.length > 0 && (
              <button
                type="button"
                onClick={() => handleHistoricalYear(HISTORICAL_YEAR_DEFAULT)}
                className="mt-2 text-[10px] font-bold text-amber-100 border border-amber-500/50 rounded-lg px-2.5 py-1 hover:bg-amber-800/60 pointer-events-auto"
                id="weather-use-historical-btn"
              >
                Use historical {HISTORICAL_YEAR_DEFAULT}
              </button>
            )}
          </div>
        </div>
      )}

      {/* ------------ Unavailable overlay ------------ */}
      {!loading && gridStatus === 'UNAVAILABLE' && (
        <div className="absolute inset-x-0 top-24 z-20 flex justify-center pointer-events-none">
          <div className="bg-rose-950/85 backdrop-blur-md border border-rose-500/40 rounded-xl px-4 py-3 text-rose-100 shadow-2xl max-w-sm text-center">
            <p className="text-xs font-bold tracking-wide">{isHistorical ? 'HISTORICAL DATA UNAVAILABLE' : 'WEATHER DATA UNAVAILABLE'}</p>
            <p className="text-[10px] mt-1 text-rose-200/90 leading-relaxed">{unavailableReason ?? 'The requested window lies outside the weather data domain (India).'}</p>
            <button
              type="button"
              onClick={resetFeed}
              className="mt-2 text-[10px] font-bold text-rose-100 border border-rose-500/50 rounded-lg px-2.5 py-1 hover:bg-rose-800/60 pointer-events-auto"
            >
              Reset view
            </button>
          </div>
        </div>
      )}
      {loading && (
        <div className="absolute inset-x-0 top-24 z-20 flex justify-center pointer-events-none">
          <div className="bg-slate-950/75 backdrop-blur-md border border-slate-700/80 rounded-xl px-3 py-2 text-slate-300 text-[10px] flex items-center gap-2">
            <Loader2 className="w-3.5 h-3.5 animate-spin text-sky-400" /> Loading {feed.kind === 'weather' ? variableLabel(feed.variable) : 'flood-risk'} grid…
          </div>
        </div>
      )}

      {/* ------------ Pick tool ------------ */}
      {picker && (
        <div className="absolute bottom-24 left-3 z-30 pointer-events-auto bg-slate-950/85 backdrop-blur-md border border-slate-700/80 rounded-xl shadow-2xl p-3 w-64 max-w-[calc(100%-8px)]">
          <div className="flex items-start justify-between gap-2">
            <p className="text-[10px] font-bold uppercase tracking-wide text-sky-400">Point picker</p>
            <button type="button" onClick={() => setPicker(null)} className="text-slate-500 hover:text-white">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
          <p className="text-[11px] text-slate-300 mt-1">
            {picker.lat.toFixed(4)}°, {picker.lng.toFixed(4)}°
          </p>
          {picker.value != null && (
            <p className="mt-1.5 text-[11px] text-slate-200 flex items-baseline gap-1.5">
              <span className="text-slate-500">Cell:</span>
              <b>{picker.label}</b>
            </p>
          )}
          {picker.weather ? (
            isHistorical && 'is_historical' in picker.weather ? (
              <HistoricalPointPanel
                weather={picker.weather}
                dayMode={dayMode}
                year={historicalYear ?? picker.weather.year}
                month={historicalMonth ?? picker.weather.month}
                day={historicalDay}
              />
            ) : (
              <LivePointPanel weather={picker.weather} />
            )
          ) : picker.value != null ? (
            <p className="mt-2 text-[10px] text-slate-500">enriching point details…</p>
          ) : (
            <p className="mt-2 text-[10px] text-slate-500 flex items-center gap-1.5">
              <Loader2 className="w-3 h-3 animate-spin" /> fetching point weather…
            </p>
          )}
        </div>
      )}

      {/* ------------ Timeline (bottom) — live forecasts only ------------ */}
      {!isHistorical && (
        <div className="absolute bottom-0 left-0 right-0 z-30 pointer-events-none px-2 sm:px-3 pb-2">
          <div className="pointer-events-auto bg-slate-950/80 backdrop-blur-md border border-slate-700/80 rounded-xl px-3 py-2 shadow-2xl">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[9px] font-bold uppercase tracking-wider text-slate-500 w-9">Timeline</span>
              <button
                type="button"
                onClick={() => changeHour(0)}
                className="tl-btn"
                title="Now"
              >
                NOW
              </button>
              <button type="button" onClick={() => changeHour(Math.max(0, (effectiveHour === 0 ? 0 : effectiveHour) - 1))} className="tl-btn" title="Previous hour" aria-label="Previous hour">
                <SkipBack className="w-3 h-3" />
              </button>
              <button
                type="button"
                onClick={togglePlay}
                disabled={currentOnly || feed.kind !== 'weather'}
                className={`tl-btn ${currentOnly || feed.kind !== 'weather' ? 'opacity-40 cursor-not-allowed' : ''}`}
                title={currentOnly ? 'Current conditions only' : 'Play hourly forecast'}
                aria-label="Play hourly forecast"
              >
                {playing ? <Pause className="w-3 h-3" /> : <Play className="w-3 h-3" />}
              </button>
              <button type="button" onClick={() => changeHour(Math.min(HOURLY_MAX, effectiveHour + 1))} className="tl-btn" title="Next hour" aria-label="Next hour">
                <SkipForward className="w-3 h-3" />
              </button>
              <input
                id="weather-hour-slider"
                type="range"
                min={0}
                max={HOURLY_MAX}
                value={effectiveHour}
                disabled={currentOnly || feed.kind !== 'weather'}
                onChange={(e) => changeHour(Number(e.target.value))}
                className="flex-1 min-w-24 accent-sky-500"
              />
              <span className="text-[11px] font-bold text-sky-300 w-24 text-right whitespace-nowrap">
                {currentOnly ? 'Now (current)' : effectiveHour === 0 ? 'Now' : `+${effectiveHour}h · ${hourClockLabel(effectiveHour)}`}
              </span>
            </div>
            {currentOnly && (
              <p className="text-[9px] text-amber-400/90 mt-1">This layer only exists for the exact current moment — timeline locked to Now.</p>
            )}
            {feed.kind === 'flood' && (
              <p className="text-[9px] text-slate-500 mt-1">
                Flood-risk overlay combines current precipitation with SRTM terrain — independent of the hourly timeline.
              </p>
            )}
            {windActive && windField && (
              <p className="text-[9px] text-sky-400/90 mt-0.5">Wind field: hour-0 model run (speed+direction → u/v), animated across all stops.</p>
            )}
          </div>
        </div>
      )}

      {/* Historical-mode bottom bar: month timeline + date control */}
      {isHistorical && historicalYear != null && historicalMonth != null && (
        <div className="absolute bottom-0 left-0 right-0 z-30 pointer-events-none px-2 sm:px-3 pb-2">
          <div className="pointer-events-auto bg-slate-950/85 backdrop-blur-md border border-violet-800/50 rounded-xl px-3 py-2 shadow-2xl space-y-1.5">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <p className="text-[9px] text-violet-300/90 flex items-center gap-1.5">
                <CalendarDays className="w-3 h-3" />
                Historical: real ERA5 reanalysis — completed months only, never invented. Monthly shows the month's aggregate; Daily plays back that single day's grid (wind particles available per day).
              </p>
              <span
                className="text-[9px] font-bold tracking-wide text-violet-100 bg-violet-950/70 border border-violet-500/50 rounded-full px-2 py-0.5"
                id="weather-not-live"
              >
                NOT LIVE
              </span>
            </div>
            <MonthTimeline
              year={historicalYear}
              completed={completedMonthsFor(yearAvail, historicalYear)}
              selected={historicalMonth}
              onSelect={(m) => {
                setHistoricalMonth(m);
                setHistoricalDay(1);
              }}
            />
            <DateControl
              mode={dayMode}
              year={historicalYear}
              month={historicalMonth}
              day={historicalDay}
              onModeChange={setDayMode}
              onDayChange={setHistoricalDay}
            />
            <p className="text-[9px] text-slate-500" id="weather-historical-caption">
              {completedPeriodCaption(yearAvail, historicalYear)} · Historical / completed months only · NOT LIVE
            </p>
          </div>
        </div>
      )}

      {/* global css for map internals */}
      <style>{`
        .icon-btn{
          background: rgba(2,6,23,0.8);
          border: 1px solid rgba(51,65,85,0.8);
          border-radius: 0.65rem;
          padding: 0.45rem 0.55rem;
          color: rgb(203 213 225);
        }
        .icon-btn:hover{ border-color: rgb(100 116 139); color: #fff; }
        .tl-btn{
          display:inline-flex; align-items:center; gap:0.3rem;
          font-size:10px; font-weight:700; letter-spacing:0.05em;
          padding:0.35rem 0.55rem; border-radius:0.5rem;
          background: rgb(2 6 23 / 0.6); border:1px solid rgb(51 65 85);
          color: rgb(226 232 240);
        }
        .tl-btn:hover{ border-color: rgb(148 163 184); }
        .factor-btn{
          font-size:9px; font-weight:700; padding:0.25rem 0.4rem; border-radius:0.4rem;
          background: rgb(2 6 23 / 0.6); border:1px solid rgb(51 65 85); color: rgb(148 163 184);
        }
        .factor-btn:hover{ color:#fff; }
        .leaflet-container{
          background:#0a0e1a; font-family:inherit;
        }
      `}</style>
    </div>
  );
};

function LivePointPanel({ weather }: { weather: WeatherResponse }) {
  return (
    <div className="mt-2 space-y-1 text-[10px] text-slate-300">
      <p>
        Temp: <b>{weather.current?.temperature_c != null ? `${weather.current.temperature_c.toFixed(1)}°C` : '—'}</b>
        {weather.current?.apparent_temperature_c != null && ` (feels ${weather.current.apparent_temperature_c.toFixed(1)}°)`}
      </p>
      {weather.current?.weather_description && <p>{weather.current.weather_description}</p>}
      <p>
        Wind: <b>{weather.current?.wind_speed_kmh != null ? `${weather.current.wind_speed_kmh.toFixed(1)} km/h` : '—'}</b>
        {weather.current?.wind_direction_deg != null && ` @ ${Math.round(weather.current.wind_direction_deg)}°`}
      </p>
      <p>
        Rain: <b>{weather.current?.precipitation_mm != null ? `${weather.current.precipitation_mm.toFixed(1)} mm` : '—'}</b>
      </p>
      <p>Status: <StatusChip status={weather.data_status} /></p>
    </div>
  );
}

interface HistoricalPointPanelProps {
  weather: HistoricalWeatherResponse;
  dayMode: DayMode;
  year: number;
  month: number;
  day: number;
}

function historicalDayRow(weather: HistoricalWeatherResponse, year: number, month: number, day: number) {
  const iso = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  return weather.daily?.find((r) => r.date === iso) ?? null;
}

function HistoricalPointPanel({ weather, dayMode, year, month, day }: HistoricalPointPanelProps) {
  const v = weather.variables ?? {};
  const value = (key: string): string | null => {
    const entry = v[key];
    if (entry == null || entry.value == null) return null;
    const decimals = entry.unit === 'mm' || entry.unit === '°C' ? 1 : 0;
    return `${entry.value.toFixed(decimals)} ${entry.unit ?? ''}`.trim();
  };
  // The backend now reports the real wettest day in `top_rain_day`; deriving it
  // from the daily rows here stays a harmless, consistent safety net.
  const wettestDay = (() => {
    const days = weather.daily ?? [];
    let best: { date: string; mm: number } | null = null;
    for (const d of days) {
      if (d.precipitation_mm != null && (best == null || d.precipitation_mm > best.mm)) {
        best = { date: d.date, mm: d.precipitation_mm };
      }
    }
    return best;
  })();
  if (weather.data_status !== 'HISTORICAL') {
    return (
      <div className="mt-2 space-y-1 text-[10px] text-slate-300">
        <p className="text-rose-400">{weather.reason ?? 'Historical record unavailable for this point and month.'}</p>
        <p>Status: <StatusChip status={weather.data_status} /></p>
      </div>
    );
  }
  const row = dayMode === 'daily' ? historicalDayRow(weather, year, month, day) : null;
  return (
    <div className="mt-2 space-y-1 text-[10px] text-slate-300">
      {dayMode === 'daily' ? (
        row ? (
          <>
            <p>
              Date: <b className="text-sky-300">{fmtDateLabel(year, month, day)}</b>
            </p>
            {row.precipitation_mm != null && (
              <p>
                Rainfall: <b>{row.precipitation_mm.toFixed(1)} mm</b>
              </p>
            )}
            {row.temperature_2m_mean != null && (
              <p>
                Temperature: <b>{row.temperature_2m_mean.toFixed(1)} °C</b>
                {row.temperature_2m_max != null && row.temperature_2m_min != null
                  ? ` (max ${row.temperature_2m_max.toFixed(1)} / min ${row.temperature_2m_min.toFixed(1)})`
                  : ''}
              </p>
            )}
            {row.wind_speed_10m_max != null && (
              <p>
                Wind speed: <b>{row.wind_speed_10m_max.toFixed(1)} km/h</b>
                {row.wind_direction_10m_dominant != null ? ` @ ${Math.round(row.wind_direction_10m_dominant)}°` : ''}
              </p>
            )}
            {row.wind_gusts_10m_max != null && (
              <p>
                Wind gusts: <b>{row.wind_gusts_10m_max.toFixed(1)} km/h</b>
              </p>
            )}
            {row.surface_pressure_mean != null && (
              <p>
                Pressure: <b>{row.surface_pressure_mean.toFixed(0)} hPa</b>
              </p>
            )}
            {'relative_humidity_mean' in (row as unknown as Record<string, unknown>) &&
              (row as unknown as { relative_humidity_mean?: number }).relative_humidity_mean != null && (
                <p>
                  Humidity: <b>{(row as unknown as { relative_humidity_mean: number }).relative_humidity_mean.toFixed(0)}%</b>
                </p>
              )}
            <p>Period: <b className="text-violet-300">{weather.period ?? `${year}-${String(month).padStart(2, '0')}`}</b></p>
            <p>Source: <b className="text-slate-200">{weather.data_source}</b></p>
            <p>Status: <StatusChip status={weather.data_status} /></p>
          </>
        ) : (
          <>
            <p>
              Date: <b className="text-sky-300">{fmtDateLabel(year, month, day)}</b>
            </p>
            <p className="text-amber-300">
              No daily record for {fmtDateLabel(year, month, day)} in this month's archive — values remain a monthly aggregate.
            </p>
            <p>Status: <StatusChip status={weather.data_status} /></p>
          </>
        )
      ) : (
        <>
          <p>
            Temp (mean): <b>{value('temperature_2m') ?? '—'}</b>
          </p>
          <p>
            Precip (month total): <b>{value('precipitation') ?? '—'}</b>
          </p>
<p>
              Wind (daily max mean): <b>{value('wind_speed_10m') ?? '—'}</b>
            </p>
            {value('storm_days') && <p>Storm days: <b>{value('storm_days')}</b></p>}
            {wettestDay && (
              <p>
                Wettest day: <b>{wettestDay.date}</b> ({wettestDay.mm.toFixed(1)} mm)
              </p>
            )}
          <p>
            Period: <b className="text-violet-300">{weather.period ?? `${weather.year}-${String(weather.month).padStart(2, '0')}`}</b>
          </p>
          <p>Source: <b className="text-slate-200">{weather.data_source}</b></p>
          <p>Status: <StatusChip status={weather.data_status} /></p>
        </>
      )}
    </div>
  );
}

function escapeHtml(value: string | number | null | undefined): string {
  return String(value ?? '').replace(
    /[&<>"']/g,
    (c) => (({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }) as Record<string, string>)[c]
  );
}

export default WeatherMap;