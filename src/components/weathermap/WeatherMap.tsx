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
  RotateCcw,
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
import {
  DEFAULT_RASTER_OPACITY,
  RASTER_OPACITY_PRESETS,
  paintGridRaster,
  rasterOpacityValue,
  toOpaqueColor,
  type RasterBounds,
  type RasterOpacityId,
} from './WeatherGridRaster';

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

/** Parse the "north,south,east,west" viewport string into raster bounds. */
function parseViewportBounds(raw: string): RasterBounds | null {
  const parts = raw.split(',').map((v) => Number(v));
  if (parts.length !== 4 || parts.some((v) => !Number.isFinite(v))) return null;
  const [north, south, east, west] = parts;
  return { north, south, east, west };
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
  const weatherRasterRef = useRef<L.ImageOverlay | null>(null);
  const floodRasterRef = useRef<L.ImageOverlay | null>(null);
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
  // Opacity of the weather/flood raster. Defaults to a light wash so the street
  // map stays clearly readable underneath the forecast colours.
  const [rasterOpacity, setRasterOpacity] = useState<RasterOpacityId>(DEFAULT_RASTER_OPACITY);

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
  const [historicalBarOpen, setHistoricalBarOpen] = useState(true);
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
      weatherRasterRef.current = null;
      floodRasterRef.current = null;
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
    // Dependency is deliberately ONLY `basemap`. This used to include
    // `viewportKey`, which changes 500ms after every pan/zoom — so the whole
    // OpenStreetMap tile layer was destroyed and rebuilt after each zoom
    // gesture. That is the "flicker"/tile-reload the desktop users reported.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [basemap]);

  // ---------------- focus / initial view ----------------
  // Camera framing lives here and nowhere else. It runs on mount and on an
  // explicit region change, and on demand from the "reset view" button. It is
  // deliberately NOT driven by `viewportKey` — doing that used to re-fit the map
  // 500ms after every pan/zoom, discarding the user's chosen zoom.
  const applyFocusView = useCallback((): void => {
    const map = mapRef.current;
    if (!map) return;
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
  }, [focus]);

  useEffect(() => {
    const raf = window.requestAnimationFrame(applyFocusView);
    return () => window.cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus]);

  const resetView = (): void => {
    applyFocusView();
  };

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

// ---------------- rendering weather/hazard raster ----------------
  // The grid is painted into a single canvas and shown as one non-interactive
  // imageOverlay instead of ~13,000 SVG rectangles. This keeps the OpenStreetMap
  // base legible underneath, keeps map clicks (and the point picker) working,
  // and lets pinch/drag stay smooth on a phone.
  useEffect(() => {
    const layer = weatherLayerRef.current;
    if (!layer) return;
    layer.clearLayers();
    weatherRasterRef.current = null;
    if (feed.kind === 'flood') return;
    const g = grid;
    if (!g || g.points.length === 0) return;
    const v = g.variable as WeatherVariable;
    const meta = WEATHER_LAYERS[v] ?? WEATHER_LAYERS.temperature_2m;
    const stepLat = g.steps?.latitude || 0.25;
    const stepLng = g.steps?.longitude || 0.25;
    const raster = paintGridRaster(
      g.points.map((p) => ({
        lat: p.latitude,
        lng: p.longitude,
        // No-data cells stay transparent rather than being painted grey, so the
        // base map shows through wherever the provider returned nothing.
        color: p.value != null ? colorForValue(p.value, meta) : null,
      })),
      g.bounds,
      stepLat,
      stepLng
    );
    if (!raster) return;
    const overlay = L.imageOverlay(
      raster.url,
      [
        [g.bounds.south, g.bounds.west],
        [g.bounds.north, g.bounds.east],
      ],
      { opacity: rasterOpacityValue(rasterOpacity), interactive: false }
    );
    overlay.addTo(layer);
    weatherRasterRef.current = overlay;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [grid, feed]);

  // ---------------- rendering flood raster ----------------
  // Same single-canvas treatment as the weather grid. The flood response carries
  // no bounds/steps of its own, so we keep the viewport window and 0.3 deg step
  // the previous rectangle overlay used.
  useEffect(() => {
    const layer = floodLayerRef.current;
    if (!layer) return;
    layer.clearLayers();
    floodRasterRef.current = null;
    if (feed.kind !== 'flood' || !floodGrid) return;
    const bounds = parseViewportBounds(viewportBounds);
    if (!bounds) return;
    const raster = paintGridRaster(
      floodGrid.points.map((p) => ({
        lat: p.latitude,
        lng: p.longitude,
        color: p.risk_score == null ? null : toOpaqueColor(FLOOD_RISK_COLORS[p.risk_level ?? 'LOW'] ?? 'rgb(148,163,184)'),
      })),
      bounds,
      0.3,
      0.3
    );
    if (!raster) return;
    const overlay = L.imageOverlay(
      raster.url,
      [
        [bounds.south, bounds.west],
        [bounds.north, bounds.east],
      ],
      { opacity: rasterOpacityValue(rasterOpacity), interactive: false }
    );
    overlay.addTo(layer);
    floodRasterRef.current = overlay;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [floodGrid, feed, viewportKey, isHistorical, historicalYear, historicalMonth]);

  // Keep both rasters at the user-chosen opacity without rebuilding the canvas.
  useEffect(() => {
    const opacity = rasterOpacityValue(rasterOpacity);
    weatherRasterRef.current?.setOpacity(opacity);
    floodRasterRef.current?.setOpacity(opacity);
  }, [rasterOpacity]);

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
    <div
      data-weather-map-root
      className="relative isolate flex flex-col rounded-xl border border-slate-700 bg-[#0a0e1a] shadow-2xl select-none"
    >
      {/* =================================================================
          Control stack — laid out in NORMAL FLOW above the map.
          Order: 1) location/header, 2) Historical date control, 3) Layers.
          Nothing here is absolutely positioned over the map, so the panels can
          never overlap the map or each other, and they scroll away with the
          page instead of floating over it.
          ================================================================= */}
      <div className="shrink-0 border-b border-slate-800 bg-[#0a0e1a]">
        {/* ---------- Row 1: location / header ---------- */}
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-800/70 px-3 py-2">
          <div className="flex items-center gap-2">
            <CloudSun className="w-4 h-4 text-sky-400 shrink-0" />
            <span className="min-w-0">
              <span className="block text-xs font-bold uppercase tracking-wide text-slate-100 truncate">
                {regionLabel}
              </span>
              <span className="block text-[10px] font-normal normal-case tracking-normal text-slate-400 whitespace-nowrap">
                | Weather &amp; Hazard Forecast
              </span>
            </span>
          </div>
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
          {viewOutsideIndia && (
            <div className="flex items-center gap-2 rounded-xl border border-amber-600/70 bg-amber-900/60 px-2.5 py-1" data-coverage-badge>
              <Waves className="w-3.5 h-3.5 text-amber-300" />
              <span className="text-[11px] font-medium text-amber-100 whitespace-nowrap">
                Outside India — showing empty grid
              </span>
            </div>
          )}
        </div>

        {/* ---------- Row 2: Historical date control (single control) ---------- */}
        {/* The year/month selects used to sit in the map's top bar while the
            month timeline + day control sat in a separate bottom bar, giving two
            competing historical controls. They are now one row.

            Rendered whenever we have availability data OR we are already in
            historical mode — otherwise a failed availability fetch would leave a
            historical user with no way to change month, or to return to live. */}
        {(yearAvail.length > 0 || isHistorical) && (
          <div className="border-b border-slate-800/70 px-3 py-2">
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                id="weather-historical-toggle"
                onClick={() => setHistoricalBarOpen((o) => !o)}
                aria-expanded={historicalBarOpen}
                aria-controls="weather-historical-panel"
                className="flex min-h-10 items-center gap-1.5 rounded-lg border border-violet-800/60 bg-violet-950/40 px-2.5 py-1.5 text-[11px] font-bold uppercase tracking-wider text-violet-100 hover:bg-violet-900/40"
              >
                <CalendarDays className="w-3.5 h-3.5 text-violet-300" />
                Historical
                {historicalBarOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronUp className="w-3.5 h-3.5" />}
              </button>

              <div className="flex min-h-10 items-center gap-1.5 rounded-lg border border-violet-800/60 bg-violet-950/40 px-2 py-1.5" id="weather-historical-selector">
                <select
                  aria-label="Weather data mode"
                  className="text-[11px] font-bold bg-transparent text-slate-100 outline-none cursor-pointer"
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
                {isHistorical && historicalYear != null && (
                  <select
                    aria-label="Historical month"
                    className="text-[11px] font-bold bg-transparent text-slate-100 outline-none cursor-pointer"
                    value={historicalMonth ?? 1}
                    onChange={(e) => {
                      setHistoricalMonth(Number(e.target.value));
                      setHistoricalDay(1);
                    }}
                  >
                    {Array.from({ length: historicalMonthsFor(historicalYear) }, (_, i) => i + 1).map((m) => (
                      <option key={m} value={m}>
                        {new Date(0, m - 1, 1).toLocaleString('en-IN', { month: 'short' }).toLowerCase()}
                      </option>
                    ))}
                  </select>
                )}
              </div>

              {isHistorical && (
                <span
                  className="text-[10px] font-bold tracking-wide text-violet-100 bg-violet-950/70 border border-violet-500/50 rounded-full px-2 py-1"
                  id="weather-not-live"
                >
                  NOT LIVE
                </span>
              )}

              {isHistorical && historicalYear != null && historicalMonth != null && historicalBarOpen && (
                <p className="text-[10px] text-slate-500" id="weather-historical-caption">
                  {completedPeriodCaption(yearAvail, historicalYear)} · completed months only · NOT LIVE
                </p>
              )}
            </div>

            {isHistorical && historicalYear != null && historicalMonth != null && historicalBarOpen && (
              <div id="weather-historical-panel" className="mt-2 space-y-2">
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
              </div>
            )}
          </div>
        )}

        {/* ---------- Row 3: Layers ---------- */}
        <div id="weather-hazard-layers" className="px-3 py-2">
          <div className="flex items-center justify-between gap-2">
            <button
              type="button"
              id="weather-hazard-layers-toggle"
              onClick={() => setLayersOpen((o) => !o)}
              aria-expanded={layersOpen}
              aria-controls="weather-hazard-layers-body"
              className="flex min-h-10 items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-200"
            >
              <Layers className="w-3.5 h-3.5 text-sky-400" /> Layers
              {layersOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronUp className="w-3.5 h-3.5" />}
            </button>
            <button
              type="button"
              onClick={resetFeed}
              title="Reset to temperature"
              aria-label="Reset layers to temperature"
              className="flex min-h-10 min-w-10 items-center justify-center text-slate-500 hover:text-sky-300"
            >
              <MapIcon className="w-3.5 h-3.5" />
            </button>
          </div>

          {layersOpen && (
            <div id="weather-hazard-layers-body" className="mt-2 space-y-2.5">
              {/* Raster opacity — lets the user dial the forecast wash back so the
                  street map reads clearly underneath. */}
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[9px] font-bold uppercase tracking-wide text-slate-500">Overlay</span>
                {RASTER_OPACITY_PRESETS.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    id={`weather-raster-opacity-${p.id}`}
                    onClick={() => setRasterOpacity(p.id)}
                    aria-pressed={rasterOpacity === p.id}
                    className={`min-h-9 rounded-md border px-2 py-1 text-[10px] font-bold transition ${
                      rasterOpacity === p.id
                        ? 'border-sky-500 bg-sky-600 text-white'
                        : 'border-slate-700 bg-slate-900/60 text-slate-300 hover:border-slate-500 hover:text-white'
                    }`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>

              {/* Category tabs */}
              <div className="flex flex-wrap gap-1">
                {(['weather', 'hazards'] as const).map((c) => (
                  <button
                    key={c}
                    type="button"
                    id={`weather-hazard-category-${c}`}
                    onClick={() => setCategory(c)}
                    aria-pressed={category === c}
                    className={`min-h-9 flex-1 rounded-md border px-2 py-1 text-[10px] font-bold uppercase tracking-wide transition ${
                      category === c ? 'bg-sky-600 border-sky-500 text-white' : 'bg-slate-900 border-slate-700 text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    {c}
                  </button>
                ))}
              </div>

              {/* Weather list */}
              {category === 'weather' && (
                <div className="grid grid-cols-2 gap-1 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
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
                        className={`min-h-10 text-left text-[10px] px-2 py-1.5 rounded-md border transition flex items-center justify-between gap-1 ${
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
                <div className="grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
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
                        className={`min-h-10 text-left px-2 py-1.5 rounded-md border transition ${
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
      </div>

      {/* =================================================================
          Map — an explicit, usable height rather than a flex share.
          `flex-1 min-h-0` here collapsed to zero: the control stack above is
          `shrink-0`, so with Layers expanded there was no free space left and
          the root's `overflow-hidden` then clipped what remained. A defined
          height keeps the map at full size, and because the page is no longer
          height-locked, `<main>` scrolls down to reach it.
          `overflow-hidden` is kept here ONLY to clip the Leaflet canvas to the
          rounded map boundary — this element does not scroll.
          ================================================================= */}
      <div className="relative h-[420px] sm:h-[480px] lg:h-[560px] shrink-0 overflow-hidden">
      <div ref={containerRef} id="weather-hazard-map-canvas" className="absolute inset-0 z-0" />

      {/* ------------ Map toolbar (search, settings, locate, fullscreen, basemap) ------------ */}
      <div className="absolute top-0 left-0 right-0 z-30 pointer-events-none">
        <div className="m-2 flex items-center gap-2">
          <div className="pointer-events-auto relative min-w-0 flex-1 max-w-xs">
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
                  <button type="button" onClick={runSearch} className="text-slate-400 hover:text-slate-100" aria-label="Search">
                    <Search className="w-3.5 h-3.5" />
                  </button>
                  <button type="button" onClick={() => setSearchOpen(false)} aria-label="Close search" className="text-slate-500 hover:text-slate-200">
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
                className="bg-slate-950/80 backdrop-blur-md border border-slate-700/80 rounded-xl px-3 py-1.5 min-h-10 flex items-center gap-2 text-slate-300 hover:border-slate-500"
              >
                <Search className="w-3.5 h-3.5" />
                <span className="text-[11px]">Search place…</span>
              </button>
            )}
          </div>

          <div className="pointer-events-auto ml-auto flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => setSettingsOpen((s) => !s)}
              id="weather-settings-btn"
              aria-label="Weather settings"
              title="Weather settings"
              className="inline-flex min-h-10 items-center gap-1.5 rounded-xl border border-slate-700/80 bg-slate-950/80 px-2.5 py-1.5 text-slate-300 hover:text-white hover:border-slate-500"
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
            <button type="button" onClick={locateMe} title="Use my location" aria-label="Use my location" className="icon-btn">
              <LocateFixed className="w-4 h-4" />
            </button>
            <button type="button" onClick={resetView} title="Reset map view" aria-label="Reset map view" className="icon-btn">
              <RotateCcw className="w-4 h-4" />
            </button>
            <button type="button" onClick={toggleFullscreen} title="Fullscreen" aria-label="Fullscreen" className="icon-btn">
              <Expand className="w-4 h-4" />
            </button>
            {(['street'] as const).map((b) => (
              <button
                key={b}
                type="button"
                id={`weather-basemap-${b}`}
                onClick={() => setBasemap(b)}
                aria-pressed={basemap === b}
                className={`min-h-10 px-2.5 py-1.5 text-[10px] font-bold uppercase tracking-wide rounded-lg border transition ${
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

      {/* Wind particles toggle + controls — live, and historical per-day playback */}
      {(!isHistorical || dayMode === 'daily') && feed.kind === 'weather' && feed.variable === WIND_LAYER && (
        <div className="absolute top-14 right-3 z-40 pointer-events-auto flex flex-col items-start gap-1.5">
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
                <button type="button" onClick={() => (windLayerRef.current!.isRunning() ? windLayerRef.current!.pause() : windLayerRef.current!.resume())} className="text-slate-300 hover:text-white p-1" title="Pause / play" aria-label="Pause or play wind particles">
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
      {/* Bottom-left, clear of the wind toggle (top-right), the legend
          (bottom-right) and the live timeline (bottom, live mode only). The
          historical control is no longer a map overlay, so it cannot collide. */}
      {picker && (
        <div
          className={`absolute left-3 z-30 pointer-events-auto bg-slate-950/85 backdrop-blur-md border border-slate-700/80 rounded-xl shadow-2xl p-3 w-64 max-w-[calc(100%-1.5rem)] max-h-[calc(100%-8rem)] overflow-y-auto ${
            isHistorical ? 'bottom-3' : 'bottom-24'
          }`}
        >
          <div className="flex items-start justify-between gap-2">
            <p className="text-[10px] font-bold uppercase tracking-wide text-sky-400">Point picker</p>
            <button
              type="button"
              onClick={() => setPicker(null)}
              aria-label="Close point picker"
              title="Close point picker"
              className="flex min-h-10 min-w-10 items-center justify-center -mt-2 -mr-2 text-slate-500 hover:text-white"
            >
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
      </div>

      {/* global css for map internals */}
      <style>{`
        .icon-btn{
          display:inline-flex; align-items:center; justify-content:center;
          min-height:2.5rem; min-width:2.5rem;
          background: rgba(2,6,23,0.8);
          border: 1px solid rgba(51,65,85,0.8);
          border-radius: 0.65rem;
          padding: 0.45rem 0.55rem;
          color: rgb(203 213 225);
        }
        .icon-btn:hover{ border-color: rgb(100 116 139); color: #fff; }
        .tl-btn{
          display:inline-flex; align-items:center; justify-content:center; gap:0.3rem;
          min-height:2.5rem;
          font-size:10px; font-weight:700; letter-spacing:0.05em;
          padding:0.35rem 0.55rem; border-radius:0.5rem;
          background: rgb(2 6 23 / 0.6); border:1px solid rgb(51 65 85);
          color: rgb(226 232 240);
        }
        .tl-btn:hover{ border-color: rgb(148 163 184); }
        .factor-btn{
          display:inline-flex; align-items:center; justify-content:center;
          min-height:2.5rem; min-width:2.5rem;
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

export default WeatherMap;
