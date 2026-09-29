import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Maximize2, Minimize2 } from 'lucide-react';
import L from 'leaflet';
import { Habitation, RelocationSite, RedZone, MapLayerItem, EvacuationPlanResponse, RoadConditionsResponse, FloodForecastResponse, DataStatusEntry, BasemapKey, HistoricalAvailability, HistoricalBaseline, HistoricalDistrictSummary, FieldReport, RiskZone, RainfallGridPoint, DisasterEventResponse, BhuvanShortestPathResponse, SafeRouteOption, TerrainResponse } from '../types';
import type { RegionViewportFocus } from '../lib/regionViewport';
import { MapLayerPanel } from './MapLayerPanel';
import { DataSourceStatus } from './DataSourceStatus';
import { HistoricalDistrictPanel } from './HistoricalDistrictPanel';
import { apiService } from '../services/api';
import { TERRAIN_SOURCE, terrainPointPopupHtml, type TerrainPointUnavailable } from '../lib/terrainPopup';

interface LeafletMapProps {
  habitations: Habitation[];
  relocationSites: RelocationSite[];
  redZones: RedZone[];
  infrastructure: MapLayerItem[];
  fieldReports?: FieldReport[];
  selectedHabitationId?: string;
  selectedSiteId?: string;
  focus?: RegionViewportFocus | null;
  onSelectHabitation: (hab: Habitation) => void;
  onSelectSite: (site: RelocationSite) => void;
  evacuationRoute?: EvacuationPlanResponse | null;
  evacuationRoadConditions?: RoadConditionsResponse | null;
  evacuationPickEnabled?: boolean;
  onEvacuationOriginPicked?: (lat: number, lng: number) => void;
  floodForecast?: FloodForecastResponse | null;
  dataStatus?: DataStatusEntry[] | null;
  historicalBaseline?: HistoricalBaseline | null;
  historicalSummaries?: HistoricalDistrictSummary[];
  historicalAvailability?: HistoricalAvailability | null;
  historicalDistrictId?: number | null;
  onHistoricalDistrictChange?: (districtId: number) => void;
  riskZones?: RiskZone[];
  rainfallGrid?: RainfallGridPoint[];
  disasterEvents?: DisasterEventResponse[];
  bhuvanRoute?: BhuvanShortestPathResponse | null;
  safeRoute?: SafeRouteOption | null;
}

export const LeafletMap: React.FC<LeafletMapProps> = ({
  habitations,
  relocationSites,
  redZones,
  infrastructure,
  fieldReports = [],
  selectedHabitationId,
  selectedSiteId,
  focus,
  onSelectHabitation,
  onSelectSite,
  evacuationRoute,
  evacuationRoadConditions,
  evacuationPickEnabled = false,
  onEvacuationOriginPicked,
  floodForecast = null,
  dataStatus = null,
  historicalBaseline = null,
  historicalSummaries = [],
  historicalAvailability = null,
  historicalDistrictId = null,
  onHistoricalDistrictChange = () => {},
  riskZones = [],
  rainfallGrid = [],
  disasterEvents = [],
  bhuvanRoute = null,
  safeRoute = null,
}) => {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<L.Map | null>(null);
  const gisMapComponentRef = useRef<HTMLDivElement>(null);
  const basemapLayerRef = useRef<L.Layer | null>(null);
  const pickEnabledRef = useRef(evacuationPickEnabled);
  const onPickRef = useRef(onEvacuationOriginPicked);
  pickEnabledRef.current = evacuationPickEnabled;
  onPickRef.current = onEvacuationOriginPicked;
  const layersGroupRef = useRef<{
    redZonesLayer?: L.LayerGroup;
    habitationsLayer?: L.LayerGroup;
    sitesLayer?: L.LayerGroup;
    infraLayer?: L.LayerGroup;
    routeLayer?: L.LayerGroup;
    floodLayer?: L.LayerGroup;
    reportsLayer?: L.LayerGroup;
    riskZonesLayer?: L.LayerGroup;
    rainfallLayer?: L.LayerGroup;
    disasterLayer?: L.LayerGroup;
    bhuvanLayer?: L.LayerGroup;
    safeRouteLayer?: L.LayerGroup;
  }>({});
  const wmsLayerRef = useRef<L.TileLayer.WMS | null>(null);

  // Layer toggles
  const [basemap, setBasemap] = useState<BasemapKey['id']>('street');
  const [showRedZones, setShowRedZones] = useState(true);
  const [visibleHazardTypes, setVisibleHazardTypes] = useState<string[]>([]);
  const [showHabitations, setShowHabitations] = useState(true);
  const [showSites, setShowSites] = useState(true);
  const [showInfra, setShowInfra] = useState(true);
  const [showRoute, setShowRoute] = useState(true);
  const [showFlood, setShowFlood] = useState(false);
  const [showRiskZones, setShowRiskZones] = useState(false);
  const [showRainfall, setShowRainfall] = useState(false);
  const [showBhuvanOverlay, setShowBhuvanOverlay] = useState(false);
  const [showBhuvanRoute, setShowBhuvanRoute] = useState(true);
  const [mapRainfallGrid, setMapRainfallGrid] = useState<RainfallGridPoint[]>([]);
  const rainfallRefreshTimerRef = useRef<number | null>(null);
  // Progressive terrain popup guards: a monotonic seq makes responses from an
  // older click never overwrite the newest popup; the timestamp debounces
  // stray clicks produced at the end of a map drag.
  const terrainPopupSeqRef = useRef(0);
  const lastTerrainClickRef = useRef(0);
  const terrainAbortRef = useRef<AbortController | null>(null);
  const [priorityFilter, setPriorityFilter] = useState<string>('all');
  const [basemapError, setBasemapError] = useState<string | null>(null);

  const availableHazardTypes = Array.from(new Set(redZones.map((z) => z.hazard_type)));
  const hasFloodData = Boolean(floodForecast && (floodForecast.gauges.length > 0 || floodForecast.zones.length > 0));
  const hasRiskZones = riskZones.length > 0;
  const hasRainfallData =
    rainfallGrid.length > 0 ||
    (dataStatus ?? []).some((e) => e.layer === 'rainfall' && e.status === 'LIVE');
  const rainfallStatus =
    (dataStatus ?? []).find((e) => e.layer === 'rainfall')?.status ?? 'NOT CONFIGURED';

  const [fullscreen, setFullscreen] = useState(false);

  useEffect(() => {
    const onFsChange = () => setFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener('fullscreenchange', onFsChange);
    return () => document.removeEventListener('fullscreenchange', onFsChange);
  }, []);

  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;
    const t = window.setTimeout(() => map.invalidateSize(), 60);
    return () => window.clearTimeout(t);
  }, [fullscreen]);

  const toggleFullscreen = () => {
    const el = gisMapComponentRef.current;
    if (!el) return;
    if (fullscreen) {
      if (document.fullscreenElement && document.exitFullscreen) {
        document.exitFullscreen().catch(() => setFullscreen(false));
      } else {
        setFullscreen(false);
      }
      return;
    }
    const elAny = el as HTMLDivElement & {
      requestFullscreen?: () => Promise<void> | void;
      webkitRequestFullscreen?: () => Promise<void> | void;
    };
    if (typeof document.documentElement.requestFullscreen === 'function') {
      try {
        const result = elAny.requestFullscreen?.();
        if (result && typeof result.catch === 'function') {
          result.catch(() => setFullscreen(true));
        }
      } catch {
        setFullscreen(true);
      }
      window.setTimeout(() => {
        if (!document.fullscreenElement) setFullscreen(true);
      }, 350);
    } else if (typeof elAny.webkitRequestFullscreen === 'function') {
      try {
        elAny.webkitRequestFullscreen();
      } catch {
        setFullscreen(true);
      }
      window.setTimeout(() => {
        if (!document.fullscreenElement) setFullscreen(true);
      }, 350);
    } else {
      setFullscreen(true);
    }
  };

  // Initialize Map
  useEffect(() => {
    if (!mapContainerRef.current || mapInstanceRef.current) return;

    const map = L.map(mapContainerRef.current, {
      center: [22.5, 78.9],
      zoom: 5,
      zoomControl: false,
    });

    // Add clean zoom control top-right
    L.control.zoom({ position: 'topright' }).addTo(map);

    // Initialize layer groups
    layersGroupRef.current.redZonesLayer = L.layerGroup().addTo(map);
    layersGroupRef.current.habitationsLayer = L.layerGroup().addTo(map);
    layersGroupRef.current.sitesLayer = L.layerGroup().addTo(map);
    layersGroupRef.current.infraLayer = L.layerGroup().addTo(map);
    layersGroupRef.current.routeLayer = L.layerGroup().addTo(map);
    layersGroupRef.current.floodLayer = L.layerGroup().addTo(map);
    layersGroupRef.current.reportsLayer = L.layerGroup().addTo(map);
    layersGroupRef.current.riskZonesLayer = L.layerGroup().addTo(map);
    layersGroupRef.current.rainfallLayer = L.layerGroup().addTo(map);
    layersGroupRef.current.disasterLayer = L.layerGroup().addTo(map);
    layersGroupRef.current.bhuvanLayer = L.layerGroup().addTo(map);
    layersGroupRef.current.safeRouteLayer = L.layerGroup().addTo(map);

    mapInstanceRef.current = map;

    // Debug hook so automated checks can assert map relocation.
    (window as unknown as { __namsafeMap?: L.Map }).__namsafeMap = map;

    // Evacuation origin picking on click
    map.on('click', (event: L.LeafletMouseEvent) => {
      if (pickEnabledRef.current) {
        onPickRef.current?.(event.latlng.lat, event.latlng.lng);
        return;
      }
      // Debounce: ignore clicks that arrive right after the previous one (a
      // drag's closing click must not spawn a second popup).
      const now = Date.now();
      if (now - lastTerrainClickRef.current < 300) return;
      lastTerrainClickRef.current = now;

      // Additive, progressive: cached elevation first, then slope + full
      // terrain payload. The popup mirrors the terrain request lifecycle:
      // it opens on "Fetching terrain data…", stays in a live LOADING (or
      // bounded RETRYING) state until the provider really answers, and only
      // then renders the real values or the honest terminal reason. A new
      // click (or unmount) aborts the stale in-flight request (monotonic seq
      // guard), so a response from an older click can never overwrite the
      // newest popup, and a real elevation that is already on screen is never
      // wiped by a later failure.
      const { lat, lng } = event.latlng;
      const seq = ++terrainPopupSeqRef.current;
      terrainAbortRef.current?.abort();
      const controller = new AbortController();
      terrainAbortRef.current = controller;

      let popup: L.Popup | null = null;
      try {
        popup = L.popup({ className: 'leaflet-custom-tooltip', maxWidth: 280 })
          .setLatLng(event.latlng)
          .setContent(terrainPointPopupHtml({ lat, lng, elevation: null, point: null }))
          .openOn(map);
      } catch {
        return;
      }
      let lastElev: number | null = null;
      const showRetrying = (): void => {
        if (terrainPopupSeqRef.current !== seq || !popup) return;
        popup.setContent(terrainPointPopupHtml({ lat, lng, elevation: lastElev, point: null, retrying: true }));
      };
      const renderPoint = (point: TerrainResponse | TerrainPointUnavailable): void => {
        if (terrainPopupSeqRef.current !== seq || !popup) return;
        lastElev = (point.elevation_m ?? undefined) === undefined ? lastElev : point.elevation_m;
        popup.setContent(terrainPointPopupHtml({ lat, lng, elevation: lastElev, point }));
      };

      apiService
        .getElevationFast(lat, lng, { signal: controller.signal, onRetry: showRetrying })
        .then((elev) => {
          if (terrainPopupSeqRef.current !== seq || !popup) return;
          if (elev.data_status === 'UNAVAILABLE' || elev.data_status === 'NOT_CONFIGURED') {
            // Terminal from the fast path: report the real outcome. No
            // fabricated "provider is slow" guess — the API lifecycle has
            // already retried transient failures before it reached us.
            renderPoint(elev);
            return;
          }
          lastElev = elev.elevation_m ?? lastElev;
          popup.setContent(terrainPointPopupHtml({ lat, lng, elevation: lastElev, point: null }));
          return apiService.getTerrain(lat, lng, { signal: controller.signal, onRetry: showRetrying }).then((full) => {
            if (terrainPopupSeqRef.current !== seq || !popup) return;
            renderPoint(full);
          });
        })
        .catch(() => {
          // Defensive: a crash inside the chain must never leave a stuck popup.
          if (terrainPopupSeqRef.current !== seq || !popup) return;
          popup.setContent(terrainPointPopupHtml({
            lat, lng, elevation: lastElev,
            point: { data_status: 'UNAVAILABLE', data_source: TERRAIN_SOURCE, reason: 'Terrain request failed unexpectedly.' },
          }));
        });
    });

    // Handle container resize
    const resizeObserver = new ResizeObserver(() => {
      map.invalidateSize();
    });
    resizeObserver.observe(mapContainerRef.current);

    return () => {
      resizeObserver.disconnect();
      terrainAbortRef.current?.abort();
      terrainAbortRef.current = null;
      map.remove();
      mapInstanceRef.current = null;
    };
  }, []);

  // Basemap switcher: Google Maps (primary) / Esri+OSM (fallback when no API key)
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;

    // Remove old basemap layer (may be TileLayer or LayerGroup)
    if (basemapLayerRef.current) {
      map.removeLayer(basemapLayerRef.current);
      basemapLayerRef.current = null;
    }

    setBasemapError(null);

    const googleKey = (import.meta as { env?: Record<string, string> }).env?.VITE_GOOGLE_MAPS_API_KEY || '';

    if (googleKey) {
      // --- Google Maps Platform tiles (official Map Tiles API) ---
      const lyrsMap: Record<BasemapKey['id'], string> = {
        street: 'm',
        satellite: 'y',
        terrain: 't',
      };
      const lyrs = lyrsMap[basemap] ?? 'm';
      const url = `https://maps.googleapis.com/maps/vt?lyrs=${lyrs}&x={x}&y={y}&z={z}&key=${googleKey}`;
      const attribution = 'Map data &copy; <a href="https://www.google.com/maps">Google</a> | SafeMove AI';
      const layer = L.tileLayer(url, {
        attribution,
        maxZoom: 21,
        subdomains: [],
      });
      layer.on('tileerror', () => setBasemapError('MAP SOURCE UNAVAILABLE'));
      basemapLayerRef.current = layer.addTo(map);
    } else {
      // --- Esri + OSM fallback (all free, no key) ---
      const ESRI_ATTR = 'Tiles &copy; Esri | SafeMove AI';

      if (basemap === 'street') {
        // OpenStreetMap standard tiles — real content at every native zoom (z0-19)
        const street = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
          attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors | SafeMove AI',
          maxZoom: 18,
        });
        street.on('tileerror', () => setBasemapError('MAP SOURCE UNAVAILABLE'));
        basemapLayerRef.current = street.addTo(map);
      } else if (basemap === 'satellite') {
        // Satellite imagery (base) + CartoDB transparent label/road overlay
        // CartoDB only_labels tiles are transparent PNG — no opaque background,
        // so satellite imagery stays fully visible with labels/roads on top.
        const imagery = L.tileLayer(
          'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
          {
            attribution: `${ESRI_ATTR} — Source: Esri, Maxar, Earthstar Geographics`,
            maxZoom: 18,
          }
        );
        const labels = L.tileLayer(
          'https://basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}.png',
          {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/">CARTO</a>',
            maxZoom: 18,
          }
        );
        labels.on('tileerror', () => setBasemapError('MAP SOURCE UNAVAILABLE — labels unavailable'));
        basemapLayerRef.current = L.layerGroup([imagery, labels]).addTo(map);
      } else if (basemap === 'terrain') {
        // Esri World_Topo_Map — free, no key; hillshade + contours + labels + roads (verified z0-19)
        const topo = L.tileLayer(
          'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',
          {
            attribution: 'Tiles &copy; Esri — Source: Esri, HERE, Garmin, FAO, NOAA, USGS, OpenStreetMap contributors, and the GIS User Community',
            maxZoom: 19,
          }
        );
        topo.on('tileerror', () => setBasemapError('MAP SOURCE UNAVAILABLE'));
        basemapLayerRef.current = topo.addTo(map);
      }
    }

    // Expose which provider is active for the data-status panel
    (window as unknown as { __namsafeBasemapProvider?: string }).__namsafeBasemapProvider = googleKey ? 'google' : 'esri_fallback';
  }, [basemap]);

  // Keep hazard sub-toggles in sync with whatever zones are loaded
  useEffect(() => {
    setVisibleHazardTypes((prev) => {
      if (availableHazardTypes.length === 0) return prev;
      const missing = availableHazardTypes.filter((t) => !prev.includes(t));
      return missing.length > 0 ? [...prev, ...missing] : prev;
    });
  }, [availableHazardTypes.length]);

  // Update Red Zones Layer
  useEffect(() => {
    const layer = layersGroupRef.current.redZonesLayer;
    if (!layer || !mapInstanceRef.current) return;
    layer.clearLayers();

    if (!showRedZones) return;

    redZones.forEach((zone) => {
      if (visibleHazardTypes.length > 0 && !visibleHazardTypes.includes(zone.hazard_type)) return;

      const getZoneColor = (type: string) => {
        switch (type) {
          case 'Land Subsidence':
            return { fill: '#dc2626', stroke: '#991b1b' }; // red
          case 'Flash Flood':
            return { fill: '#0284c7', stroke: '#0369a1' }; // blue
          case 'Landslide':
            return { fill: '#ea580c', stroke: '#c2410c' }; // orange
          case 'Cloudburst':
            return { fill: '#9333ea', stroke: '#7e22ce' }; // purple
          default:
            return { fill: '#ef4444', stroke: '#b91c1c' };
        }
      };

      const colors = getZoneColor(zone.hazard_type);

      // GeoJSON Polygon
      const geoJsonLayer = L.geoJSON(zone.zone_geometry as any, {
        style: {
          color: colors.stroke,
          weight: 2,
          opacity: 0.8,
          fillColor: colors.fill,
          fillOpacity: 0.25,
          dashArray: zone.hazard_type === 'Land Subsidence' ? '6, 4' : undefined,
        },
      });

      geoJsonLayer.bindTooltip(
        `<strong>${zone.zone_name}</strong><br/><span style="color:${colors.stroke}">${zone.hazard_type}</span> | Risk: ${zone.hazard_score}/100`,
        { sticky: true, className: 'leaflet-custom-tooltip' }
      );

      layer.addLayer(geoJsonLayer);
    });
  }, [redZones, showRedZones, visibleHazardTypes]);

  // Update Flood Forecast Layer (river gauges + inundation zones)
  useEffect(() => {
    const layer = layersGroupRef.current.floodLayer;
    if (!layer || !mapInstanceRef.current) return;
    layer.clearLayers();

    if (!showFlood || !floodForecast) return;

    // Gauges (colored by risk level)
    floodForecast.gauges.forEach((gauge) => {
      const riskColor =
        gauge.risk_level === 'EXTREME'
          ? '#dc2626'
          : gauge.risk_level === 'HIGH'
            ? '#ea580c'
            : gauge.risk_level === 'MODERATE'
              ? '#d97706'
              : '#10b981';

      const circle = L.circleMarker([gauge.latitude, gauge.longitude], {
        radius: 9,
        color: '#0f172a',
        weight: 2,
        fillColor: riskColor,
        fillOpacity: 0.9,
      });

      circle.bindTooltip(
        `<strong>${gauge.gauge_name}</strong><br/>River: ${gauge.river}<br/>Level: ${gauge.current_level_m.toFixed(2)} m (warning ${gauge.warning_level_m.toFixed(2)}, danger ${gauge.danger_level_m.toFixed(2)})<br/>Risk: <span style="color:${riskColor};font-weight:bold">${gauge.risk_level}</span> <em>(${gauge.data_status ?? 'DEMO'})</em>`,
        { sticky: true }
      );

      layer.addLayer(circle);
    });

    // Inundation zones (HIGH/EXTREME river gauges)
    floodForecast.zones.forEach((zone) => {
      const zoneLayer = L.geoJSON(zone.geometry as any, {
        style: {
          color: '#0369a1',
          weight: 2,
          opacity: 0.8,
          fillColor: '#0284c7',
          fillOpacity: 0.28,
          dashArray: '5, 5',
        },
      });
      zoneLayer.bindTooltip(
        `<strong>${zone.gauge_name} — ${zone.risk_level} flood</strong><br/>River: ${zone.river}<br/>Possible inundation zone`,
        { sticky: true }
      );
      layer.addLayer(zoneLayer);
    });
  }, [floodForecast, showFlood]);

  const getRainfallColor = (mm: number | null): string => {
    if (mm == null || mm <= 0) return '';
    if (mm < 2.5) return '#93c5fd';
    if (mm < 7.5) return '#2563eb';
    if (mm < 30) return '#f97316';
    return '#dc2626';
  };

  useEffect(() => {
    const layer = layersGroupRef.current.rainfallLayer;
    if (!layer || !mapInstanceRef.current) return;
    layer.clearLayers();

    if (!showRainfall || mapRainfallGrid.length === 0) return;

    mapRainfallGrid.forEach((cell) => {
      const color = getRainfallColor(cell.precipitation_mm_hour);
      if (!color) return;

      const circle = L.circleMarker([cell.latitude, cell.longitude], {
        radius: 6,
        color: '#0f172a',
        weight: 1,
        opacity: 0.9,
        fillColor: color,
        fillOpacity: 0.7,
      });

      circle.bindTooltip(
        `<strong>Precipitation</strong><br/>${
          cell.precipitation_mm_hour == null
            ? 'no data'
            : `${cell.precipitation_mm_hour.toFixed(2)} mm/hr`
        }<br/><em>NASA GPM IMERG</em>`,
        { sticky: true }
      );

      layer.addLayer(circle);
    });
  }, [mapRainfallGrid, showRainfall]);

  // Seed the in-map GPM grid from the initial payload, then keep fetching new
  // viewports from the NASA GPM endpoint as the user pans/zooms the map.
  const refreshRainfallForViewport = useCallback(() => {
    const map = mapInstanceRef.current;
    if (!map) return;
    const b = map.getBounds();
    const bounds = [
      b.getNorth().toFixed(2),
      b.getSouth().toFixed(2),
      b.getEast().toFixed(2),
      b.getWest().toFixed(2),
    ].join(',');
    apiService
      .getRainfallMap(bounds, 400)
      .then((res) => setMapRainfallGrid(res.points ?? []))
      .catch(() => {
        /* keep the last-known grid if the fetch fails */
      });
  }, []);

  useEffect(() => {
    if (mapRainfallGrid.length === 0 && rainfallGrid.length > 0) {
      setMapRainfallGrid(rainfallGrid);
    }
  }, [rainfallGrid, mapRainfallGrid.length]);

  useEffect(() => {
    if (showRainfall) refreshRainfallForViewport();
  }, [showRainfall, refreshRainfallForViewport]);

  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;
    const onMoveEnd = () => {
      if (rainfallRefreshTimerRef.current) window.clearTimeout(rainfallRefreshTimerRef.current);
      rainfallRefreshTimerRef.current = window.setTimeout(refreshRainfallForViewport, 600);
    };
    map.on('moveend', onMoveEnd);
    return () => {
      map.off('moveend', onMoveEnd);
      if (rainfallRefreshTimerRef.current) window.clearTimeout(rainfallRefreshTimerRef.current);
    };
  }, [refreshRainfallForViewport]);

  // Update AI Risk-Zones Layer (model-generated susceptibility circles)
  useEffect(() => {
    const layer = layersGroupRef.current.riskZonesLayer;
    if (!layer || !mapInstanceRef.current) return;
    layer.clearLayers();

    if (!showRiskZones || riskZones.length === 0) return;

    const riskColor: Record<string, string> = {
      LOW: '#10b981',
      MEDIUM: '#d97706',
      HIGH: '#ea580c',
      CRITICAL: '#dc2626',
      UNKNOWN: '#64748b',
    };

    riskZones.forEach((zone) => {
      const color = riskColor[zone.risk_band] ?? '#64748b';
      const circle = L.circleMarker([zone.latitude, zone.longitude], {
        radius: 8,
        color: '#0f172a',
        weight: 2,
        fillColor: color,
        fillOpacity: 0.85,
      });

      circle.bindTooltip(
        `<strong>${zone.label}</strong><br/>AI-Assessed ${zone.risk_band} · score ${zone.risk_score ?? '—'}/100<br/>${zone.hazards.length > 0 ? `Hazards: ${zone.hazards.join(', ')}` : 'No hazards enumerated'}<br/><em>${zone.assessment_mode.replace(/_/g, ' ')}</em>`,
        { sticky: true }
      );

      layer.addLayer(circle);
    });
  }, [riskZones, showRiskZones]);

  // Update Habitations Layer
  useEffect(() => {
    const layer = layersGroupRef.current.habitationsLayer;
    if (!layer || !mapInstanceRef.current) return;
    layer.clearLayers();

    if (!showHabitations) return;

    const filtered = habitations.filter((h) => {
      if (priorityFilter === 'all') return true;
      return h.priority_level.toLowerCase() === priorityFilter.toLowerCase();
    });

    filtered.forEach((hab) => {
      const getMarkerColor = (level: string) => {
        switch (level) {
          case 'Immediate Relocation':
            return { bg: '#dc2626', border: '#7f1d1d', text: '#ffffff' };
          case 'Short-Term Relocation':
            return { bg: '#f59e0b', border: '#b45309', text: '#ffffff' };
          case 'Medium-Term Relocation':
            return { bg: '#eab308', border: '#a16207', text: '#ffffff' };
          case 'Monitor Only':
          default:
            return { bg: '#10b981', border: '#047857', text: '#ffffff' };
        }
      };

      const c = getMarkerColor(hab.priority_level);
      const isSelected = hab.id === selectedHabitationId;

      const iconHtml = `
        <div class="cursor-pointer transition-transform hover:scale-110" style="
          display: flex;
          align-items: center;
          justify-content: center;
          width: 32px;
          height: 32px;
          background-color: ${c.bg};
          border: ${isSelected ? '3px solid #1e293b' : `2px solid ${c.border}`};
          border-radius: 50%;
          box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3);
          color: ${c.text};
          font-weight: 700;
          font-size: 11px;
          outline: ${isSelected ? '3px solid #ef4444' : 'none'};
        ">
          ${Math.round(hab.priority_score)}
        </div>
      `;

      const customIcon = L.divIcon({
        html: iconHtml,
        className: 'custom-village-icon',
        iconSize: [32, 32],
        iconAnchor: [16, 16],
      });

      const marker = L.marker([hab.latitude, hab.longitude], { icon: customIcon });

      marker.bindTooltip(
        `<strong>${hab.village_name}</strong><br/>Priority: <span style="font-weight:bold">${hab.priority_score} (${hab.priority_level})</span><br/>Pop: ${hab.population.toLocaleString()}`,
        { direction: 'top', offset: [0, -16] }
      );

      marker.on('click', () => {
        onSelectHabitation(hab);
      });

      layer.addLayer(marker);
    });
  }, [habitations, showHabitations, priorityFilter, selectedHabitationId, onSelectHabitation]);

  // Update Field Reports Layer (geo-tagged ground reports, severity-colored)
  useEffect(() => {
    const layer = layersGroupRef.current.reportsLayer;
    if (!layer || !mapInstanceRef.current) return;
    layer.clearLayers();

    fieldReports.forEach((report) => {
      const severityColor =
        report.severity === 'Critical'
          ? '#dc2626'
          : report.severity === 'High'
            ? '#d97706'
            : report.severity === 'Low'
              ? '#10b981'
              : '#0284c7';

      const iconHtml = `
        <div class="cursor-pointer transition-transform hover:scale-110" style="
          display: flex;
          align-items: center;
          justify-content: center;
          width: 22px;
          height: 22px;
          background-color: ${severityColor};
          border: 2px solid #0f172a;
          border-radius: 50% 50% 50% 0;
          box-shadow: 0 3px 6px rgba(0,0,0,0.35);
        ">
          <span style="color:#fff;font-weight:700;font-size:10px;">!</span>
        </div>
      `;

      const customIcon = L.divIcon({
        html: iconHtml,
        className: 'custom-report-icon',
        iconSize: [22, 22],
        iconAnchor: [11, 11],
      });

      const popupHtml = `
        <strong>${report.report_type}</strong><br/>
        <span style="color:${severityColor};font-weight:bold">${report.severity}</span> · ${report.habitation_name}<br/>
        Reported: ${new Date(report.reported_at).toLocaleString()} by ${report.officer_name}<br/>
        <span style="color:${report.verified ? '#047857' : '#b45309'}">${report.verified ? 'Verified' : 'Pending review'}</span><br/>
        <span style="color:#475569;font-size:11px;">${report.description}</span>
      `;

      const marker = L.marker([report.latitude, report.longitude], { icon: customIcon });

      marker.bindTooltip(
        `<strong>${report.report_type}</strong> — ${report.severity}<br/>${report.habitation_name}`,
        { direction: 'top', offset: [0, -11] }
      );
      marker.bindPopup(popupHtml, { maxWidth: 280 });

      layer.addLayer(marker);
    });
  }, [fieldReports]);

  // Update Relocation Sites Layer
  useEffect(() => {
    const layer = layersGroupRef.current.sitesLayer;
    if (!layer || !mapInstanceRef.current) return;
    layer.clearLayers();

    if (!showSites) return;

    relocationSites.forEach((site) => {
      const isSelected = site.id === selectedSiteId;

      const iconHtml = `
        <div class="cursor-pointer transition-transform hover:scale-110" style="
          display: flex;
          align-items: center;
          justify-content: center;
          width: 36px;
          height: 36px;
          background-color: #047857;
          border: ${isSelected ? '3px solid #facc15' : '2px solid #065f46'};
          border-radius: 8px;
          box-shadow: 0 4px 10px rgba(4, 120, 87, 0.4);
          color: #ffffff;
          font-size: 16px;
        ">
          🛡️
        </div>
      `;

      const customIcon = L.divIcon({
        html: iconHtml,
        className: 'custom-site-icon',
        iconSize: [36, 36],
        iconAnchor: [18, 18],
      });

      const marker = L.marker([site.latitude, site.longitude], { icon: customIcon });

      marker.bindTooltip(
        `<strong>${site.site_name} (SAFE ZONE)</strong><br/>Suitability: ${site.suitability_score}/100<br/>Avail Capacity: ${site.available_capacity_families} families`,
        { direction: 'top', offset: [0, -18] }
      );

      // Add a 2km safe buffer circle
      const buffer = L.circle([site.latitude, site.longitude], {
        radius: 2000,
        color: '#10b981',
        weight: 1,
        fillColor: '#34d399',
        fillOpacity: 0.15,
      });

      marker.on('click', () => {
        onSelectSite(site);
      });

      layer.addLayer(buffer);
      layer.addLayer(marker);
    });
  }, [relocationSites, showSites, selectedSiteId, onSelectSite]);

  // Update Infrastructure Layer
  useEffect(() => {
    const layer = layersGroupRef.current.infraLayer;
    if (!layer || !mapInstanceRef.current) return;
    layer.clearLayers();

    if (!showInfra) return;

    infrastructure.forEach((item) => {
      const isHospital = item.type === 'hospital';
      const isSchool = item.type === 'school';

      const iconChar = isHospital ? '🏥' : isSchool ? '🏫' : '🛣️';

      const customIcon = L.divIcon({
        html: `
          <div style="
            display: flex;
            align-items: center;
            justify-content: center;
            width: 26px;
            height: 26px;
            background: white;
            border: 1px solid #94a3b8;
            border-radius: 50%;
            font-size: 14px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.2);
          ">
            ${iconChar}
          </div>
        `,
        className: 'infra-icon',
        iconSize: [26, 26],
        iconAnchor: [13, 13],
      });

      const marker = L.marker([item.latitude, item.longitude], { icon: customIcon });
      marker.bindTooltip(
        `<strong>${item.name}</strong><br/><span style="text-transform:capitalize;color:#475569">${item.type.replace('_', ' ')}</span>: ${item.capacity_or_type}`,
        { direction: 'top', offset: [0, -13] }
      );

      layer.addLayer(marker);
    });
  }, [infrastructure, showInfra]);

  // Update Evacuation Route + Blocked/Closed Road Overlay
  useEffect(() => {
    const layer = layersGroupRef.current.routeLayer;
    if (!layer || !mapInstanceRef.current) return;
    layer.clearLayers();

    if (!showRoute) return;

    const routeColor =
      evacuationRoute?.route_status === 'SAFE' ? '#10b981' : evacuationRoute?.route_status === 'CAUTION' ? '#f59e0b' : '#64748b';

    // 1) Closed / restricted road conditions (drawn first, under the route)
    const highlightedStatuses = new Set<string>(['CLOSED', 'RESTRICTED', 'HIGH_RISK_EXIT']);
    (evacuationRoadConditions?.segments ?? []).forEach((seg) => {
      if (!seg.geometry || !highlightedStatuses.has(seg.status)) return;
      const latlngs = seg.geometry.coordinates.map(([lng, lat]) => [lat, lng] as [number, number]);
      const closed = seg.status === 'CLOSED';
      const polyline = L.polyline(latlngs, {
        color: closed ? '#dc2626' : '#f97316',
        weight: 6,
        opacity: 0.7,
        dashArray: closed ? '8, 6' : '2, 6',
      }).bindTooltip(`<strong>${seg.name}</strong><br/>Status: ${closed ? 'Closed' : 'Restricted'} (walk/exit only)`, { sticky: true });
      layer.addLayer(polyline);
    });

    // 2) Immediate blocked segments near the route corridor
    (evacuationRoute?.blocked_segments ?? []).forEach((block) => {
      if (!block.geometry) return;
      const latlngs = block.geometry.coordinates.map(([lng, lat]) => [lat, lng] as [number, number]);
      const polyline = L.polyline(latlngs, {
        color: '#dc2626',
        weight: 7,
        opacity: 0.8,
        dashArray: '8, 6',
      }).bindTooltip(`<strong>BLOCKED</strong> ${block.name}<br/>${block.reason}`, { sticky: true });
      layer.addLayer(polyline);
    });

    // 3) The recommended route itself
    if (evacuationRoute?.route_geometry?.coordinates?.length) {
      const latlngs = evacuationRoute.route_geometry.coordinates.map(([lng, lat]) => [lat, lng] as [number, number]);
      const routePolyline = L.polyline(latlngs, {
        color: routeColor,
        weight: 5,
        opacity: 0.95,
      }).bindTooltip(
        `<strong>${evacuationRoute.route_status ?? ''} route</strong><br/>${evacuationRoute.destination?.site_name ?? ''}<br/>${evacuationRoute.distance_km?.toFixed(1) ?? '—'} km · ~${evacuationRoute.travel_time_min ?? '—'} min`,
        { sticky: true }
      );
      layer.addLayer(routePolyline);

      // Origin marker
      const origin = evacuationRoute.origin;
      if (origin?.latitude && origin?.longitude) {
        const originIcon = L.divIcon({
          html: '<div style="display:flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:50%;background:#dc2626;border:2px solid #7f1d1d;color:#fff;font-weight:800;font-size:14px;box-shadow:0 3px 8px rgba(0,0,0,0.4);">▲</div>',
          className: 'evac-origin-icon',
          iconSize: [30, 30],
          iconAnchor: [15, 15],
        });
        const originMarker = L.marker([origin.latitude, origin.longitude], { icon: originIcon })
          .bindTooltip(`<strong>Origin</strong><br/>${origin.label ?? 'Selected origin'}`, { direction: 'top', offset: [0, -15] });
        layer.addLayer(originMarker);
      }

      // Destination marker
      const dest = evacuationRoute.destination;
      if (dest?.latitude && dest?.longitude) {
        const destIcon = L.divIcon({
          html: '<div style="display:flex;align-items:center;justify-content:center;width:32px;height:32px;border-radius:8px;background:#047857;border:2px solid #065f46;color:#fff;font-size:16px;box-shadow:0 3px 10px rgba(4,120,87,0.5);">🛡️</div>',
          className: 'evac-dest-icon',
          iconSize: [32, 32],
          iconAnchor: [16, 16],
        });
        const destMarker = L.marker([dest.latitude, dest.longitude], { icon: destIcon })
          .bindTooltip(`<strong>Safe destination</strong><br/>${dest.site_name}<br/>Capacity: ${dest.available_capacity_families} families`, { direction: 'top', offset: [0, -16] });
        layer.addLayer(destMarker);
      }

      // Hazard waypoints
      (evacuationRoute.hazards_encountered ?? []).forEach((hazard) => {
        if (!hazard.latitude && !hazard.longitude) return;
        const hazardIcon = L.divIcon({
          html: '<div style="display:flex;align-items:center;justify-content:center;width:20px;height:20px;border-radius:50%;background:#facc15;border:2px solid #a16207;color:#422006;font-size:12px;font-weight:900;">!</div>',
          className: 'evac-hazard-icon',
          iconSize: [20, 20],
          iconAnchor: [10, 10],
        });
        const hazardMarker = L.marker([hazard.latitude, hazard.longitude], { icon: hazardIcon })
          .bindTooltip(`<strong>${hazard.zone_name ?? hazard.hazard_type ?? 'Hazard'}</strong><br/>${hazard.road ?? ''}`, { direction: 'top', offset: [0, -10] });
        layer.addLayer(hazardMarker);
      });
    }
  }, [evacuationRoute, evacuationRoadConditions, showRoute]);

  // Bhuvan / ISRO intra-state shortest path assist (from Risk Intelligence).
  useEffect(() => {
    const layer = layersGroupRef.current.bhuvanLayer;
    if (!layer || !mapInstanceRef.current) return;
    layer.clearLayers();

    if (!showBhuvanRoute || !bhuvanRoute) return;
    if (bhuvanRoute.data_status !== 'AVAILABLE' && bhuvanRoute.data_status !== 'CACHED') return;

    const geom = bhuvanRoute.geometry;
    const drawRing = (coords: Array<[number, number] | number[]>) => {
      if (!coords || coords.length === 0) return;
      const latlngs = coords.map((c) => [c[1], c[0]] as [number, number]);
      const polyline = L.polyline(latlngs, {
        color: '#7c3aed',
        weight: 4,
        opacity: 0.85,
        dashArray: '6, 4',
      }).bindTooltip(
        `<strong>Bhuvan intra-state route</strong><br/>${bhuvanRoute.distance_km?.toFixed(1) ?? '—'} km · ISRO road network`,
        { sticky: true }
      );
      layer.addLayer(polyline);
    };

    if (geom?.type === 'MultiLineString') {
      (geom.coordinates as unknown[][][]).forEach((ring) => drawRing(ring as Array<[number, number] | number[]>));
    } else if (geom?.type === 'LineString') {
      drawRing(geom.coordinates as Array<[number, number] | number[]>);
    }
  }, [bhuvanRoute, showBhuvanRoute]);

  // Engine-evaluated "Safer Route" (from Route Intelligence across safe-location analyses).
  useEffect(() => {
    const layer = layersGroupRef.current.safeRouteLayer;
    if (!layer || !mapInstanceRef.current) return;
    layer.clearLayers();

    if (!safeRoute?.route_geometry || !safeRoute.route_geometry.coordinates) return;

    const geom = safeRoute.route_geometry;
    const coords = (geom.coordinates as unknown) as Array<[number, number] | number[]>;
    const drawRing = (ring: Array<[number, number] | number[]>) => {
      if (!ring || ring.length === 0) return;
      const latlngs = ring.map((c) => [c[1], c[0]] as [number, number]);
      const polyline = L.polyline(latlngs, {
        color: '#10b981',
        weight: 5,
        opacity: 0.9,
        dashArray: '2, 6',
      }).bindTooltip(
        `<strong>Recommended Safer Route</strong><br/>Safety ${safeRoute.safety_score ?? '—'}% · Risk ${safeRoute.risk_score ?? '—'}<br/>${safeRoute.distance_km?.toFixed(1) ?? '—'} km · ${safeRoute.travel_time_min?.toFixed(0) ?? '—'} min`,
        { sticky: true }
      );
      layer.addLayer(polyline);
    };

    if (geom.type === 'MultiLineString') {
      (geom.coordinates as Array<Array<[number, number] | number[]>>).forEach(drawRing);
    } else if (geom.type === 'LineString') {
      drawRing(geom.coordinates as Array<[number, number] | number[]>);
    }
  }, [safeRoute]);

  // Bhuvan / ISRO thematic WMS overlay (LULC 50K national mosaic, ISRO).
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;

    if (showBhuvanOverlay && !wmsLayerRef.current) {
      const wms = L.tileLayer.wms('https://bhuvan-vec2.nrsc.gov.in/bhuvan/wms', {
        layers: 'lulc:BR_LULC50K_1112',
        format: 'image/png',
        transparent: true,
        opacity: 0.6,
        crs: L.CRS.EPSG4326,
      });
      wms.addTo(map);
      wmsLayerRef.current = wms;
    } else if (!showBhuvanOverlay && wmsLayerRef.current) {
      map.removeLayer(wmsLayerRef.current);
      wmsLayerRef.current = null;
    }
  }, [showBhuvanOverlay, mapInstanceRef.current]);

  // Nationwide disaster events markers (shown in national overview / non-pilot view).
  useEffect(() => {
    const layer = layersGroupRef.current.disasterLayer;
    if (!layer || !mapInstanceRef.current) return;
    layer.clearLayers();
    disasterEvents.forEach((ev) => {
      if (typeof ev.latitude !== 'number' || typeof ev.longitude !== 'number') return;
      const color =
        ev.severity_level === 'Critical' ? '#b91c1c'
        : ev.severity_level === 'High' ? '#c2410c'
        : ev.severity_level === 'Medium' ? '#d97706'
        : '#2563eb';
      const marker = L.marker([ev.latitude, ev.longitude], {
        icon: L.divIcon({
          className: 'namsafe-disaster-marker',
          html: `<div style="
            width:22px;height:22px;border-radius:50%;
            background:${color};border:2px solid #fff;
            box-shadow:0 1px 3px rgba(0,0,0,0.4);display:flex;align-items:center;justify-content:center;
            font-size:11px;font-weight:700;color:#fff;pointer-events:auto;
          " title="${ev.hazard_type}">${ev.hazard_type[0] ?? '!'}</div>`,
          iconSize: [22, 22],
          iconAnchor: [11, 11],
        }),
      });
      const dateStr = ev.event_date
        ? new Date(ev.event_date).toLocaleDateString()
        : 'Unknown date';
      const popup = [
        `<div style="min-width:180px">`,
        `<div style="font-weight:700;font-size:12px">${ev.name}</div>`,
        `<div style="font-size:11px;color:#475569;margin:4px 0">${ev.hazard_type} — ${dateStr}</div>`,
        ev.severity_level ? `<div style="font-size:11px"><span style="background:${color};color:#fff;padding:1px 6px;border-radius:4px;font-weight:600">${ev.severity_level}</span></div>` : '',
        ev.affected_population ? `<div style="font-size:11px;color:#64748b;margin-top:4px">Affected: ${ev.affected_population.toLocaleString()}</div>` : '',
        ev.state ? `<div style="font-size:11px;color:#64748b">${[ev.state, ev.district].filter(Boolean).join(', ')}</div>` : '',
        `</div>`,
      ].join('');
      marker.bindPopup(popup, { className: 'leaflet-custom-tooltip' });
      marker.bindTooltip(ev.name, { permanent: false, direction: 'top', offset: [0, -8] });
      layer.addLayer(marker);
    });
  }, [disasterEvents]);

  // Fly to the region selected in the Region Quick-Select
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map || !focus) return;
    if (focus.bounds) {
      map.flyToBounds(
        L.latLngBounds([
          [focus.bounds[0], focus.bounds[1]],
          [focus.bounds[2], focus.bounds[3]],
        ]),
        { duration: 1.2 }
      );
    } else {
      map.flyTo([focus.lat, focus.lng], focus.zoom, { duration: 1.2 });
    }
  }, [focus?.key]);

  const handleResetCenter = () => {
    if (mapInstanceRef.current) {
      mapInstanceRef.current.flyTo([22.5, 78.9], 5, { duration: 1.2 });
    }
  };

  return (
    <div
      ref={gisMapComponentRef}
      id="gis-map-component"
      className={`relative w-full h-full min-h-[420px] lg:min-h-[550px] rounded-xl overflow-hidden border border-sm-border shadow-inner ${
        fullscreen ? 'gis-map-fullscreen' : ''
      }`}
    >
      {/* The Leaflet Canvas */}
      <div ref={mapContainerRef} className="w-full h-full z-0" />

      {/* Full Screen / Exit Full Screen controls (top-right, left of Leaflet zoom) */}
      <div className="absolute top-4 right-12 z-[1000] flex flex-col gap-2 sm:top-[14px]">
        {!fullscreen ? (
          <button
            id="map-fullscreen-btn"
            onClick={toggleFullscreen}
            title="Enter full screen"
            aria-label="Enter full screen"
            className="w-10 h-10 flex items-center justify-center rounded-lg bg-sm-panel-2/95 hover:bg-sm-panel-2 text-sm-text border border-sm-border shadow-md transition cursor-pointer"
          >
            <Maximize2 className="w-4 h-4" />
          </button>
        ) : (
          <button
            id="map-exit-fullscreen-btn"
            onClick={toggleFullscreen}
            title="Exit full screen"
            aria-label="Exit full screen"
            className="w-10 h-10 flex items-center justify-center rounded-lg bg-slate-900/90 hover:bg-slate-800 text-white border border-slate-600 shadow-md transition cursor-pointer"
          >
            <Minimize2 className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Basemap tile failure banner */}
      {basemapError && (
        <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 bg-red-900/90 text-red-100 text-[11px] font-bold px-3 py-1.5 rounded-lg border border-red-700 shadow-lg whitespace-nowrap">
          {basemapError}
        </div>
      )}

      {/* Professional Layer Control Panel */}
      <MapLayerPanel
        basemap={basemap}
        onBasemapChange={setBasemap}
        showRedZones={showRedZones}
        onRedZonesChange={setShowRedZones}
        hazardTypes={availableHazardTypes}
        visibleHazardTypes={visibleHazardTypes}
        onHazardTypeChange={(ht, visible) =>
          setVisibleHazardTypes((prev) =>
            visible ? [...prev, ht] : prev.filter((t) => t !== ht)
          )
        }
        showHabitations={showHabitations}
        onHabitationsChange={setShowHabitations}
        showSites={showSites}
        onSitesChange={setShowSites}
        showInfra={showInfra}
        onInfraChange={setShowInfra}
        showRoute={showRoute}
        onRouteChange={setShowRoute}
        showFlood={showFlood}
        onFloodChange={setShowFlood}
        floodDataStatus={floodForecast?.data_status ?? 'NOT CONFIGURED'}
        hasFloodData={hasFloodData}
        showRiskZones={showRiskZones}
        onRiskZonesChange={setShowRiskZones}
        hasRiskZones={hasRiskZones}
        showRainfall={showRainfall}
        onRainfallChange={setShowRainfall}
        hasRainfallData={hasRainfallData}
        rainfallDataStatus={rainfallStatus}
        showBhuvanRoute={showBhuvanRoute}
        onBhuvanRouteChange={setShowBhuvanRoute}
        hasBhuvanRoute={bhuvanRoute != null && (bhuvanRoute.data_status === 'AVAILABLE' || bhuvanRoute.data_status === 'CACHED')}
        showBhuvanOverlay={showBhuvanOverlay}
        onBhuvanOverlayChange={setShowBhuvanOverlay}
        priorityFilter={priorityFilter}
        onPriorityFilterChange={setPriorityFilter}
        onResetCenter={handleResetCenter}
        dataStatus={dataStatus}
      />

      {/* Data Source Status (bottom-left) */}
      {!fullscreen && <DataSourceStatus layers={dataStatus} />}

      {/* Historical Rainfall (Kerala previous-year) — shown once a Kerala district is selected */}
      {!fullscreen && historicalDistrictId != null && (
        <HistoricalDistrictPanel
          districtId={historicalDistrictId}
          onDistrictChange={onHistoricalDistrictChange}
          baseline={historicalBaseline}
          summaries={historicalSummaries}
          availability={historicalAvailability}
        />
      )}

      {/* Floating Legend */}
      <div
        id="gis-map-legend"
        className="hidden sm:block absolute bottom-4 right-4 z-10 bg-slate-900/90 backdrop-blur-md text-white p-3 rounded-xl border border-slate-700 shadow-xl text-xs space-y-1.5"
      >
        <div className="font-bold text-[11px] text-slate-300 uppercase tracking-wider mb-1">
          Priority Legend
        </div>
        <div className="flex items-center gap-2">
          <span className="w-3 h-3 rounded-full bg-red-600 inline-block shrink-0" />
          <span>Immediate Relocation (&ge; 75)</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-3 h-3 rounded-full bg-amber-500 inline-block shrink-0" />
          <span>Short-Term Relocation (50 - 74)</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-3 h-3 rounded-full bg-yellow-500 inline-block shrink-0" />
          <span>Medium-Term Relocation (30 - 49)</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-3 h-3 rounded bg-emerald-600 inline-block shrink-0 text-[9px] text-center">🛡️</span>
          <span>Safe Site (+2km Buffer)</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-block h-0.5 w-4 rounded bg-emerald-400 shrink-0" />
          <span>Evacuation Route (SAFE)</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-block h-0.5 w-4 rounded bg-amber-500 shrink-0" />
          <span>Evacuation Route (CAUTION)</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-block w-4 shrink-0 text-center text-[10px] leading-none" style={{ borderTop: '3px dashed #dc2626' }} />
          <span>Closed Corridor</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-block w-4 shrink-0 text-center text-[10px] leading-none" style={{ borderTop: '3px dotted #f97316' }} />
          <span>Restricted Segment</span>
        </div>
        {hasFloodData && (
          <>
            <div className="flex items-center gap-2">
              <span className="w-3 h-3 rounded-full border-2 border-slate-900 inline-block shrink-0" style={{ background: '#0284c7' }} />
              <span>Flood Gauge / Zone</span>
            </div>
          </>
        )}
        {hasRiskZones && (
          <>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="w-3 h-3 rounded-full border-2 border-slate-900 inline-block shrink-0" style={{ background: '#ea580c' }} />
              <span>AI-Assessed Risk Zone</span>
            </div>
          </>
        )}
        {hasRainfallData && (
          <>
            <div className="font-bold text-[11px] text-slate-300 uppercase tracking-wider mt-1 pt-1 border-t border-slate-700">
              Live Rainfall (NASA GPM IMERG)
            </div>
            <div className="flex items-center gap-2">
              <span className="w-3 h-3 rounded-full inline-block shrink-0" style={{ background: '#93c5fd' }} />
              <span>Light 0.1&ndash;2.5 mm/hr</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-3 h-3 rounded-full inline-block shrink-0" style={{ background: '#2563eb' }} />
              <span>Moderate 2.5&ndash;7.5 mm/hr</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-3 h-3 rounded-full inline-block shrink-0" style={{ background: '#f97316' }} />
              <span>Heavy 7.5&ndash;30 mm/hr</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-3 h-3 rounded-full inline-block shrink-0" style={{ background: '#dc2626' }} />
              <span>Extreme &gt;30 mm/hr</span>
            </div>
          </>
        )}
      </div>
    </div>
  );
};
