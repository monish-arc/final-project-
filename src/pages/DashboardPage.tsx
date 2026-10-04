import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  MapPin,
  ArrowRight,
  AlertTriangle,
  History,
} from 'lucide-react';
import {
  DashboardSummary,
  Habitation,
  RelocationSite,
  RedZone,
  MapLayerItem,
  FieldReport,
  DisasterEventResponse,
  RiskZone,
  RainfallGridPoint,
  FloodForecastResponse,
  DataStatusEntry,
  BhuvanShortestPathResponse,
  RiskAlert,
  WeatherResponse,
  TerrainResponse,
  FloodRiskResponse,
  RainfallResponse,
  RiskAssessmentResponse,
  SafeLocationsResponse,
  DisasterEventsResponse,
  SafeRouteOption,
  HistoricalAvailability,
  HistoricalBaseline,
  HistoricalDistrictSummary,
  RegionSelection,
} from '../types';
import { NavTab } from '../components/Sidebar';
import { RegionViewportFocus } from '../lib/regionViewport';
import { apiService } from '../services/api';
import { HistoricalBaselineCard } from '../components/HistoricalBaselineCard';
import { DataStatusBadge } from '../components/DataStatusBadge';
import { LocationControlBar } from '../components/commandcenter/LocationControlBar';
import { RiskSummaryRow } from '../components/commandcenter/RiskSummaryRow';
import { ActiveAlertsPanel } from '../components/commandcenter/ActiveAlertsPanel';
import { EmergencyServicesRow } from '../components/commandcenter/EmergencyServicesRow';
import { HabitationRiskTable } from '../components/commandcenter/HabitationRiskTable';
import { RiskFactorBars } from '../components/commandcenter/RiskFactorBars';
import { AIExplanationPanel } from '../components/commandcenter/AIExplanationPanel';
import { SafeLocationsCards } from '../components/commandcenter/SafeLocationsCards';
import { RouteIntelligence } from '../components/commandcenter/RouteIntelligence';
import { DataSourcesPanel } from '../components/commandcenter/DataSourcesPanel';

interface DashboardPageProps {
  summary: DashboardSummary | null;
  habitations: Habitation[];
  relocationSites: RelocationSite[];
  redZones: RedZone[];
  infrastructure: MapLayerItem[];
  fieldReports: FieldReport[];
  disasterEvents: DisasterEventResponse[];
  riskZones: RiskZone[];
  rainfallGrid: RainfallGridPoint[];
  floodForecast: FloodForecastResponse | null;
  dataStatus: DataStatusEntry[] | null;
  bhuvanRoute: BhuvanShortestPathResponse | null;
  riskAlerts: RiskAlert[];
  habitationsMeta: { data_status: string; data_source: string; count: number; reason: string | null } | null;
  focusRegion: RegionViewportFocus | null;
  region: RegionSelection;
  loading: boolean;
  dataLastUpdated: Date | null;
  onRefresh: () => void;
  onRegionChange: (region: RegionSelection) => void;
  onSelectHabitation: (hab: Habitation) => void;
  onNavigateTab: (tab: NavTab) => void;
  onOpenEvacuation: (hab: Habitation) => void;
  onLocateOnMap: (focus: RegionViewportFocus) => void;
  onBhuvanRouteLoaded: (route: BhuvanShortestPathResponse | null) => void;
  historicalAvailability: HistoricalAvailability | null;
  historicalSummaries: HistoricalDistrictSummary[];
  historicalBaseline: HistoricalBaseline | null;
  historicalDistrictId: number | null;
  onHistoricalDistrictChange: (districtId: number) => void;
  regionLabel: string;
}

function LiveTile({
  title,
  status,
  reason,
  loading,
  rows,
}: {
  title: string;
  status: string | null | undefined;
  reason?: string | null;
  loading?: boolean;
  rows: Array<[string, string]> | null;
}) {
  return (
    <div className="bg-sm-panel border border-sm-border rounded-xl shadow p-3.5">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] font-bold uppercase tracking-wider text-sm-muted">{title}</span>
        {loading ? (
          <span className="text-[9px] text-sm-muted animate-pulse">Fetching…</span>
        ) : (
          <DataStatusBadge status={status} title={reason ?? ''} />
        )}
      </div>
      {loading ? null : rows ? (
        <div className="grid grid-cols-2 gap-x-3 gap-y-1">
          {rows.map(([k, v]) => (
            <div key={k} className="text-[11px]">
              <span className="text-sm-muted block text-[9px] uppercase tracking-wide">{k}</span>
              <span className="text-sm-text font-semibold">{v}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-[10px] text-sm-muted leading-snug">
          {status === 'UNAVAILABLE' ? reason ?? 'Provider unreachable — no fabricated values.' : status}
        </p>
      )}
    </div>
  );
}

export const DashboardPage: React.FC<DashboardPageProps> = ({
  summary,
  habitations,
  relocationSites,
  redZones,
  infrastructure,
  fieldReports,
  disasterEvents,
  riskZones,
  rainfallGrid,
  floodForecast,
  dataStatus,
  bhuvanRoute,
  riskAlerts,
  habitationsMeta,
  focusRegion,
  region,
  loading,
  dataLastUpdated,
  onRefresh,
  onRegionChange,
  onSelectHabitation,
  onNavigateTab,
  onOpenEvacuation,
  onLocateOnMap,
  onBhuvanRouteLoaded,
  historicalAvailability,
  historicalSummaries,
  historicalBaseline,
  historicalDistrictId,
  onHistoricalDistrictChange,
  regionLabel,
}) => {
  // ---- Anchor (habitation that drives live analysis) ----
  const [activeHabId, setActiveHabId] = useState<string | null>(
    focusRegion?.habitationId ?? null
  );

  // Auto-follow region focus to a surveyed habitation when one exists.
  useEffect(() => {
    if (!focusRegion?.habitationId) return;
    setActiveHabId((prev) => prev ?? focusRegion!.habitationId ?? null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusRegion?.key]);

  const anchorHab = useMemo(
    () => habitations.find((h) => h.id === activeHabId) ?? null,
    [habitations, activeHabId]
  );
  const anchorPoint = anchorHab
    ? { lat: anchorHab.latitude, lng: anchorHab.longitude, label: anchorHab.village_name }
    : null;
  const anchorKey = anchorPoint ? `${anchorPoint.lat.toFixed(4)},${anchorPoint.lng.toFixed(4)}` : null;

  // ---- Live point state ----
  const [weather, setWeather] = useState<WeatherResponse | null>(null);
  const [terrain, setTerrain] = useState<TerrainResponse | null>(null);
  const [flood, setFlood] = useState<FloodRiskResponse | null>(null);
  const [rainfall, setRainfall] = useState<RainfallResponse | null>(null);
  const [assessment, setAssessment] = useState<RiskAssessmentResponse | null>(null);
  const [safeLocs, setSafeLocs] = useState<SafeLocationsResponse | null>(null);
  const [historyNear, setHistoryNear] = useState<DisasterEventsResponse | null>(null);
  const [liveLoading, setLiveLoading] = useState(false);
  const liveSeqRef = useRef(0);

  // Debounced live fetch for the anchor point. Response drops when a newer
  // anchor is chosen mid-flight.
  useEffect(() => {
    if (!anchorPoint) {
      setWeather(null);
      setTerrain(null);
      setFlood(null);
      setRainfall(null);
      setAssessment(null);
      setSafeLocs(null);
      setHistoryNear(null);
      setLiveLoading(false);
      return;
    }
    const timer = setTimeout(() => {
      const seq = ++liveSeqRef.current;
      setLiveLoading(true);
      const base = { latitude: anchorPoint.lat, longitude: anchorPoint.lng };
      Promise.all([
        apiService.getWeather(anchorPoint.lat, anchorPoint.lng).catch(() => null),
        apiService.getTerrain(anchorPoint.lat, anchorPoint.lng).catch(() => null),
        apiService.getFloodRisk(anchorPoint.lat, anchorPoint.lng).catch(() => null),
        apiService.getRainfall(anchorPoint.lat, anchorPoint.lng).catch(() => null),
        apiService
          .getRiskAssessment({ ...base, placeLabel: anchorPoint.label })
          .catch(() => null),
        apiService
          .getSafeLocations({ ...base, affectedPopulation: anchorHab?.population ?? 0 })
          .catch(() => null),
        apiService.getDisasterEventsNear(anchorPoint.lat, anchorPoint.lng, 100).catch(() => null),
      ]).then(([w, t, f, r, a, s, h]) => {
        if (seq !== liveSeqRef.current) return;
        setWeather(w);
        setTerrain(t);
        setFlood(f);
        setRainfall(r);
        setAssessment(a);
        setSafeLocs(s);
        setHistoryNear(h);
        setLiveLoading(false);
      }).finally(() => {
        if (seq === liveSeqRef.current) setLiveLoading(false);
      });
    }, 250);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anchorKey, anchorHab?.population]);

  const setAnchor = (hab: Habitation) => {
    setActiveHabId(hab.id);
  };

  // ---- Route destination derived from the top safe location ----
  const destPoint = useMemo(() => {
    const top = safeLocs?.locations?.[0];
    if (!top) return null;
    return { lat: top.latitude, lng: top.longitude, label: top.name };
  }, [safeLocs]);

  const [safeRoute, setSafeRoute] = useState<SafeRouteOption | null>(null);
  const [anchorForRoute, setAnchorForRoute] = useState<{ lat: number; lng: number; label: string } | null>(null);
  useEffect(() => {
    // Route Intelligence is only meaningful on the same anchor the user is
    // analysing. Prompting explicitly is less surprising than auto-blasting.
    setAnchorForRoute(anchorPoint && destPoint ? anchorPoint : null);
  }, [anchorKey, anchorPoint, destPoint]);

  const handleControlBarHabitation = (hab: Habitation | null) => {
    setActiveHabId(hab?.id ?? null);
  };

  const regionTitle = regionLabel || 'Selected region';

  return (
    <div id="executive-dashboard-view" className="space-y-5">
      {/* Row 1: Sticky location control bar */}
      <div className="sticky top-0 z-30 -mx-4 px-4 sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8 bg-sm-bg/95 backdrop-blur py-2 rounded-xl">
        <LocationControlBar
          region={region}
          habitations={habitations}
          activeHabId={activeHabId}
          loading={loading || liveLoading}
          dataLastUpdated={dataLastUpdated}
          dataStatus={dataStatus}
          onRegionChange={onRegionChange}
          onSelectHabitation={handleControlBarHabitation}
          onRefresh={onRefresh}
        />
      </div>

      {/* Row 2: Header */}
      <div className="bg-gradient-to-r from-sm-panel via-sm-panel-2 to-sm-panel rounded-xl p-5 text-sm-text border border-sm-border shadow-md flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1.5">
            <span className="bg-red-500/20 text-red-300 border border-red-500/30 text-xs px-2.5 py-0.5 rounded-full font-mono font-medium">
              AI-POWERED DISASTER COMMAND CENTER
            </span>
            <span className="text-xs text-sm-muted">
              {regionTitle}
              {summary?.data_status === 'UNAVAILABLE' ? ' — summary unavailable for this location' : ''}
            </span>
          </div>
          <h2 className="text-2xl font-extrabold tracking-tight">
            Proactive Red-Zone &amp; Relocation Decision Platform
          </h2>
          <p className="text-sm text-sm-muted mt-1 max-w-3xl">
            Detect → assess → prioritise → safe locations → route → relocate. Every card
          reports the real provider that served it; nothing is fabricated for
          regions without curated data.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            id="open-gis-map-dashboard-btn"
            onClick={() => onNavigateTab('map')}
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-sm-green hover:bg-sm-green-hover text-slate-900 text-xs font-bold shadow-sm transition cursor-pointer"
          >
            <MapPin className="w-4 h-4" />
            <span>Launch GIS Map</span>
          </button>
          <button
            id="open-safeshift-dashboard-btn"
            onClick={() => onNavigateTab('simulator')}
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-sm-panel-2 hover:bg-sm-panel-2/80 text-sm-text border border-sm-border text-xs font-bold transition cursor-pointer"
          >
            <span>Relocation Simulator</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Row 3: Risk summary */}
      <RiskSummaryRow summary={summary} regionLabel={regionTitle} />

      {/* Row 4: Alerts rail */}
      <div className="grid grid-cols-1 gap-5">
        <div className="flex flex-col gap-4">
          <ActiveAlertsPanel
            riskAlerts={riskAlerts}
            redZones={redZones}
            regionLabel={regionTitle}
            onLocateOnMap={onLocateOnMap}
          />
        </div>
      </div>

      {/* Row 5: Live point strip */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <LiveTile
          title="Live Weather"
          loading={liveLoading}
          status={weather?.data_status}
          reason={weather?.reason}
          rows={weather?.current
            ? [
                ['Temp', `${weather.current.temperature_c?.toFixed(1) ?? '—'} °C`],
                ['Rain', `${weather.current.precipitation_mm ?? '—'} mm/hr`],
                ['Condition', weather.current.weather_description ?? '—'],
                ['Source', weather.data_source],
              ]
            : null}
        />
        <LiveTile
          title="Terrain (NASA SRTM)"
          loading={liveLoading}
          status={terrain?.data_status}
          reason={terrain?.reason}
          rows={terrain?.elevation_m != null
            ? [
                ['Elevation', `${terrain.elevation_m.toFixed(0)} m`],
                ['Slope', `${terrain.slope_percent?.toFixed(1) ?? '—'} %`],
                ['Category', terrain.slope_category ?? '—'],
                ['Source', terrain.data_source ?? terrain.dataset ?? 'NASA Earthdata SRTM'],
              ]
            : null}
        />
        <LiveTile
          title="River Flood (GloFAS)"
          loading={liveLoading}
          status={flood?.data_status}
          reason={flood?.reason}
          rows={flood?.discharge_band
            ? [
                ['Discharge', `${flood.river_discharge_m3s?.toFixed(0) ?? '—'} m³/s`],
                ['Band', flood.discharge_band],
              ]
            : null}
        />
        <LiveTile
          title="Rainfall (NASA GPM)"
          loading={liveLoading}
          status={rainfall?.data_status}
          reason={rainfall?.reason}
          rows={rainfall?.precipitation_mm_hour != null
            ? [
                ['Intensity', `${rainfall.precipitation_mm_hour} mm/hr`],
                ['Dataset', rainfall.dataset ?? '—'],
              ]
            : null}
        />
      </div>
      <p className="text-[10px] text-sm-muted">
        {anchorPoint
          ? `Live providers probed around ${anchorPoint.label} (${anchorPoint.lat.toFixed(4)}, ${anchorPoint.lng.toFixed(4)}).`
          : 'Select a habitation in the control bar to probe live providers.'}
      </p>

      {/* Row 6: Habitation risk table */}
      <HabitationRiskTable
        habitations={habitations}
        region={region}
        activeHabId={activeHabId}
        onSelectHabitation={(hab) => {
          setAnchor(hab);
          onSelectHabitation(hab);
        }}
      />

      {/* Row 7: Safe locations + AI explanation + factor bars */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div className="lg:col-span-2">
          <SafeLocationsCards locations={safeLocs?.locations ?? []} loading={liveLoading} anchor={anchorPoint} />
        </div>
        <div className="space-y-5">
          <AIExplanationPanel assessment={assessment} loading={liveLoading} anchorLabel={anchorPoint?.label ?? null} />
        </div>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div className="lg:col-span-1">
          <RiskFactorBars assessment={assessment} loading={liveLoading} anchorLabel={anchorPoint?.label ?? null} />
        </div>
        <div className="lg:col-span-2">
          <RouteIntelligence
            origin={anchorForRoute ? { ...anchorForRoute } : null}
            destination={destPoint}
            anchorKey={anchorKey ?? 'none'}
            running={liveLoading || loading}
            onSafeRouteChange={setSafeRoute}
            onBhuvanRouteLoaded={onBhuvanRouteLoaded}
            onLocateOnMap={onLocateOnMap}
          />
        </div>
      </div>

      {/* Row 8: Relocation priority | disaster history | emergency services */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div className="bg-sm-panel border border-sm-border rounded-xl shadow p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-bold uppercase tracking-wider text-sm-text">
              Relocation Priority
            </h3>
            <button
              onClick={() => onNavigateTab('priority')}
              className="text-[10px] font-semibold text-sm-green hover:text-sm-green-hover cursor-pointer"
            >
              View all ({summary?.total_habitations_monitored ?? 0})
            </button>
          </div>
          {(summary?.top_five_critical_villages ?? []).length === 0 ? (
            <p className="text-[11px] text-sm-muted">
              No risk-ranked habitations for {regionTitle}. Nothing fabricated.
            </p>
          ) : (
            <div className="space-y-2">
              {summary!.top_five_critical_villages.slice(0, 5).map((hab, index) => (
                <div
                  key={hab.id}
                  onClick={() => {
                    setAnchor(hab);
                    onSelectHabitation(hab);
                  }}
                  className="rounded-lg border border-sm-border bg-sm-panel-2 p-2.5 cursor-pointer hover:border-sm-border transition space-y-1"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] font-bold text-sm-text truncate">
                      #{index + 1} {hab.village_name}
                    </span>
                    <span className="text-[10px] font-bold text-red-300">{hab.priority_score}/100</span>
                  </div>
                  <div className="w-full h-1.5 bg-sm-border rounded-full overflow-hidden">
                    <div
                      className={`h-full ${hab.priority_score >= 75 ? 'bg-red-500' : hab.priority_score >= 60 ? 'bg-orange-400' : hab.priority_score >= 45 ? 'bg-yellow-400' : 'bg-emerald-500'}`}
                      style={{ width: `${Math.min(100, Math.max(4, hab.priority_score))}%` }}
                    />
                  </div>
                  <div className="flex items-center justify-between text-[9px] text-sm-muted">
                    <span>{hab.population.toLocaleString()} people · {hab.households} hh</span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onOpenEvacuation(hab);
                      }}
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-red-600/20 border border-red-500/40 text-red-300 hover:bg-red-600/30 font-semibold cursor-pointer"
                    >
                      Evacuate <ArrowRight className="w-2.5 h-2.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="bg-sm-panel border border-sm-border rounded-xl shadow p-4">
          <div className="flex items-center gap-2 mb-3">
            <History className="w-4 h-4 text-violet-400" />
            <div>
              <h3 className="text-xs font-bold uppercase tracking-wider text-sm-text">
                Disaster History Nearby
              </h3>
              <p className="text-[10px] text-sm-muted">
                {anchorPoint ? `Within 100 km of ${anchorPoint.label}` : 'Region records'}
              </p>
            </div>
          </div>
          {liveLoading ? (
            <p className="text-[11px] text-sm-muted">Loading records…</p>
          ) : (historyNear?.events ?? []).length === 0 ? (
            <p className="text-[11px] text-sm-muted">
              {anchorPoint
                ? historyNear?.reason ?? 'No documented events near this point — nothing fabricated.'
                : (disasterEvents.length > 0
                    ? `${disasterEvents.length} documented events in the selected region.`
                    : 'No documented events for this selection.')}
            </p>
          ) : (
            <div className="space-y-2">
              {historyNear!.events.slice(0, 6).map((ev) => (
                <div key={ev.id} className="rounded-lg border border-sm-border bg-sm-panel-2 p-2.5 space-y-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] font-bold text-sm-text">
                      <AlertTriangle className="w-3 h-3 inline text-amber-400 mr-1" />
                      {ev.name || ev.hazard_type}
                    </span>
                    <span className="text-[9px] text-sm-muted">
                      {new Date(ev.event_date).toLocaleDateString(undefined, { month: 'short', year: 'numeric' })}
                    </span>
                  </div>
                  <p className="text-[10px] text-sm-muted line-clamp-2">{ev.description}</p>
                </div>
              ))}
            </div>
          )}
        </div>

        <EmergencyServicesRow
          anchor={anchorPoint}
          anchorKey={anchorKey ?? 'none'}
          onLocateOnMap={onLocateOnMap}
        />
      </div>

      {/* Row 9: Field reports | data sources | historical baseline */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div className="bg-sm-panel border border-sm-border rounded-xl shadow p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-bold uppercase tracking-wider text-sm-text">
              Field Officer Alerts
            </h3>
            <button
              onClick={() => onNavigateTab('field_reports')}
              className="text-[10px] font-semibold text-sm-green hover:text-sm-green-hover cursor-pointer"
            >
              All reports
            </button>
          </div>
          {fieldReports.length === 0 ? (
            <p className="text-[11px] text-sm-muted">
              No field reports filed for {regionTitle}. Nothing fabricated.
            </p>
          ) : (
            <div className="space-y-2">
              {fieldReports.slice(0, 4).map((r) => (
                <div key={r.id} className="rounded-lg border border-sm-border bg-sm-panel-2 p-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] font-bold text-sm-text">{r.habitation_name}</span>
                    <span className={`text-[9px] px-1.5 py-0.5 rounded border font-bold ${r.verified ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40' : 'bg-amber-500/20 text-amber-300 border-amber-500/40'}`}>
                      {r.verified ? 'Verified' : 'Pending'}
                    </span>
                  </div>
                  <p className="text-[10px] text-sm-muted line-clamp-2 mt-1">{r.description}</p>
                  <div className="text-[9px] text-sm-muted mt-1 flex items-center justify-between">
                    <span>by {r.officer_name}</span>
                    <span>{new Date(r.reported_at).toLocaleDateString()}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
        <DataSourcesPanel dataStatus={dataStatus} />
        <div className="bg-sm-panel border border-sm-border rounded-xl shadow p-4">
          <HistoricalBaselineCard
            availability={historicalAvailability}
            summaries={historicalSummaries}
            baseline={historicalBaseline}
            selectedDistrictId={historicalDistrictId}
            onDistrictChange={onHistoricalDistrictChange}
          />
        </div>
      </div>
    </div>
  );
};