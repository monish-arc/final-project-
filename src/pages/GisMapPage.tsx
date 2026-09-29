import React, { useEffect, useRef, useState } from 'react';
import {
  Search,
  Layers,
  MapPin,
  Shield,
  Crosshair,
  Info,
  Maximize2,
  Route as RouteIcon,
} from 'lucide-react';
import { Habitation, RelocationSite, RedZone, MapLayerItem, FloodForecastResponse, DataStatusEntry, HistoricalAvailability, HistoricalBaseline, HistoricalDistrictSummary, FieldReport, RiskZone, RainfallGridPoint, DisasterEventResponse, BhuvanShortestPathResponse } from '../types';
import { LeafletMap } from '../components/LeafletMap';
import { RiskBadge } from '../components/RiskBadge';
import type { RegionViewportFocus } from '../lib/regionViewport';

interface GisMapPageProps {
  habitations: Habitation[];
  relocationSites: RelocationSite[];
  redZones: RedZone[];
  infrastructure: MapLayerItem[];
  fieldReports?: FieldReport[];
  disasterEvents?: DisasterEventResponse[];
  regionLabel?: string;
  habitationsMeta?: {
    data_status: string;
    data_source: string;
    count: number;
    reason: string | null;
  } | null;
  onSelectHabitation: (hab: Habitation) => void;
  onSelectSite: (site: RelocationSite) => void;
  focusRegion?: RegionViewportFocus | null;
  onOpenEvacuation?: (hab?: Habitation) => void;
  floodForecast?: FloodForecastResponse | null;
  dataStatus?: DataStatusEntry[] | null;
  historicalBaseline?: HistoricalBaseline | null;
  historicalSummaries?: HistoricalDistrictSummary[];
  historicalAvailability?: HistoricalAvailability | null;
  historicalDistrictId?: number | null;
  onHistoricalDistrictChange?: (districtId: number) => void;
  riskZones?: RiskZone[];
  rainfallGrid?: RainfallGridPoint[];
  bhuvanRoute?: BhuvanShortestPathResponse | null;
}

export const GisMapPage: React.FC<GisMapPageProps> = ({
  habitations,
  relocationSites,
  redZones,
  infrastructure,
  fieldReports = [],
  disasterEvents = [],
  regionLabel = 'India',
  habitationsMeta = null,
  onSelectHabitation,
  onSelectSite,
  focusRegion,
  onOpenEvacuation,
  floodForecast = null,
  dataStatus = null,
  historicalBaseline = null,
  historicalSummaries = [],
  historicalAvailability = null,
  historicalDistrictId = null,
  onHistoricalDistrictChange = () => {},
  riskZones = [],
  rainfallGrid = [],
  bhuvanRoute = null,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedHabId, setSelectedHabId] = useState<string | undefined>(undefined);
  const [selectedSiteId, setSelectedSiteId] = useState<string | undefined>(undefined);
  const highlightedHabRef = useRef<string | undefined>(undefined);

  // Highlight the habitation resolved from the region quick-select (center-only, no modal).
  useEffect(() => {
    const id = focusRegion?.habitationId;
    if (id && id !== highlightedHabRef.current) {
      highlightedHabRef.current = id;
      setSelectedHabId(id);
    }
  }, [focusRegion]);

  const hasPilotHotspots = habitations.some((h) => h.id === 'hab-joshimath');

  const filteredHabitations = habitations.filter(
    (h) =>
      h.village_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      h.village_code.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div id="gis-map-view" className="space-y-4 animate-in fade-in duration-200">
      {/* Top Controls Bar */}
      <div className="bg-sm-panel p-4 rounded-xl border border-sm-border shadow-sm flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3 flex-1 min-w-0">
          <div className="relative flex-1 max-w-md">
            <Search className="w-4 h-4 text-sm-muted absolute left-3 top-2.5" />
            <input
              id="gis-village-search-input"
              type="text"
              placeholder="Search villages near the selected region..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-3 py-2 rounded-lg bg-sm-panel-2 border border-sm-border text-xs text-sm-text placeholder-sm-muted focus:bg-sm-panel-2 focus:outline-none focus:ring-2 focus:ring-sm-green/40 focus:border-sm-green transition"
            />
          </div>

          {hasPilotHotspots && (
          <div className="hidden sm:flex items-center gap-2">
            <span className="text-xs text-sm-muted font-semibold uppercase text-[10px]">Hotspots:</span>
            <button
              onClick={() => {
                const j = habitations.find((h) => h.id === 'hab-joshimath');
                if (j) {
                  setSelectedHabId(j.id);
                  onSelectHabitation(j);
                }
              }}
              className="px-2.5 py-1 rounded-md bg-red-500/10 hover:bg-red-500/20 text-red-300 border border-red-500/30 text-[11px] font-bold transition cursor-pointer"
            >
              Joshimath (86.8)
            </button>
            <button
              onClick={() => {
                const r = habitations.find((h) => h.id === 'hab-raini');
                if (r) {
                  setSelectedHabId(r.id);
                  onSelectHabitation(r);
                }
              }}
              className="px-2.5 py-1 rounded-md bg-orange-500/10 hover:bg-orange-500/20 text-orange-300 border border-orange-500/30 text-[11px] font-bold transition cursor-pointer"
            >
              Raini Gorge (87.2)
            </button>
            <button
              onClick={() => {
                const g = relocationSites.find((s) => s.id === 'site-gauchar-01');
                if (g) {
                  setSelectedSiteId(g.id);
                  onSelectSite(g);
                }
              }}
              className="px-2.5 py-1 rounded-md bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 text-[11px] font-bold transition cursor-pointer"
            >
              Gauchar Safe Site
            </button>
          </div>
          )}
        </div>

        <div className="flex items-center gap-2 text-xs text-sm-muted">
          {onOpenEvacuation && (
            <button
              id="map-plan-evacuation-btn"
              onClick={() => {
                const hab = habitations.find((h) => h.id === selectedHabId);
                onOpenEvacuation(hab ? hab : undefined);
              }}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-[11px] transition cursor-pointer"
            >
              <RouteIcon className="w-3.5 h-3.5" />
              Plan evacuation
            </button>
          )}
          <span className="inline-flex items-center gap-1.5 bg-sm-panel-2 px-2.5 py-1 rounded-lg font-medium text-[11px]">
            <span className="w-2 h-2 rounded-full bg-red-500" /> {habitations.length} Habitations
          </span>
          <span className="inline-flex items-center gap-1.5 bg-sm-panel-2 px-2.5 py-1 rounded-lg font-medium text-[11px]">
            <span className="w-2 h-2 rounded bg-emerald-600" /> {relocationSites.length} Safe Enclaves
          </span>
          <span className="inline-flex items-center gap-1.5 bg-sm-panel-2 px-2.5 py-1 rounded-lg font-medium text-[11px]">
            <span className="w-2 h-2 rounded bg-red-400" /> {redZones.length} Red Zones
          </span>
        </div>
      </div>

      {/* Main Map Container */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        {/* Left Side: Habitations Quick List */}
        <div className="bg-sm-panel rounded-xl border border-sm-border shadow-sm p-4 flex flex-col h-[40vh] lg:h-[650px] order-2 lg:order-1 overflow-hidden">
          <div className="flex items-center justify-between pb-3 border-b border-sm-border">
            <div>
              <h3 className="text-xs font-bold text-sm-text uppercase tracking-wider">
                {regionLabel} Habitations ({filteredHabitations.length})
              </h3>
              <p className="text-[10px] text-sm-muted">
                {habitationsMeta?.data_source ?? 'Click marker or card to inspect'}
              </p>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto space-y-2 mt-3 pr-1">
            {filteredHabitations.length === 0 && (
              <p className="text-[11px] text-sm-muted p-2">
                {searchQuery
                  ? 'No villages match that search.'
                  : 'No curated habitations for this region — select a state/district to load live village data around it.'}
              </p>
            )}
            {filteredHabitations.map((hab) => (
              <div
                key={hab.id}
                id={`map-hab-item-${hab.id}`}
                onClick={() => {
                  setSelectedHabId(hab.id);
                  onSelectHabitation(hab);
                }}
                className={`p-3 rounded-lg border text-xs cursor-pointer transition ${
                  selectedHabId === hab.id
                    ? 'border-l-4 border-l-sm-green bg-sm-green/10 border-sm-border ring-1 ring-sm-green/30'
                    : 'border-l-4 border-l-transparent bg-sm-panel-2 hover:bg-sm-panel-2/80 border-sm-border'
                }`}
              >
                <div className="flex items-start justify-between gap-1 mb-1">
                  <span className="font-bold text-sm-text line-clamp-1">
                    {hab.village_name}
                  </span>
                  <span className="text-[10px] font-extrabold text-sm-text bg-sm-panel-2 px-1.5 py-0.5 rounded border border-sm-border">
                    {hab.priority_score}
                  </span>
                </div>
                <div className="flex items-center justify-between text-[11px] text-sm-muted">
                  <span>Pop: {hab.population.toLocaleString()}</span>
                  <RiskBadge level={hab.priority_level} size="sm" showDot={false} />
                </div>
              </div>
            ))}
          </div>

          {/* Safe Sites Section */}
          <div className="pt-3 border-t border-sm-border">
            <h4 className="text-[11px] font-bold text-sm-muted uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <Shield className="w-3.5 h-3.5 text-emerald-400" /> Designated Safe Sites ({relocationSites.length})
            </h4>
            <div className="space-y-1.5">
              {relocationSites.map((site) => (
                <div
                  key={site.id}
                  id={`map-site-item-${site.id}`}
                  onClick={() => {
                    setSelectedSiteId(site.id);
                    onSelectSite(site);
                  }}
                  className={`p-2 rounded border text-xs cursor-pointer flex items-center justify-between transition ${
                    selectedSiteId === site.id
                      ? 'bg-emerald-500/10 border-emerald-500/40 ring-1 ring-emerald-500/40'
                      : 'bg-sm-panel-2 hover:bg-sm-panel-2/80 border-sm-border'
                  }`}
                >
                  <span className="font-medium text-sm-text truncate max-w-[150px]">
                    {site.site_name}
                  </span>
                  <span className="text-[10px] text-emerald-400 font-bold">
                    {site.available_capacity_families} slots
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right Side: Leaflet Interactive Map */}
        <div className="lg:col-span-3 h-[60vh] min-h-[420px] lg:h-[650px] order-1 lg:order-2">
          <LeafletMap
            habitations={habitations}
            relocationSites={relocationSites}
            redZones={redZones}
            infrastructure={infrastructure}
            fieldReports={fieldReports}
            selectedHabitationId={selectedHabId}
            selectedSiteId={selectedSiteId}
            focus={focusRegion ?? null}
            onSelectHabitation={(hab) => {
              setSelectedHabId(hab.id);
              onSelectHabitation(hab);
            }}
            onSelectSite={(site) => {
              setSelectedSiteId(site.id);
              onSelectSite(site);
            }}
            floodForecast={floodForecast}
            dataStatus={dataStatus}
            historicalBaseline={historicalBaseline}
            historicalSummaries={historicalSummaries}
            historicalAvailability={historicalAvailability}
            historicalDistrictId={historicalDistrictId}
            onHistoricalDistrictChange={onHistoricalDistrictChange}
            riskZones={riskZones}
            rainfallGrid={rainfallGrid}
            disasterEvents={disasterEvents}
            bhuvanRoute={bhuvanRoute}
          />
        </div>
      </div>
    </div>
  );
};