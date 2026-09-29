import React, { useEffect, useState } from 'react';
import {
  CloudRain, Mountain, Waves, MapPin, ShieldCheck, AlertTriangle,
  CalendarDays, Navigation, HeartPulse, Activity, RefreshCw, Crosshair,
  ShieldAlert, Satellite,
} from 'lucide-react';
import type { RegionViewportFocus } from '../lib/regionViewport';
import {
  Habitation, RiskZone, WeatherResponse, TerrainResponse, FloodRiskResponse,
  RainfallResponse, RiskAssessmentResponse, SafeLocationsResponse,
  DisasterEventsResponse, NearbyPlacesResponse, DataLayerStatus,
  BhuvanVillageGeocodeResponse, BhuvanReverseGeocodeResponse, BhuvanHospitalsResponse,
  BhuvanLulcResponse, BhuvanShortestPathResponse,
} from '../types';
import { apiService } from '../services/api';
import { DataStatusBadge } from '../components/DataStatusBadge';

interface RiskIntelligencePageProps {
  habitations: Habitation[];
  riskZones: RiskZone[];
  anchor?: { lat: number; lng: number; label?: string };
  onLocateOnMap?: (focus: RegionViewportFocus) => void;
  onRiskZonesLoaded?: (zones: RiskZone[]) => void;
  onBhuvanRouteLoaded?: (route: BhuvanShortestPathResponse | null) => void;
  // Citizen portal: the live weather / flood / rainfall science endpoints are
  // not included there (backend 403). The page then shows honest labelled
  // sections instead of attempting denied network calls.
  isCitizen?: boolean;
}

// Only used when no region (or map focus) is resolved yet — otherwise the
// live anchor comes from the region selection props.
const FALLBACK_LAT = 22.5;
const FALLBACK_LNG = 78.9;

const CITIZEN_WEATHER_REASON =
  'The Citizen portal provides historical weather on the Weather Map; live point-weather, rainfall, and flood science are not exposed to citizen accounts.';

const bandClass: Record<string, string> = {
  LOW: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
  MEDIUM: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
  HIGH: 'bg-orange-500/10 text-orange-300 border-orange-500/30',
  CRITICAL: 'bg-red-500/10 text-red-300 border-red-500/30',
  UNKNOWN: 'bg-sm-panel-2 text-sm-muted border-sm-border',
};

function statusDot(status?: string): React.ReactNode {
  const key = String(status ?? 'NOT_CONFIGURED');
  const label = key.replace(/_/g, ' ').toLowerCase();
  const dot =
    label === 'live' ? 'bg-emerald-400' :
    label === 'forecast' ? 'bg-sky-400' :
    label === 'historical' ? 'bg-violet-400' :
    label === 'unavailable' ? 'bg-red-400' :
    label === 'no_route' || label === 'no route' ? 'bg-red-400' :
    'bg-slate-400';
  return (
    <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-sm-muted">
      <span className={`w-1.5 h-1.5 rounded-full ${dot} inline-block`} />
      <span className="uppercase tracking-wider">{label}</span>
    </span>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-sm-border bg-sm-panel shadow-sm overflow-hidden">
      <div className="border-b border-sm-border px-5 py-3 font-bold text-sm-text">{title}</div>
      <div className="p-5">{children}</div>
    </section>
  );
}

export const RiskIntelligencePage: React.FC<RiskIntelligencePageProps> = ({
  habitations,
  riskZones,
  anchor,
  onLocateOnMap,
  onRiskZonesLoaded,
  onBhuvanRouteLoaded,
  isCitizen = false,
}) => {
  const [lat, setLat] = useState<number>(anchor?.lat ?? FALLBACK_LAT);
  const [lng, setLng] = useState<number>(anchor?.lng ?? FALLBACK_LNG);

  const [weather, setWeather] = useState<WeatherResponse | null>(null);
  const [terrain, setTerrain] = useState<TerrainResponse | null>(null);
  const [flood, setFlood] = useState<FloodRiskResponse | null>(null);
  const [rainfall, setRainfall] = useState<RainfallResponse | null>(null);
  const [reports, setReports] = useState<NearbyPlacesResponse | null>(null);
  const [assessment, setAssessment] = useState<RiskAssessmentResponse | null>(null);
  const [disasters, setDisasters] = useState<DisasterEventsResponse | null>(null);
  const [safeLocs, setSafeLocs] = useState<SafeLocationsResponse | null>(null);
  const [loading, setLoading] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [zones, setZones] = useState<RiskZone[]>(riskZones);
  const [zonesLoading, setZonesLoading] = useState(false);
  const [bhuvan, setBhuvan] = useState<{
    village: BhuvanVillageGeocodeResponse | null;
    reverse: BhuvanReverseGeocodeResponse | null;
    hospitals: BhuvanHospitalsResponse | null;
    lulc: BhuvanLulcResponse | null;
    route: BhuvanShortestPathResponse | null;
  } | null>(null);

  useEffect(() => setZones(riskZones), [riskZones]);

  const beginLoad = (key: string) => setLoading((prev) => ({ ...prev, [key]: true }));
  const endLoad = (key: string) => setLoading((prev) => ({ ...prev, [key]: false }));
  const noteError = (key: string, message: string) => setErrors((prev) => ({ ...prev, [key]: message }));

  const selectedHab =
    habitations.find((h) => Math.abs(h.latitude - lat) < 0.01 && Math.abs(h.longitude - lng) < 0.01) ?? null;

  const useHab = (hab: Habitation) => {
    setLat(hab.latitude);
    setLng(hab.longitude);
  };

  const fetchLive = async (key: string, loader: () => Promise<unknown>, setter: (v: never) => void) => {
    beginLoad(key);
    noteError(key, '');
    try {
      const data = await loader();
      setter(data as never);
    } catch {
      noteError(key, 'This provider could not be reached. Showing the last known status, if any.');
    } finally {
      endLoad(key);
    }
  };

  const loadPoint = async (force = false) => {
    setLoading((p) => ({ ...p, weather: true, terrain: true, flood: true, rainfall: true }));
    const base = { latitude: lat, longitude: lng };
    try {
      if (isCitizen) {
        // Citizen portal: live point-weather/flood/rainfall science is not
        // exposed to citizen accounts (historical weather lives on the
        // Weather Map). Avoid the round-trips entirely and label the sections
        // honestly; terrain stays available to citizens.
        setWeather({
          latitude: lat, longitude: lng,
          data_status: 'UNAVAILABLE' as DataLayerStatus,
          data_source: 'Open-Meteo/ECMWF',
          provider: null, provider_role: null, model: null,
          observed_at: null, current: null, forecast: [],
          timezone: null,
          reason: CITIZEN_WEATHER_REASON,
        });
        setFlood({
          latitude: lat, longitude: lng,
          data_status: 'NOT CONFIGURED' as DataLayerStatus,
          data_source: 'Copernicus GloFAS',
          river_discharge_m3s: null, threshold_m3s: null, discharge_band: null,
          lead_time_hours: null, issue_time: null, valid_time: null, forecast_hours: null,
          dataset: null, computed_at: null, assumption: null,
          reason: CITIZEN_WEATHER_REASON,
        });
        setRainfall({
          latitude: lat, longitude: lng,
          data_status: 'NOT CONFIGURED' as DataLayerStatus,
          data_source: 'NASA GPM IMERG',
          precipitation_mm_hour: null, dataset: null, tile_time: null,
          computed_at: null, assumption: null,
          reason: CITIZEN_WEATHER_REASON,
        });
        setTerrain(await apiService.getTerrain(lat, lng));
      } else {
        const [w, t, f, r] = await Promise.all([
          apiService.getWeather(lat, lng),
          apiService.getTerrain(lat, lng),
          apiService.getFloodRisk(lat, lng),
          apiService.getRainfall(lat, lng),
        ]);
        setWeather(w); setTerrain(t); setFlood(f); setRainfall(r);
      }
    } catch {
      noteError('point', 'Live providers could not be reached; labelled statuses are shown instead.');
    } finally {
      setLoading((p) => ({ ...p, weather: false, terrain: false, flood: false, rainfall: false }));
      void base; void force;
    }
  };

  const loadAssessment = async (recompute = false) => {
    beginLoad('assessment');
    noteError('assessment', '');
    try {
      const result = recompute
        ? await apiService.recalculateRisk({ latitude: lat, longitude: lng })
        : await apiService.getRiskAssessment({ latitude: lat, longitude: lng, placeLabel: selectedHab?.village_name });
      setAssessment(result);
    } catch {
      noteError('assessment', 'Assessment could not be computed for these coordinates.');
    } finally {
      endLoad('assessment');
    }
  };

  const loadDisasters = async () => {
    beginLoad('disasters');
    noteError('disasters', '');
    try {
      setDisasters(await apiService.getDisasterEventsNear(lat, lng, 100));
    } catch {
      noteError('disasters', 'Historical disaster records could not be loaded.');
    } finally {
      endLoad('disasters');
    }
  };

  const loadSafeLocations = async () => {
    beginLoad('safe');
    noteError('safe', '');
    try {
      const data = await apiService.getSafeLocations({
        latitude: lat, longitude: lng,
        affectedPopulation: selectedHab?.population ?? 0,
      });
      setSafeLocs(data);
    } catch {
      noteError('safe', 'Safe-location engine did not respond.');
    } finally {
      endLoad('safe');
    }
  };

  const loadNearby = async () => {
    beginLoad('nearby');
    noteError('nearby', '');
    try {
      setReports(await apiService.getNearby('hospitals', lat, lng, 25));
    } catch {
      noteError('nearby', 'Nearby facilities could not be loaded.');
    } finally {
      endLoad('nearby');
    }
  };

  const refreshZones = async () => {
    setZonesLoading(true);
    try {
      const result = await apiService.getRiskZones({ granularity: 'habitations', maxPoints: 80 });
      setZones(result.zones);
      onRiskZonesLoaded?.(result.zones);
    } catch {
      noteError('zones', 'Risk zones could not be recomputed.');
    } finally {
      setZonesLoading(false);
    }
  };

  const loadBhuvan = async () => {
    beginLoad('bhuvan');
    noteError('bhuvan', '');
    const villageName = selectedHab?.village_name ?? null;
    const destination = safeLocs?.locations?.[0] ?? null;
    try {
      const [village, reverse, hospitals, lulc] = await Promise.all([
        villageName
          ? apiService.bhuvanVillageGeocode(villageName)
          : Promise.resolve<BhuvanVillageGeocodeResponse>({
              source: 'Bhuvan / ISRO', service: 'village_geocode', data_status: 'UNAVAILABLE',
              data_source: 'Bhuvan / ISRO village census geocode', has_coordinates: false,
              query: {}, coordinate_note: 'No surveyed habitation selected at this point.',
            }),
        apiService.bhuvanReverseGeocode(lat, lng),
        apiService.bhuvanHospitals(lat, lng, 3000),
        apiService.bhuvanLulc(lat, lng, 'all'),
      ]);
      let route: BhuvanShortestPathResponse;
      if (destination && destination.latitude != null && destination.longitude != null) {
        route = await apiService.bhuvanShortestPath(lat, lng, destination.latitude, destination.longitude);
      } else {
        route = {
          source: 'Bhuvan / ISRO', service: 'shortest_path', data_status: 'UNAVAILABLE',
          data_source: 'Bhuvan / ISRO intra-state shortest path',
          origin: [lat, lng], destination: [],
          reason: 'No recommended destination yet — find safe locations first to plan an evacuation route.',
        };
      }
      setBhuvan({ village, reverse, hospitals, lulc, route });
      onBhuvanRouteLoaded?.(route.data_status === 'AVAILABLE' || route.data_status === 'CACHED' ? route : null);
    } catch {
      noteError('bhuvan', 'Bhuvan providers could not be reached; statuses are shown instead.');
    } finally {
      endLoad('bhuvan');
    }
  };

  useEffect(() => {
    loadPoint();
    loadAssessment();
    loadDisasters();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const metric = (label: string, value: React.ReactNode, sub?: React.ReactNode) => (
    <div className="p-3 rounded-lg bg-sm-panel-2 border border-sm-border">
      <div className="text-[10px] font-bold text-sm-muted uppercase tracking-wider">{label}</div>
      <div className="text-sm font-bold text-sm-text mt-0.5">{value}</div>
      {sub && <div className="text-[11px] text-sm-muted mt-0.5">{sub}</div>}
    </div>
  );

  const locate = (focusLat: number, focusLng: number, label: string) => {
    onLocateOnMap?.({ lat: focusLat, lng: focusLng, zoom: 13, label });
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Banner */}
      <div className="rounded-xl border border-sm-green/30 bg-sm-green/10 p-5">
        <div className="flex items-center gap-2 text-sm-green">
          <Activity className="w-5 h-5" />
          <h2 className="font-bold text-lg">SafeMove AI — Real-time Risk Intelligence</h2>
        </div>
        <p className="mt-1 text-sm text-sm-green/90">
          Live weather, terrain, river flow, rainfall and the AI risk engine for any point in India.
          Scores are susceptibility estimates — they are never official red-zone notifications.
        </p>
      </div>

      {/* Coordinates + controls */}
      <section className="rounded-xl border border-sm-border bg-sm-panel shadow-sm p-4">
        <div className="flex flex-wrap items-end gap-3">
          <label className="block">
            <span className="text-[10px] font-semibold text-sm-muted uppercase tracking-wide block mb-1">Latitude</span>
            <input
              id="ri-lat-input"
              type="number" step="any"
              value={lat}
              onChange={(e) => setLat(Number(e.target.value))}
              className="w-32 px-2.5 py-1.5 border border-sm-border bg-sm-panel-2 text-sm-text rounded-lg text-sm font-medium focus:outline-none focus:ring-2 focus:ring-sm-green/40 focus:border-sm-green"
            />
          </label>
          <label className="block">
            <span className="text-[10px] font-semibold text-sm-muted uppercase tracking-wide block mb-1">Longitude</span>
            <input
              id="ri-lng-input"
              type="number" step="any"
              value={lng}
              onChange={(e) => setLng(Number(e.target.value))}
              className="w-32 px-2.5 py-1.5 border border-sm-border bg-sm-panel-2 text-sm-text rounded-lg text-sm font-medium focus:outline-none focus:ring-2 focus:ring-sm-green/40 focus:border-sm-green"
            />
          </label>

          <div className="flex items-center gap-2">
            <button
              onClick={() => { loadPoint(); loadAssessment(); loadDisasters(); }}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-sm-green hover:bg-sm-green-hover text-slate-900 font-semibold text-xs transition cursor-pointer"
            >
              <Crosshair className="w-3.5 h-3.5" /> Assess this point
            </button>
            <button
              onClick={() => onLocateOnMap?.({ lat, lng, zoom: 12, label: 'Risk intelligence point' })}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-sm-panel-2 hover:bg-sm-panel-2/80 text-sm-text border border-sm-border font-semibold text-xs transition cursor-pointer"
            >
              <MapPin className="w-3.5 h-3.5" /> Locate on map
            </button>
          </div>

          <div className="flex-1 min-w-[200px]">
            <span className="text-[10px] font-semibold text-sm-muted uppercase tracking-wide block mb-1">Or pick a surveyed habitation</span>
            <select
              id="ri-habitation-select"
              value={selectedHab?.id ?? ''}
              onChange={(e) => {
                const hab = habitations.find((h) => h.id === e.target.value);
                if (hab) useHab(hab);
              }}
              className="w-full px-2.5 py-1.5 border border-sm-border bg-sm-panel-2 text-sm-text rounded-lg text-sm font-medium focus:outline-none focus:ring-2 focus:ring-sm-green/40 focus:border-sm-green"
            >
              <option value="">— {habitations.length ? 'select a habitation' : 'no surveyed habitations in this region'} —</option>
              {habitations.map((h) => (
                <option key={h.id} value={h.id}>{h.village_name}</option>
              ))}
            </select>
            {anchor?.label && (
              <p className="mt-1 text-[11px] text-sm-muted">Region anchor: {anchor.label}</p>
            )}
          </div>
        </div>
      </section>

      {/* Live point data */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Section title="Weather">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-1.5 text-sm-muted text-[11px]">
              <CloudRain className="w-3.5 h-3.5" /> Open-Meteo
            </div>
            {weather && <DataStatusBadge status={weather.data_status} timestamp={weather.observed_at} />}
          </div>
          {errors.point && <p className="text-xs text-amber-400 mb-2">{errors.point}</p>}
          {weather?.current ? (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {metric('Temp', `${weather.current.temperature_c?.toFixed(1) ?? '—'} °C`)}
              {metric('Rain', `${weather.current.precipitation_mm ?? '—'} mm/hr`, weather.current.rain_intensity ?? undefined)}
              {metric('Condition', weather.current.weather_description ?? '—')}
            </div>
          ) : weather ? (
            <p className="text-xs text-sm-muted">
              {loading.weather ? 'Fetching…' : (String(weather.data_status).replace(/_/g, ' ') + (weather.reason ? ` — ${weather.reason}` : ''))}
            </p>
          ) : (<p className="text-xs text-sm-muted">Press "Assess this point" to load weather.</p>)}
          {weather?.forecast && weather.forecast.length > 0 && (
            <div className="mt-3 border-t border-sm-border pt-2">
              <div className="text-[10px] font-bold text-sm-muted uppercase tracking-wider mb-1">7-day outlook</div>
              <div className="flex gap-1.5 overflow-x-auto">
                {weather.forecast.slice(0, 7).map((day) => (
                  <div key={day.date} className="p-1.5 rounded-md bg-sm-panel-2 border border-sm-border min-w-[64px] text-center">
                    <div className="text-[9px] text-sm-muted font-semibold">{day.date.slice(5)}</div>
                    <div className="text-xs font-bold text-sm-text">{day.max_temp_c?.toFixed(0) ?? '—'}°/{(day.min_temp_c ?? '—')}{day.min_temp_c != null ? '°' : ''}</div>
                    <div className="text-[10px] text-sky-400 font-semibold">{day.precipitation_mm ?? '—'} mm</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Section>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
          <Section title="Terrain (NASA SRTM)">
            <div className="flex items-center justify-between mb-2">
              <Mountain className="w-4 h-4 text-amber-400" />
              {terrain && <DataStatusBadge status={terrain.data_status} timestamp={terrain.computed_at} />}
            </div>
            {terrain?.elevation_m != null ? (
              <div className="space-y-2">
                {metric('Elevation', `${terrain.elevation_m.toFixed(0)} m`)}
                {metric('Slope', `${terrain.slope_percent?.toFixed(1) ?? '—'} %`, terrain.slope_category ?? undefined)}
                {metric(
                  'Source',
                  `${terrain.data_source ?? terrain.dataset ?? 'NASA Earthdata SRTM'}${
                    terrain.provider_role === 'fallback' ? ' (fallback)' : ''
                  }`
                )}
              </div>
            ) : (
              <p className="text-xs text-sm-muted">{terrain ? String(terrain.data_status).replace(/_/g, ' ') : 'Press to load terrain.'}</p>
            )}
          </Section>

          <Section title="River flood (GloFAS)">
            <div className="flex items-center justify-between mb-2">
              <Waves className="w-4 h-4 text-sky-400" />
              {flood && <DataStatusBadge status={flood.data_status} timestamp={flood.computed_at} />}
            </div>
            {flood?.discharge_band ? (
              <div className="space-y-2">
                {metric('Discharge', `${flood.river_discharge_m3s?.toFixed(0) ?? '—'} m³/s`)}
                {metric('Band', flood.discharge_band)}
              </div>
            ) : (
              <p className="text-xs text-sm-muted">{flood ? String(flood.data_status).replace(/_/g, ' ') : 'Press to load flood data.'}</p>
            )}
          </Section>

          <Section title="Rainfall (NASA GPM)">
            <div className="flex items-center justify-between mb-2">
              <CloudRain className="w-4 h-4 text-indigo-400" />
              {rainfall && <DataStatusBadge status={rainfall.data_status} timestamp={rainfall.tile_time ?? rainfall.computed_at} />}
            </div>
            {rainfall?.precipitation_mm_hour != null ? (
              <div className="space-y-2">
                {metric('Intensity', `${rainfall.precipitation_mm_hour} mm/hr`)}
                {metric('Dataset', '', <span className="text-[10px] break-words">{rainfall.dataset ?? ''}</span>)}
              </div>
            ) : (
              <p className="text-xs text-sm-muted">{rainfall ? String(rainfall.data_status).replace(/_/g, ' ') : 'Press to load rainfall.'}</p>
            )}
          </Section>
        </div>
      </div>

      {/* Risk assessment */}
      <Section title="AI Risk Assessment">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div className="text-xs text-sm-muted">
            Combined susceptibility for <b>{lat.toFixed(4)}, {lng.toFixed(4)}</b>
            {selectedHab ? ` (${selectedHab.village_name})` : ''}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => loadAssessment(false)}
              disabled={loading.assessment}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sm-panel-2 hover:bg-sm-panel-2/80 border border-sm-border text-sm-text font-semibold text-xs transition disabled:opacity-50 cursor-pointer"
            >
              <RefreshCw className="w-3 h-3" /> Recompute
            </button>
            <button
              onClick={() => loadAssessment(true)}
              disabled={loading.assessment}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sm-green hover:bg-sm-green-hover text-slate-900 font-semibold text-xs transition disabled:opacity-50 cursor-pointer"
            >
              <Activity className="w-3 h-3" /> Force recalc
            </button>
          </div>
        </div>

        {assessment ? (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="space-y-3">
              <div className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl border font-bold text-sm ${bandClass[assessment.risk_band] ?? bandClass.UNKNOWN}`}>
                <ShieldAlert className="w-4 h-4" />
                {assessment.risk_band} — {assessment.risk_score ?? 'No score'}
                {assessment.risk_score != null ? '/100' : ''}
              </div>
              {assessment.disaster_type && (
                <div className="text-xs text-sm-muted">Primary hazard class: <b>{assessment.disaster_type.replace(/_/g, ' ')}</b></div>
              )}
              <div className="text-[11px] text-sm-muted">
                Mode <b>{String(assessment.assessment_mode).toUpperCase()}</b> · model status{' '}
                <b>{String(assessment.model_status ?? 'RULE_BASED').replace(/_/g, ' ')}</b>
              </div>
              <div className="text-[11px] text-sm-muted leading-snug italic mt-1">{assessment.caveat}</div>
            </div>

            <div className="lg:col-span-2">
              <div className="text-[10px] font-bold text-sm-muted uppercase tracking-wider mb-2">Factor decomposition</div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {assessment.factors.map((f) => (
                  <div key={f.key} className="p-2.5 rounded-lg bg-sm-panel-2 border border-sm-border">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-sm-text">{f.label}</span>
                      <span className="text-[10px] font-bold text-sm-muted">
                        {f.score != null ? `${f.score} · ${f.impact.replace(/_/g, ' ').toLowerCase()}` : 'no signal'}
                      </span>
                    </div>
                    {f.detail && <p className="text-[10px] text-sm-muted mt-0.5 leading-snug">{f.detail}</p>}
                  </div>
                ))}
              </div>
              {assessment.sources.length > 0 && (
                <div className="mt-3 text-[10px] text-sm-muted">
                  Sources: {assessment.sources.map((s) => `${s.name} (${String(s.status).replace(/_/g, ' ').toLowerCase()})`).join(' · ')}
                </div>
              )}
            </div>
          </div>
        ) : (
          <p className="text-xs text-sm-muted">{loading.assessment ? 'Computing…' : (errors.assessment ?? 'Press "Assess this point" to run the risk engine.')}</p>
        )}
      </Section>

      {/* Bhuvan / ISRO supporting layer */}
      <Section title="Bhuvan / ISRO (Supporting Geospatial Layer)">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <p className="text-xs text-sm-muted">
            Official ISRO Bhuvan APIs — census-2001 village geocode, LULC surface cover, hospitals (AP) and intra-state routing.
            Static datasets are annotated and never labelled live.
          </p>
          <button
            onClick={loadBhuvan}
            disabled={loading.bhuvan}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white font-semibold text-xs transition disabled:opacity-50 cursor-pointer"
          >
            <Satellite className="w-3.5 h-3.5" /> {bhuvan ? 'Re-query Bhuvan' : 'Query Bhuvan'}
          </button>
        </div>
        {errors.bhuvan && <p className="text-xs text-amber-400 mb-2">{errors.bhuvan}</p>}
        {!bhuvan ? (
          <p className="text-xs text-sm-muted">
            {loading.bhuvan ? 'Querying Bhuvan / ISRO…' : 'Press "Query Bhuvan" to enrich this point with census, land-cover and routing context.'}
          </p>
        ) : (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {/* Village geocode */}
              <div className="p-3 rounded-lg border border-sm-border bg-sm-panel-2">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[10px] font-bold text-sm-muted uppercase tracking-wider">Village (census 2001)</span>
                  <DataStatusBadge status={bhuvan.village.data_status} />
                </div>
                {bhuvan.village.data_status === 'AVAILABLE' || bhuvan.village.data_status === 'CACHED' ? (
                  bhuvan.village.record ? (
                    <div className="text-xs text-sm-text space-y-0.5">
                      <div className="font-bold">{bhuvan.village.record.name}</div>
                      <div>
                        {[bhuvan.village.record.sub_district, bhuvan.village.record.district].filter(Boolean).join(' · ')}
                        {bhuvan.village.record.households ? ` · ${bhuvan.village.record.households} households` : ''}
                      </div>
                      {bhuvan.village.record.census_village_code && (
                        <div className="text-[10px] text-sm-muted">Census code {bhuvan.village.record.census_village_code}</div>
                      )}
                      {bhuvan.village.coordinate_note && (
                        <div className="text-[10px] text-sm-muted italic">{bhuvan.village.coordinate_note}</div>
                      )}
                    </div>
                  ) : (
                    <p className="text-xs text-sm-muted">No census record matched.</p>
                  )
                ) : (
                  <p className="text-xs text-sm-muted">
                    {bhuvan.village.data_status === 'LOCATION_MISMATCH'
                      ? 'Census record belongs to a different district — kept separate, not merged.'
                      : (bhuvan.village.reason ?? 'Unavailable for this point.')}
                  </p>
                )}
                {bhuvan.village.coverage_note && <p className="text-[10px] text-sm-muted mt-1">{bhuvan.village.coverage_note}</p>}
              </div>

              {/* LULC */}
              <div className="p-3 rounded-lg border border-sm-border bg-sm-panel-2">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[10px] font-bold text-sm-muted uppercase tracking-wider">LULC surface cover</span>
                  <DataStatusBadge status={bhuvan.lulc.data_status} />
                </div>
                {bhuvan.lulc.data_status === 'AVAILABLE' || bhuvan.lulc.data_status === 'CACHED' ? (
                  <div className="text-xs text-sm-text space-y-0.5">
                    <div className="font-bold">{bhuvan.lulc.class ?? 'Unknown class'}</div>
                    {bhuvan.lulc.dataset_year && <div className="text-[10px] text-sm-muted">Dataset year {bhuvan.lulc.dataset_year}</div>}
                    <div className="text-[10px] text-sm-muted italic">ISRO LULC 250K classification — surface cover, not a flood model.</div>
                  </div>
                ) : (
                  <p className="text-xs text-sm-muted">{bhuvan.lulc.reason ?? 'No LULC class for this point.'}</p>
                )}
              </div>

              {/* Hospitals */}
              <div className="p-3 rounded-lg border border-sm-border bg-sm-panel-2">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[10px] font-bold text-sm-muted uppercase tracking-wider">Hospitals ({bhuvan.hospitals.buffer_m} m)</span>
                  <DataStatusBadge status={bhuvan.hospitals.data_status} />
                </div>
                {bhuvan.hospitals.data_status === 'AVAILABLE' || bhuvan.hospitals.data_status === 'CACHED' ? (
                  bhuvan.hospitals.count === 0 ? (
                    <p className="text-xs text-sm-muted">No Bhuvan hospitals within the buffer.</p>
                  ) : (
                    <div className="space-y-1">
                      {bhuvan.hospitals.hospitals.slice(0, 5).map((h, i) => (
                        <div key={i} className="text-xs text-sm-text flex justify-between gap-2">
                          <span className="truncate">{h.name ?? 'Unnamed facility'}</span>
                          {h.distance_m != null && <span className="text-[10px] text-sm-muted shrink-0">{(h.distance_m / 1000).toFixed(1)} km</span>}
                        </div>
                      ))}
                    </div>
                  )
                ) : (
                  <p className="text-xs text-sm-muted">{bhuvan.hospitals.reason ?? 'Hospitals unavailable.'}</p>
                )}
                <p className="text-[10px] text-sm-muted mt-1">Bhuvan hospitals cover Andhra Pradesh only; OSM hospitals remain the authoritative list.</p>
              </div>

              {/* Shortest path */}
              <div className="p-3 rounded-lg border border-sm-border bg-sm-panel-2">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[10px] font-bold text-sm-muted uppercase tracking-wider">Intra-state shortest path</span>
                  <DataStatusBadge status={bhuvan.route.data_status} />
                </div>
                {bhuvan.route.data_status === 'AVAILABLE' || bhuvan.route.data_status === 'CACHED' ? (
                  <div className="text-xs text-sm-text space-y-0.5">
                    <div className="font-bold">{bhuvan.route.distance_km != null ? `${bhuvan.route.distance_km.toFixed(1)} km` : 'Route found'}</div>
                    <div className="text-[10px] text-sm-muted italic">Bhuvan routing is intra-state; the risk-classified SAFE/CAUTION route remains authoritative.</div>
                  </div>
                ) : (
                  <p className="text-xs text-sm-muted">{bhuvan.route.reason ?? 'No route available.'}</p>
                )}
              </div>
            </div>
            <div className="mt-3 text-[11px] text-sm-muted">
              Reverse geocode (census):{' '}
              {bhuvan.reverse.villages.length > 0 ? bhuvan.reverse.villages.slice(0, 3).join(', ') : 'no census settlement at this point'}.
              {' '}Coordinates, elevation (SRTM) and hospital authority remain with the already-verified live providers.
            </div>
          </>
        )}
      </Section>

      {/* Risk zones */}
      <Section title="AI-Assessed High-Risk Zones">
        <div className="flex items-center justify-between mb-3">
          <p className="text-xs text-sm-muted">
            Model-generated susceptibility labels for the selected habitations — not official notifications.
          </p>
          <button
            onClick={refreshZones}
            disabled={zonesLoading}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sm-panel-2 hover:bg-sm-panel-2/80 border border-sm-border text-sm-text font-semibold text-xs transition disabled:opacity-50 cursor-pointer"
          >
            <RefreshCw className={`w-3 h-3 ${zonesLoading ? 'animate-spin' : ''}`} /> Refresh zones
          </button>
        </div>
        {errors.zones && <p className="text-xs text-amber-400 mb-2">{errors.zones}</p>}
        {zones.length === 0 ? (
          <p className="text-xs text-sm-muted">No zones computed yet.</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {zones.slice(0, 24).map((zone) => (
              <div key={zone.id} className="p-3 rounded-lg border border-sm-border bg-sm-panel-2 flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-xs font-bold text-sm-text truncate">{zone.label}</div>
                  <div className="text-[10px] text-sm-muted">
                    {zone.hazards.slice(0, 2).join(' · ') || '—'}
                  </div>
                  <button
                    onClick={() => locate(zone.latitude, zone.longitude, zone.label)}
                    className="mt-1.5 inline-flex items-center gap-1 text-[10px] font-semibold text-sm-green hover:underline cursor-pointer"
                  >
                    <MapPin className="w-3 h-3" /> Locate
                  </button>
                </div>
                <span className={`shrink-0 inline-flex items-center px-2 py-0.5 rounded-full border text-[10px] font-bold ${bandClass[zone.risk_band] ?? bandClass.UNKNOWN}`}>
                  {zone.risk_band} {zone.risk_score != null ? `· ${zone.risk_score}` : ''}
                </span>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* Safe locations + nearby + disasters */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Section title="Safe Locations & Relocation Candidates">
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs text-sm-muted">Ranked safe facilities for {selectedHab?.village_name ?? `${lat.toFixed(3)}, ${lng.toFixed(3)}`}.</p>
            {safeLocs && <DataStatusBadge status={safeLocs.data_status} />}
          </div>
          <button
              onClick={loadSafeLocations}
              disabled={loading.safe}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-700 hover:bg-emerald-800 text-white font-semibold text-xs transition disabled:opacity-50 cursor-pointer"
            >
              <ShieldCheck className="w-3 h-3" /> Find safe locations
            </button>
          {errors.safe && <p className="text-xs text-amber-400 mb-2">{errors.safe}</p>}
          {safeLocs ? (
            safeLocs.locations.length === 0 ? (
              <p className="text-xs text-sm-muted">No recommended location within safe bands.</p>
            ) : (
              <div className="space-y-2">
                {safeLocs.locations.slice(0, 6).map((loc) => (
                  <div key={loc.id} className="p-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-xs font-bold text-sm-text truncate">{loc.name}</div>
                      <div className="text-[10px] text-sm-muted">
                        {loc.kind.replace(/_/g, ' ')} · {loc.distance_km} km · grade {loc.data_grade}
                        {loc.available_capacity_families != null ? ` · ${loc.available_capacity_families} family slots` : ''}
                      </div>
                      <button
                        onClick={() => locate(loc.latitude, loc.longitude, loc.name)}
                        className="mt-1.5 inline-flex items-center gap-1 text-[10px] font-semibold text-sm-green hover:underline cursor-pointer"
                      >
                        <MapPin className="w-3 h-3" /> Locate
                      </button>
                    </div>
                    <span className={`shrink-0 inline-flex items-center px-2 py-0.5 rounded-full border text-[10px] font-bold ${bandClass[loc.risk_band ?? 'UNKNOWN'] ?? bandClass.UNKNOWN}`}>
                      {loc.risk_band ?? 'UNKNOWN'}
                    </span>
                  </div>
                ))}
              </div>
            )
          ) : (
            <p className="text-xs text-sm-muted">{loading.safe ? 'Searching…' : 'Press "Find safe locations" to rank candidates.'}</p>
          )}
        </Section>

        <div className="grid grid-cols-1 gap-6">
          <Section title="Nearby Hospitals & Clinics">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-1.5 text-sm-muted text-[11px]"><HeartPulse className="w-3.5 h-3.5" /> OpenStreetMap</div>
              {reports && <DataStatusBadge status={reports.data_status} />}
              <button
                onClick={loadNearby}
                disabled={loading.nearby}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sm-panel-2 hover:bg-sm-panel-2/80 border border-sm-border text-sm-text font-semibold text-xs transition disabled:opacity-50 cursor-pointer"
              >
                <Navigation className="w-3 h-3" /> Search 25 km
              </button>
            </div>
            {errors.nearby && <p className="text-xs text-amber-400 mb-2">{errors.nearby}</p>}
            {reports ? (
              reports.places.length === 0 ? (
                <p className="text-xs text-sm-muted">No nearby {reports.label.toLowerCase()} found within range.</p>
              ) : (
                <div className="space-y-1.5">
                  {reports.places.slice(0, 6).map((p) => (
                    <div key={`${p.osm_type}-${p.osm_id}`} className="flex items-center justify-between gap-2 p-2 rounded-lg bg-sm-panel-2 border border-sm-border">
                      <span className="text-xs font-semibold text-sm-text truncate">{p.name}</span>
                      <span className="text-[10px] text-sm-muted shrink-0">{p.distance_km} km</span>
                    </div>
                  ))}
                </div>
              )
            ) : (
              <p className="text-xs text-sm-muted">{loading.nearby ? 'Searching…' : 'Press "Search 25 km" to find nearby critical facilities.'}</p>
            )}
          </Section>

          <Section title="Historical Disaster Record (100 km)">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-1.5 text-sm-muted text-[11px]"><CalendarDays className="w-3.5 h-3.5" /> Curated, source-referenced</div>
              {disasters && <DataStatusBadge status={disasters.data_status} />}
              <button
                onClick={loadDisasters}
                disabled={loading.disasters}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sm-panel-2 hover:bg-sm-panel-2/80 border border-sm-border text-sm-text font-semibold text-xs transition disabled:opacity-50 cursor-pointer"
              >
                <RefreshCw className="w-3 h-3" /> Refresh
              </button>
            </div>
            {errors.disasters && <p className="text-xs text-amber-400 mb-2">{errors.disasters}</p>}
            {disasters ? (
              disasters.events.length === 0 ? (
                <p className="text-xs text-sm-muted">No curated events within range of this point.</p>
              ) : (
                <div className="space-y-1.5">
                  {disasters.events.slice(0, 6).map((e) => (
                    <div key={e.id} className="p-2.5 rounded-lg bg-sm-panel-2 border border-sm-border">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-semibold text-sm-text truncate">{e.name}</span>
                        <span className="text-[10px] text-sm-muted shrink-0">{e.event_date.slice(0, 4)} · {e.distance_km?.toFixed(1)} km</span>
                      </div>
                      {e.description && <p className="text-[10px] text-sm-muted leading-snug mt-0.5">{e.description}</p>}
                      <span className="text-[9px] text-sm-muted">{e.hazard_type.replace(/_/g, ' ')} · {e.state}{e.district ? ` / ${e.district}` : ''}</span>
                    </div>
                  ))}
                </div>
              )
            ) : (
              <p className="text-xs text-sm-muted">{loading.disasters ? 'Loading…' : 'Loading historical record…'}</p>
            )}
          </Section>
        </div>
      </div>

      {onLocateOnMap && (
        <div className="text-[11px] text-sm-muted flex items-center gap-1.5">
          <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />
          Live data relies on open and configured providers (Open-Meteo, GloFAS, NASA GPM, OSM). When unavailable, the platform says so explicitly.
        </div>
      )}
    </div>
  );
};