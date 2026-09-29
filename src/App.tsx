import React, { useState, useEffect, useRef } from 'react';
import {
  Navbar,
} from './components/Navbar';
import { Sidebar, getAccessibleTabs, NavTab } from './components/Sidebar';
import { VillageModal } from './components/VillageModal';
import { SiteModal } from './components/SiteModal';
import { AccessGate } from './components/AccessGate';
import { SafeMoveLogo } from './components/SafeMoveLogo';

// Pages
import { DashboardPage } from './pages/DashboardPage';
import { GisMapPage } from './pages/GisMapPage';
import { WeatherForecastMapPage } from './pages/WeatherForecastMapPage';
import { HabitationsPage } from './pages/HabitationsPage';
import { PriorityPage } from './pages/PriorityPage';
import { SimulatorPage } from './pages/SimulatorPage';
import { FieldReportsPage } from './pages/FieldReportsPage';
import { ReportsPage } from './pages/ReportsPage';
import { AdminPage } from './pages/AdminPage';
import { DocsPage } from './pages/DocsPage';
import { RiskAlertsPage } from './pages/RiskAlertsPage';
import { EvacuationPlanPage } from './pages/EvacuationPlanPage';
import { RiskIntelligencePage } from './pages/RiskIntelligencePage';

// Types & Services
import {
  User,
  Habitation,
  RelocationSite,
  RedZone,
  FieldReport,
  RelocationRecommendation,
  DashboardSummary,
  MapLayerItem,
  HazardEvent,
  RegionSelection,
  RegionViewportFocus,
  EvacuationOriginPayload,
  FloodForecastResponse,
  DataStatusEntry,
  HistoricalAvailability,
  HistoricalBaseline,
  HistoricalDistrictSummary,
  RiskZone,
  RainfallGridPoint,
  BhuvanShortestPathResponse,
  RiskAlert,
} from './types';
import { DEMO_USERS } from './data/mockData';
import { apiService } from './services/api';
import { resolveRegionViewport } from './lib/regionViewport';
import {
  DisasterEventResponse,
  DisasterEventsResponse,
} from './types';

// "No region selected" = national overview (India viewport + nationwide events).
const EMPTY_REGION: RegionSelection = {
  state: null,
  district: null,
  subDistrict: null,
  place: null,
};

// Hard cap for any single region-load: a backend that stalls at the network
// layer (proxy hiccup, saturated worker, dropped connection) must never pin
// the portal on "Loading..." forever. On firing, LOADING → honest ERROR while
// each individual request still resolves through apiService's own timeouts.
const REGION_LOADING_DEADLINE_MS = 35 * 1000;

export default function App() {
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [activeTab, setActiveTab] = useState<NavTab>('dashboard');
  const [selectedRegion, setSelectedRegion] = useState<RegionSelection | null>(null);
  const [regionFocus, setRegionFocus] = useState<RegionViewportFocus | null>(null);
  const regionFocusKeyRef = useRef(0);
  // Explicit map-focus requests (View on Map / Locate / Show Route). Takes
  // precedence over the region-derived context and is cleared on region change.
  const [explicitMapFocus, setExplicitMapFocus] = useState<RegionViewportFocus | null>(null);
  const explicitFocusKeyRef = useRef(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Core Data
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [habitations, setHabitations] = useState<Habitation[]>([]);
  const [relocationSites, setRelocationSites] = useState<RelocationSite[]>([]);
  const [redZones, setRedZones] = useState<RedZone[]>([]);
  const [fieldReports, setFieldReports] = useState<FieldReport[]>([]);
  const [recommendations, setRecommendations] = useState<RelocationRecommendation[]>([]);
  const [infrastructure, setInfrastructure] = useState<MapLayerItem[]>([]);
  const [hazardEvents, setHazardEvents] = useState<HazardEvent[]>([]);
  const [disasterEvents, setDisasterEvents] = useState<DisasterEventResponse[]>([]);
  const [habitationsMeta, setHabitationsMeta] = useState<{
    data_status: string;
    data_source: string;
    count: number;
    reason: string | null;
  } | null>(null);
  const [floodForecast, setFloodForecast] = useState<FloodForecastResponse | null>(null);
  const [dataStatus, setDataStatus] = useState<DataStatusEntry[] | null>(null);
  const [riskZones, setRiskZones] = useState<RiskZone[]>([]);
  const [bhuvanRoute, setBhuvanRoute] = useState<BhuvanShortestPathResponse | null>(null);
  const [rainfallGrid, setRainfallGrid] = useState<RainfallGridPoint[]>([]);
  const [riskAlerts, setRiskAlerts] = useState<RiskAlert[]>([]);

  // Honest freshness: set to the wall-clock moment the latest region batch
  // finished loading. Never fabricated; derived purely from fetch completion.
  const [dataLastUpdated, setDataLastUpdated] = useState<Date | null>(null);
  // Monotonic fetch sequence: results from an older region request are dropped
  // so a slow response can never overwrite the currently-selected region.
  const regionFetchSeqRef = useRef(0);

  // Historical Rainfall (Kerala previous-year baseline)
  const [historicalAvailability, setHistoricalAvailability] = useState<HistoricalAvailability | null>(null);
  const [historicalSummaries, setHistoricalSummaries] = useState<HistoricalDistrictSummary[]>([]);
  const [historicalBaseline, setHistoricalBaseline] = useState<HistoricalBaseline | null>(null);
  const [historicalDistrictId, setHistoricalDistrictId] = useState<number | null>(null);

  // Modals & Cross-tab Navigation State
  const [modalHabitation, setModalHabitation] = useState<Habitation | null>(null);
  const [modalSite, setModalSite] = useState<RelocationSite | null>(null);
  const [simulatorHabId, setSimulatorHabId] = useState<string | undefined>(undefined);
  const [simulatorSiteId, setSimulatorSiteId] = useState<string | undefined>(undefined);
  const [evacuationOrigin, setEvacuationOrigin] = useState<EvacuationOriginPayload | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Initial load → national overview (no region selected).
  useEffect(() => {
    fetchRegionData(null);
  }, []);

  // CLAMP active tab to the current role's allowed navigation
  useEffect(() => {
    if (!currentUser) return;
    const tabs = getAccessibleTabs(currentUser.role);
    if (tabs.length > 0 && !tabs.includes(activeTab)) {
      setActiveTab(tabs[0]);
    }
  }, [currentUser, activeTab]);

  const hasSelectedRegion = (region: RegionSelection | null) => {
    return Boolean(region?.state);
  };

  // Honest curated-inventory scope: the inventory in this checkpoint only
  // genuinely exists for the curated region (Uttarakhand / Chamoli). It returns
  // true ONLY when the selected region is exactly that region — it never acts
  // as a substitute for any other location.
  // True only when the selected region genuinely matches the curated Chamoli
  // inventory (Uttarakhand / Chamoli). Any other region, or no region, returns
  // false — curated records are never substituted for another location.
  const isCuratedRegion = (region: RegionSelection | null): boolean => {
    const stateName = region?.state?.name?.toLowerCase() ?? '';
    const districtName = region?.district?.name?.toLowerCase() ?? '';
    return stateName === 'uttarakhand' && districtName === 'chamoli';
  };

  const toAlertEvent = (ev: DisasterEventResponse): HazardEvent => ({
    id: String(ev.id),
    habitation_id: '',
    habitation_name: ev.name,
    hazard_type: ev.hazard_type as HazardEvent['hazard_type'],
    event_date: ev.event_date,
    intensity: ev.severity_level ?? 'Unknown',
    severity_level: (ev.severity_level as HazardEvent['severity_level']) ?? 'Medium',
    affected_people: ev.affected_population ?? 0,
    houses_damaged: 0,
    deaths: ev.fatalities ?? 0,
    source_url: ev.source_reference || ev.source || '',
  });

  // RESOLVE region selection → map viewport (offline-first + geocode fallback).
  // Re-resolves only when the region actually changes or the habitation dataset
  // loads/refreshes — not on incidental data refreshes (priority recalc, etc.)
  // so the map never re-flies behind the user.
  const lastRegionResolveKeyRef = useRef('');
  useEffect(() => {
    const region = selectedRegion ?? EMPTY_REGION;
    const signature = JSON.stringify({
      s: region.state?.code ?? null,
      d: region.district?.code ?? null,
      sd: region.subDistrict?.code ?? null,
      p: region.place ?? null,
    });
    const resolveKey = `${signature}|${habitations.length}`;
    if (resolveKey === lastRegionResolveKeyRef.current) return;
    lastRegionResolveKeyRef.current = resolveKey;

    let cancelled = false;
    resolveRegionViewport(region, habitations)
      .then((viewport) => {
        if (cancelled || !viewport) return;
        regionFocusKeyRef.current += 1;
        setRegionFocus({ ...viewport, key: String(regionFocusKeyRef.current) });
      })
      .catch(() => {
        /* leave map unchanged if resolution fails */
      });
    return () => {
      cancelled = true;
    };
  }, [selectedRegion, habitations]);

  // HISTORICAL rainfall baseline: re-fetch whenever the user picks a
  // Kerala district on the dashboard card or the GIS panel.
  useEffect(() => {
    let cancelled = false;
    if (historicalDistrictId == null) {
      setHistoricalBaseline(null);
      return;
    }
    apiService
      .getHistoricalDistrictBaseline(historicalDistrictId)
      .then((baseline) => {
        if (!cancelled) setHistoricalBaseline(baseline);
      })
      .catch(() => {
        if (!cancelled) setHistoricalBaseline(null);
      });
    return () => {
      cancelled = true;
    };
  }, [historicalDistrictId]);

  const handleHistoricalDistrictChange = (districtId: number) => {
    setHistoricalDistrictId(districtId);
  };

  // Location-driven loader: every layer reloads for the resolved region
  // (state → district → village). National overview shows only the nationwide
  // disaster map; curated Chamoli seed stays SIMULATED for the pilot scope and
  // honestly UNAVAILABLE everywhere else.
  const fetchRegionData = async (region: RegionSelection | null) => {
    setLoading(true);
    setLoadError(null);
    const fetchSeq = ++regionFetchSeqRef.current;
    const isStale = () => fetchSeq !== regionFetchSeqRef.current;
    const deadlineTimer = setTimeout(() => {
      if (fetchSeq === regionFetchSeqRef.current) {
        setLoadError('Some data services are unreachable — showing what could be loaded.');
        setLoading(false);
      }
    }, REGION_LOADING_DEADLINE_MS);
    try {
      const stateName = region?.state?.name ?? undefined;
      const districtName = region?.district?.name ?? undefined;
      const national = !region?.state;
      const pilot = hasSelectedRegion(region) ? isCuratedRegion(region) : false;

      let viewport: RegionViewportFocus | null = null;
      try {
        viewport = await resolveRegionViewport(region ?? EMPTY_REGION, habitations);
      } catch {
        viewport = null;
      }
      const boundsStr = viewport?.bounds ? [...viewport.bounds].join(',') : undefined;

      const [
        sumData,
        habResult,
        sitesData,
        landLayers,
        reportsData,
        recsData,
        hazardList,
        eventsData,
        floodData,
        statusData,
        histAvail,
        histSummaries,
        alertsData,
      ] = await Promise.all([
        national ? Promise.resolve(null) : apiService.getDashboardSummary(stateName, districtName),
        apiService.getHabitations({
          state: stateName,
          district: districtName,
          lat: viewport?.lat,
          lng: viewport?.lng,
          radius: 25,
        }),
        apiService.getRelocationSites(stateName, districtName),
        apiService.getMapLayers(stateName, districtName).catch(() => null),
        pilot ? apiService.getFieldReports() : Promise.resolve([]),
        pilot ? apiService.getRecommendations() : Promise.resolve([]),
        apiService.getHazardEvents(stateName, districtName),
        apiService.getDisasterEvents(
          national ? {} : { state: stateName, district: districtName }
        ),
        national ? Promise.resolve(null) : apiService.getFloodForecast(stateName, districtName).catch(() => null),
        apiService.getDataStatus().catch(() => null),
        apiService.getHistoricalAvailability().catch(() => null),
        apiService.getHistoricalKeralaSummaries().catch(() => []),
        apiService.getRiskAlerts().catch(() => []),
      ]);

      let riskZonesData: RiskZone[] = [];
      let rainfallGridData: RainfallGridPoint[] = [];
      if (!national && boundsStr) {
        const [rz, gg] = await Promise.all([
          apiService
            .getRiskZones({ granularity: 'habitations', maxPoints: 80, state: stateName, district: districtName })
            .then((r) => r.zones ?? [])
            .catch(() => []),
          apiService
            .getRainfallMap(boundsStr, 400)
            .then((g) => g.points ?? [])
            .catch(() => []),
        ]);
        riskZonesData = rz;
        rainfallGridData = gg;
      }

      setSummary(sumData);
      setHabitations(habResult.habitations);
      setHabitationsMeta({
        data_status: habResult.data_status,
        data_source: habResult.data_source,
        count: habResult.count,
        reason: habResult.reason ?? null,
      });
      setRelocationSites(sitesData && sitesData.length ? sitesData : landLayers?.relocation_sites ?? []);
      setRedZones(landLayers?.red_zones ?? []);
      setInfrastructure(landLayers?.infrastructure ?? []);
      setFieldReports(reportsData);
      setRecommendations(recsData);
      setHazardEvents(hazardList);
      setDisasterEvents(eventsData.events ?? []);
      setFloodForecast(floodData);
      setDataStatus(statusData?.layers ?? null);
      setHistoricalAvailability(histAvail);
      setHistoricalSummaries(histSummaries);
      setRiskZones(riskZonesData);
      setRainfallGrid(rainfallGridData);
      setRiskAlerts(alertsData);
      if (!isStale()) {
        setDataLastUpdated(new Date());
      }
    } catch (err) {
      console.error('Error loading region data:', err);
      if (fetchSeq === regionFetchSeqRef.current) {
        setLoadError('Some data services failed to respond — showing what could be loaded.');
      }
    } finally {
      clearTimeout(deadlineTimer);
      if (fetchSeq === regionFetchSeqRef.current) {
        setLoading(false);
      }
    }
  };

  // Cross-module actions
  const handleLaunchSimulation = (habId: string, siteId?: string) => {
    setSimulatorHabId(habId);
    if (siteId) {
      setSimulatorSiteId(siteId);
    }
    setActiveTab('simulator');
  };

  const handleOpenEvacuation = (origin?: EvacuationOriginPayload | Habitation) => {
    if (origin && 'village_name' in origin) {
      setEvacuationOrigin({
        type: 'habitation',
        id: origin.id,
        label: origin.village_name,
        lat: origin.latitude,
        lng: origin.longitude,
      });
    } else if (origin) {
      setEvacuationOrigin(origin);
    } else {
      setEvacuationOrigin(null);
    }
    setActiveTab('evacuation');
  };

  // Explicit map actions (View on Map / Locate Alert / Show Route) focus the map
  // without changing the geographic context. `switchToMap` additionally opens the
  // GIS map tab so the focused location is actually visible.
  const handleExplicitFocus = (focus: RegionViewportFocus, switchToMap = false) => {
    explicitFocusKeyRef.current += 1;
    setExplicitMapFocus({ ...focus, key: `explicit-${explicitFocusKeyRef.current}` });
    if (switchToMap) setActiveTab('map');
  };

  const handleRegionChange = (region: RegionSelection) => {
    setSelectedRegion(region);
    setExplicitMapFocus(null);
    fetchRegionData(region);
  };

  const handleSwitchUser = (user: User) => {
    setCurrentUser(user);
    setEvacuationOrigin(null);
  };

  const handleEnterPortal = (user: User) => {
    setCurrentUser(user);
  };

  const handleSignOut = () => {
    setCurrentUser(null);
  };

  const handleResetData = async () => {
    await apiService.resetSeedData();
    await fetchRegionData(selectedRegion);
  };

  const handleSubmitReport = async (reportData: Partial<FieldReport>) => {
    const created = await apiService.submitFieldReport(reportData);
    setFieldReports((prev) => [created, ...prev]);
    // A fresh field report can change susceptibility at its location: re-run the
    // AI assessment there, then refresh the shared risk-zone layer (best-effort).
    if (typeof created.latitude === 'number' && typeof created.longitude === 'number') {
      apiService
        .recalculateRisk({ latitude: created.latitude, longitude: created.longitude })
        .catch(() => undefined)
        .finally(() => {
          apiService
            .getRiskZones({
              granularity: 'habitations',
              maxPoints: 80,
              state: selectedRegion?.state?.name,
              district: selectedRegion?.district?.name,
            })
            .then((res) => setRiskZones(res.zones ?? []))
            .catch(() => undefined);
        });
    }
    return created;
  };

  const handleVerifyReport = async (reportId: string) => {
    const updated = await apiService.verifyFieldReport(reportId, currentUser.full_name);
    setFieldReports((prev) =>
      prev.map((r) => (r.id === reportId ? updated : r))
    );
    return updated;
  };

  const handleRecalculatePriority = async (params: any) => {
    const updatedHab = await apiService.recalculatePriority(params);
    setHabitations((prev) =>
      prev.map((h) => (h.id === updatedHab.id ? updatedHab : h))
    );
    // Refresh summary
    const newSummary = await apiService.getDashboardSummary(
      selectedRegion?.state?.name,
      selectedRegion?.district?.name
    );
    setSummary(newSummary);
    return updatedHab;
  };

  // The map viewport honors explicit focus requests first, then the region context.
  const activeFocus = explicitMapFocus ?? regionFocus;

  if (!currentUser) {
    return <AccessGate users={DEMO_USERS} onEnter={handleEnterPortal} />;
  }

  return (
    <div className="h-screen w-full flex flex-col bg-sm-bg text-sm-text overflow-hidden font-sans antialiased">
      {/* Top Navbar */}
      <Navbar
        currentUser={currentUser}
        onSwitchUser={handleSwitchUser}
        onResetData={handleResetData}
        onSignOut={handleSignOut}
        activeTab={activeTab}
        onSelectTab={(tab) => setActiveTab(tab)}
        onOpenSidebar={() => setSidebarOpen(true)}
        regionLabel={
          selectedRegion
            ? `${selectedRegion.state?.name ?? 'India'}${selectedRegion.district ? ` / ${selectedRegion.district.name}` : ''}`
            : 'India'
        }
      />

      {/* Main Workspace Layout */}
      <div className="flex-1 flex overflow-hidden">
        {/* Mobile drawer backdrop (only when sidebar open on <lg) */}
        {sidebarOpen && (
          <div
            id="mobile-sidebar-backdrop"
            className="fixed inset-0 z-40 bg-sm-bg/70 backdrop-blur-sm lg:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}

        {/* Left Sidebar */}
        <Sidebar
          activeTab={activeTab}
          onSelectTab={(tab) => {
            setActiveTab(tab);
            setSidebarOpen(false);
          }}
          userRole={currentUser.role}
          region={selectedRegion ?? EMPTY_REGION}
          onRegionChange={handleRegionChange}
          open={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
        />

        {/* Content Viewport */}
        <main
          id="main-app-content-viewport"
          className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8 bg-sm-bg flex flex-col gap-6"
        >
          {!loading && loadError && (
            <div
              data-load-error-banner
              className="flex items-start gap-2 text-sm px-4 py-2.5 rounded-lg border border-sm-warning/40 bg-sm-warning/10 text-amber-200 animate-in fade-in"
            >
              <span className="font-semibold">Data services degraded:</span>
              <span>{loadError}</span>
            </div>
          )}
          {loading ? (
            <div className="flex flex-col items-center justify-center h-80 space-y-3">
              <div className="w-10 h-10 border-4 border-sm-panel-2 border-t-sm-green rounded-full animate-spin" />
              <SafeMoveLogo variant="compact" />
              <p className="text-sm font-semibold text-sm-muted">
                {selectedRegion
                  ? `Loading hazard data for ${selectedRegion.state?.name ?? 'India'}...`
                  : 'Loading India-wide hazard data...'}
              </p>
            </div>
          ) : (
            <>
              {activeTab === 'dashboard' && (
                <DashboardPage
                  summary={summary}
                  habitations={habitations}
                  relocationSites={relocationSites}
                  redZones={redZones}
                  infrastructure={infrastructure}
                  fieldReports={fieldReports}
                  disasterEvents={disasterEvents}
                  riskZones={riskZones}
                  rainfallGrid={rainfallGrid}
                  floodForecast={floodForecast}
                  dataStatus={dataStatus}
                  bhuvanRoute={bhuvanRoute}
                  riskAlerts={riskAlerts}
                  habitationsMeta={habitationsMeta}
                  focusRegion={activeFocus}
                  region={selectedRegion ?? EMPTY_REGION}
                  loading={loading}
                  dataLastUpdated={dataLastUpdated}
                  onRefresh={() => fetchRegionData(selectedRegion)}
                  onRegionChange={handleRegionChange}
                  onSelectHabitation={(hab) => setModalHabitation(hab)}
                  onSelectSite={(site) => setModalSite(site)}
                  onNavigateTab={(tab) => setActiveTab(tab)}
                  onOpenEvacuation={(hab) => handleOpenEvacuation(hab)}
                  onLocateOnMap={(focus) => handleExplicitFocus(focus)}
                  onBhuvanRouteLoaded={setBhuvanRoute}
                  historicalAvailability={historicalAvailability}
                  historicalSummaries={historicalSummaries}
                  historicalBaseline={historicalBaseline}
                  historicalDistrictId={historicalDistrictId}
                  onHistoricalDistrictChange={handleHistoricalDistrictChange}
                  regionLabel={
                    selectedRegion
                      ? `${selectedRegion.state?.name ?? 'India'}${selectedRegion.district ? ` / ${selectedRegion.district.name}` : ''}`
                      : 'India'
                  }
                />
              )}

              {activeTab === 'map' && (
                <GisMapPage
                  habitations={habitations}
                  relocationSites={relocationSites}
                  redZones={redZones}
                  infrastructure={infrastructure}
                  fieldReports={fieldReports}
                  disasterEvents={disasterEvents}
                  regionLabel={selectedRegion ? `${selectedRegion.state?.name ?? ''}${selectedRegion.district ? ` / ${selectedRegion.district.name}` : ''}` : 'India'}
                  onSelectHabitation={(hab) => setModalHabitation(hab)}
                  onSelectSite={(site) => setModalSite(site)}
                  focusRegion={activeFocus}
                  onOpenEvacuation={(hab) => handleOpenEvacuation(hab)}
                  floodForecast={floodForecast}
                  dataStatus={dataStatus}
                  habitationsMeta={habitationsMeta}
                  historicalBaseline={historicalBaseline}
                  historicalSummaries={historicalSummaries}
                  historicalAvailability={historicalAvailability}
                  historicalDistrictId={historicalDistrictId}
                  onHistoricalDistrictChange={handleHistoricalDistrictChange}
                  riskZones={riskZones}
                  rainfallGrid={rainfallGrid}
                  bhuvanRoute={bhuvanRoute}
                />
              )}

              {activeTab === 'weather' && (
                <WeatherForecastMapPage
                  key={`weather-${activeFocus?.key ?? 'national'}`}
                  focus={activeFocus}
                  dataStatus={dataStatus}
                  regionLabel={selectedRegion?.state?.name ?? 'All of India'}
                  userRole={currentUser?.role ?? 'admin'}
                />
              )}

              {activeTab === 'risk_intelligence' && (
                <RiskIntelligencePage
                  key={`risk-intel-${activeFocus?.key ?? 'national'}`}
                  habitations={habitations}
                  riskZones={riskZones}
                  isCitizen={currentUser?.role === 'normal_citizen'}
                  anchor={
                    activeFocus
                      ? { lat: activeFocus.lat, lng: activeFocus.lng, label: activeFocus.label }
                      : undefined
                  }
                  onLocateOnMap={(focus) => handleExplicitFocus(focus, true)}
                  onRiskZonesLoaded={setRiskZones}
                  onBhuvanRouteLoaded={setBhuvanRoute}
                />
              )}
                {activeTab === 'alerts' && (
                <RiskAlertsPage
                  redZones={redZones}
                  events={
                    isCuratedRegion(selectedRegion)
                      ? hazardEvents
                      : disasterEvents.map((ev) => toAlertEvent(ev))
                  }
                  habitations={habitations}
                  onLocateOnMap={(focus) => handleExplicitFocus(focus, true)}
                />
              )}

              {activeTab === 'habitations' && (
                <HabitationsPage
                  habitations={habitations}
                  onSelectHabitation={(hab) => setModalHabitation(hab)}
                  onSimulateHabitation={(habId) => handleLaunchSimulation(habId)}
                  onPlanEvacuation={(hab) => handleOpenEvacuation(hab)}
                />
              )}

              {activeTab === 'priority' && (
                <PriorityPage
                  habitations={habitations}
                  recommendations={recommendations}
                  onSelectHabitation={(hab) => setModalHabitation(hab)}
                  onSimulate={(habId, siteId) => handleLaunchSimulation(habId, siteId)}
                  onPlanEvacuation={(hab) => handleOpenEvacuation(hab)}
                  onRecalculatePriority={handleRecalculatePriority}
                />
              )}

              {activeTab === 'simulator' && (
                <SimulatorPage
                  habitations={habitations}
                  relocationSites={relocationSites}
                  initialHabitationId={simulatorHabId}
                  initialSiteId={simulatorSiteId}
                  onSimulate={(habId, siteId, fams) =>
                    apiService.simulateRelocation(habId, siteId, fams)
                  }
                  onPlanEvacuation={(hab) => handleOpenEvacuation(hab)}
                  onViewOnMap={(focus) => handleExplicitFocus(focus, true)}
                />
              )}

              {activeTab === 'evacuation' && (
                <EvacuationPlanPage
                  habitations={habitations}
                  hazardEvents={hazardEvents}
                  relocationSites={relocationSites}
                  redZones={redZones}
                  infrastructure={infrastructure}
                  initialOrigin={evacuationOrigin}
                  focus={activeFocus}
                  onViewRouteOnMap={(focus) => handleExplicitFocus(focus, false)}
                />
              )}

              {activeTab === 'field_reports' && (
                <FieldReportsPage
                  reports={fieldReports}
                  habitations={habitations}
                  currentUser={currentUser}
                  onSubmitReport={handleSubmitReport}
                  onVerifyReport={handleVerifyReport}
                  onSelectHabitation={(hab) => setModalHabitation(hab)}
                  onViewOnMap={(focus) => handleExplicitFocus(focus, true)}
                />
              )}

              {activeTab === 'directive' && (
                <ReportsPage
                  habitations={habitations}
                  relocationSites={relocationSites}
                  recommendations={recommendations}
                />
              )}

              {activeTab === 'admin' && (
                <AdminPage
                  currentUser={currentUser}
                  onSwitchUser={handleSwitchUser}
                  onResetSeedData={handleResetData}
                />
              )}

              {activeTab === 'docs' && <DocsPage />}
            </>
          )}
        </main>
      </div>

      {/* Professional Polish Standard Footer */}
      <footer className="h-8 bg-sm-panel border-t border-sm-border px-6 flex items-center justify-between text-[10px] text-sm-muted font-medium shrink-0">
        <div>&copy; 2026 SafeMove AI &mdash; Government of India Disaster Management</div>
        <div className="flex items-center gap-4">
          <span className="hidden sm:inline">v1.1.0 (SafeMove AI)</span>
          <div className="flex items-center gap-1.5">
            <div className="w-2 h-2 rounded-full bg-sm-green" />
            <span className="text-sm-muted font-semibold">System Operational</span>
          </div>
        </div>
      </footer>

      {/* Village Deep Risk Inspection Modal */}
      {modalHabitation && (
        <VillageModal
          habitation={modalHabitation}
          historicalEvents={hazardEvents.filter(
            (e) => e.habitation_id === modalHabitation.id
          )}
          recommendation={recommendations.find(
            (r) => r.habitation_id === modalHabitation.id
          )}
          onClose={() => setModalHabitation(null)}
          onSimulate={(habId) => handleLaunchSimulation(habId)}
          onPlanEvacuation={(hab) => handleOpenEvacuation(hab)}
        />
      )}

      {/* Relocation Site Carrying Capacity Inspection Modal */}
      {modalSite && (
        <SiteModal
          site={modalSite}
          onClose={() => setModalSite(null)}
          onSimulate={(siteId) => {
            setSimulatorSiteId(siteId);
            setActiveTab('simulator');
          }}
        />
      )}
    </div>
  );
}
