import React, { useState } from "react";
import {
  Layers,
  RotateCcw,
  Waves,
  Filter,
  Satellite,
  Map as MapIcon,
  Radar,
  CloudRain,
  Landmark,
  Mountain,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { BasemapKey, DataStatusEntry, DataLayerStatus } from "../types";

interface MapLayerPanelProps {
  basemap: BasemapKey["id"];
  onBasemapChange: (basemap: BasemapKey["id"]) => void;
  showRedZones: boolean;
  onRedZonesChange: (visible: boolean) => void;
  hazardTypes: string[];
  visibleHazardTypes: string[];
  onHazardTypeChange: (hazardType: string, visible: boolean) => void;
  showHabitations: boolean;
  onHabitationsChange: (visible: boolean) => void;
  showSites: boolean;
  onSitesChange: (visible: boolean) => void;
  showInfra: boolean;
  onInfraChange: (visible: boolean) => void;
  showRoute: boolean;
  onRouteChange: (visible: boolean) => void;
  showFlood: boolean;
  onFloodChange: (visible: boolean) => void;
  floodDataStatus?: DataLayerStatus;
  hasFloodData: boolean;
  showRiskZones?: boolean;
  onRiskZonesChange?: (visible: boolean) => void;
  hasRiskZones?: boolean;
  showRainfall?: boolean;
  onRainfallChange?: (visible: boolean) => void;
  hasRainfallData?: boolean;
  rainfallDataStatus?: DataLayerStatus;
  showBhuvanRoute?: boolean;
  onBhuvanRouteChange?: (visible: boolean) => void;
  hasBhuvanRoute?: boolean;
  showBhuvanOverlay?: boolean;
  onBhuvanOverlayChange?: (visible: boolean) => void;
  priorityFilter: string;
  onPriorityFilterChange: (filter: string) => void;
  onResetCenter: () => void;
  dataStatus?: DataStatusEntry[] | null;
}

const BASEMAPS: {
  id: BasemapKey["id"];
  label: string;
  icon: React.ReactNode;
}[] = [
  { id: "street", label: "Street", icon: <MapIcon className="w-3 h-3" /> },
  {
    id: "satellite",
    label: "Satellite",
    icon: <Satellite className="w-3 h-3" />,
  },
  { id: "terrain", label: "Terrain", icon: <Mountain className="w-3 h-3" /> },
];

const HAZARD_DOTS: Record<string, string> = {
  "Land Subsidence": "bg-red-500",
  "Flash Flood": "bg-sky-500",
  Landslide: "bg-orange-500",
  Cloudburst: "bg-purple-500",
};

export const MapLayerPanel: React.FC<MapLayerPanelProps> = ({
  basemap,
  onBasemapChange,
  showRedZones,
  onRedZonesChange,
  hazardTypes,
  visibleHazardTypes,
  onHazardTypeChange,
  showHabitations,
  onHabitationsChange,
  showSites,
  onSitesChange,
  showInfra,
  onInfraChange,
  showRoute,
  onRouteChange,
  showFlood,
  onFloodChange,
  floodDataStatus = "DEMO",
  hasFloodData,
  showRiskZones = false,
  onRiskZonesChange = (_: boolean) => {},
  hasRiskZones = false,
  showRainfall = false,
  onRainfallChange = (_: boolean) => {},
  hasRainfallData = false,
  rainfallDataStatus = "NOT CONFIGURED",
  showBhuvanRoute = false,
  onBhuvanRouteChange = (_: boolean) => {},
  hasBhuvanRoute = false,
  showBhuvanOverlay = false,
  onBhuvanOverlayChange = (_: boolean) => {},
  priorityFilter,
  onPriorityFilterChange,
  onResetCenter,
  dataStatus,
}) => {
  const floodDot =
    floodDataStatus === "LIVE"
      ? "bg-emerald-400"
      : floodDataStatus === "FORECAST"
        ? "bg-sky-400"
        : floodDataStatus === "DEMO"
          ? "bg-amber-400"
          : "bg-slate-400";

  const rainfallDot =
    rainfallDataStatus === "LIVE" ? "bg-emerald-400" : "bg-slate-400";

  const [collapsed, setCollapsed] = useState(false);

  return (
    <>
      {collapsed && (
        <button
          type="button"
          onClick={() => setCollapsed(false)}
          className="absolute left-3 top-3 sm:left-4 sm:top-4 z-40 flex h-10 w-10 items-center justify-center rounded-full border border-sm-border bg-sm-panel/95 text-sm-text shadow-xl backdrop-blur-md transition-colors hover:bg-white/5 focus:outline-none focus:ring-2 focus:ring-sm-green/60"
          aria-label="Expand GIS Map Layers"
          aria-expanded={false}
          aria-controls="gis-layer-control-panel"
          title="Expand GIS Map Layers"
        >
          <ChevronRight className="h-5 w-5" />
        </button>
      )}
      <div
        id="gis-layer-control-panel"
        className={`absolute left-3 top-3 sm:left-4 sm:top-4 z-30 max-w-[calc(100%-1.5rem)] sm:max-w-xs transform-gpu transition-transform duration-300 ease-in-out ${
          collapsed
            ? "-translate-x-full opacity-0 pointer-events-none"
            : "translate-x-0 opacity-100"
        }`}
      >
        <div
          className="relative flex flex-col space-y-3 rounded-xl border border-sm-border bg-sm-panel/95 p-3.5 text-xs text-sm-text shadow-xl backdrop-blur-md"
          style={{ overflow: "visible" }}
        >
          <button
            type="button"
            onClick={() => setCollapsed(true)}
            className="absolute -right-5 top-1/2 -translate-y-1/2 flex h-10 w-10 items-center justify-center rounded-full border border-sm-border bg-sm-panel/95 text-sm-text shadow-lg backdrop-blur-md transition-colors hover:bg-white/5 focus:outline-none focus:ring-2 focus:ring-sm-green/60"
            aria-label="Collapse GIS Map Layers"
            aria-expanded={true}
            aria-controls="gis-layer-control-panel"
            title="Collapse GIS Map Layers"
          >
            <ChevronLeft className="h-5 w-5" />
          </button>
          <div className="flex items-center justify-between border-b border-sm-border pb-2">
            <div className="flex items-center gap-1.5 font-bold text-sm-text">
              <Layers className="w-4 h-4 text-sm-green" />
              <span>GIS Map Layers</span>
            </div>
            <button
              onClick={onResetCenter}
              title="Reset Map to India View"
              className="p-1 rounded bg-sm-panel-2 hover:bg-white/5 text-sm-muted transition"
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Basemap switcher */}
          <div className="space-y-1.5">
            <div className="text-[10px] font-bold text-sm-muted uppercase tracking-wider">
              Basemap
            </div>
            <div className="grid grid-cols-3 gap-1">
              {BASEMAPS.map((b) => (
                <button
                  key={b.id}
                  id={`map-basemap-${b.id}`}
                  onClick={() => onBasemapChange(b.id)}
                  className={`flex items-center justify-center gap-1 px-1.5 py-1.5 rounded-md text-[10px] font-semibold border transition cursor-pointer ${
                    basemap === b.id
                      ? "bg-sm-green border-sm-green text-slate-950"
                      : "bg-sm-panel-2 border-sm-border text-sm-muted hover:bg-white/5"
                  }`}
                >
                  {b.icon}
                  {b.label}
                </button>
              ))}
            </div>
          </div>

          {/* Hazard sub-toggles */}
          <div className="space-y-1.5">
            <label className="flex items-center justify-between cursor-pointer group">
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded bg-red-500/80 border border-red-400 inline-block" />
                <span className="group-hover:text-sm-text">Hazard Zones</span>
              </div>
              <input
                type="checkbox"
                checked={showRedZones}
                onChange={(e) => onRedZonesChange(e.target.checked)}
                className="rounded accent-red-600 cursor-pointer"
              />
            </label>

            {showRedZones && (
              <div className="pl-5 space-y-1 border-l border-sm-border ml-0.5">
                {hazardTypes.map((hazardType) => {
                  const visible = visibleHazardTypes.includes(hazardType);
                  const dot = HAZARD_DOTS[hazardType] ?? "bg-red-500";
                  return (
                    <label
                      key={hazardType}
                      className="flex items-center justify-between cursor-pointer group text-[11px]"
                    >
                      <div className="flex items-center gap-1.5">
                        <span
                          className={`w-2.5 h-2.5 rounded ${dot} inline-block`}
                        />
                        <span className="group-hover:text-sm-text">
                          {hazardType}
                        </span>
                      </div>
                      <input
                        type="checkbox"
                        checked={visible}
                        onChange={(e) =>
                          onHazardTypeChange(hazardType, e.target.checked)
                        }
                        className="rounded accent-red-600 cursor-pointer"
                      />
                    </label>
                  );
                })}
              </div>
            )}
          </div>

          {/* Flood forecast toggle */}
          <label className="flex items-center justify-between cursor-pointer group">
            <div className="flex items-center gap-2">
              <Waves className="w-3.5 h-3.5 text-sky-400" />
              <span className="group-hover:text-sm-text">Flood Forecast</span>
              <span
                className={`w-2 h-2 rounded-full ${floodDot} inline-block`}
                title={floodDataStatus}
              />
            </div>
            <input
              id="map-flood-layer-toggle"
              type="checkbox"
              checked={showFlood}
              disabled={!hasFloodData}
              onChange={(e) => onFloodChange(e.target.checked)}
              className="rounded accent-sky-600 cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed"
            />
          </label>

          <label className="flex items-center justify-between cursor-pointer group">
            <div className="flex items-center gap-2">
              <Radar className="w-3.5 h-3.5 text-orange-400" />
              <span className="group-hover:text-sm-text">
                AI-Assessed Risk Zones
              </span>
            </div>
            <input
              id="map-risk-zones-layer-toggle"
              type="checkbox"
              checked={showRiskZones}
              disabled={!hasRiskZones}
              onChange={(e) => onRiskZonesChange(e.target.checked)}
              className="rounded accent-orange-600 cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed"
            />
          </label>

          <label className="flex items-center justify-between cursor-pointer group">
            <div className="flex items-center gap-2">
              <CloudRain className="w-3.5 h-3.5 text-sky-400" />
              <span className="group-hover:text-sm-text">Live Rainfall</span>
              <span
                className={`w-2 h-2 rounded-full ${rainfallDot} inline-block`}
                title={rainfallDataStatus}
              />
            </div>
            <input
              id="map-rainfall-layer-toggle"
              type="checkbox"
              checked={showRainfall}
              disabled={!hasRainfallData}
              onChange={(e) => onRainfallChange(e.target.checked)}
              className="rounded accent-sky-600 cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed"
              title="NASA GPM IMERG"
            />
          </label>

          {/* Bhuvan / ISRO supporting layer toggles */}
          <div className="space-y-1.5 pt-1 border-t border-sm-border/60">
            <div className="text-[10px] font-bold text-sm-muted uppercase tracking-wider flex items-center gap-1">
              <Satellite className="w-3 h-3 text-indigo-400" /> Bhuvan / ISRO
              (supporting)
            </div>
            <label className="flex items-center justify-between cursor-pointer group">
              <div className="flex items-center gap-2">
                <span className="inline-block h-0.5 w-4 rounded bg-violet-400 align-middle" />
                <span className="group-hover:text-sm-text">
                  Bhuvan Route Path
                </span>
              </div>
              <input
                type="checkbox"
                checked={showBhuvanRoute}
                disabled={!hasBhuvanRoute}
                onChange={(e) => onBhuvanRouteChange(e.target.checked)}
                className="rounded accent-violet-600 cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed"
                title="Intra-state shortest path from Risk Intelligence (query Bhuvan first)"
              />
            </label>
            <label className="flex items-center justify-between cursor-pointer group">
              <div className="flex items-center gap-2">
                <Landmark className="w-3.5 h-3.5 text-indigo-400" />
                <span className="group-hover:text-sm-text">
                  Thematic LULC Overlay
                </span>
              </div>
              <input
                type="checkbox"
                checked={showBhuvanOverlay}
                onChange={(e) => onBhuvanOverlayChange(e.target.checked)}
                className="rounded accent-indigo-600 cursor-pointer"
                title="Bhuvan LULC 50K WMS mosaic (ISRO) — historical land-cover, not live"
              />
            </label>
          </div>

          {/* Operations toggles */}
          <div className="space-y-2">
            <label className="flex items-center justify-between cursor-pointer group">
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-red-600 inline-block text-center text-[8px] text-white font-bold">
                  ●
                </span>
                <span className="group-hover:text-sm-text">
                  Habitations (Priority)
                </span>
              </div>
              <input
                type="checkbox"
                checked={showHabitations}
                onChange={(e) => onHabitationsChange(e.target.checked)}
                className="rounded accent-red-600 cursor-pointer"
              />
            </label>

            <label className="flex items-center justify-between cursor-pointer group">
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded bg-emerald-600 inline-block text-center text-[8px] text-white">
                  🛡️
                </span>
                <span className="group-hover:text-sm-text">
                  Safe Relocation Enclaves
                </span>
              </div>
              <input
                type="checkbox"
                checked={showSites}
                onChange={(e) => onSitesChange(e.target.checked)}
                className="rounded accent-emerald-600 cursor-pointer"
              />
            </label>

            <label className="flex items-center justify-between cursor-pointer group">
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-slate-200 inline-block text-center text-[8px]">
                  🏥
                </span>
                <span className="group-hover:text-sm-text">
                  Infrastructure & Shelters
                </span>
              </div>
              <input
                type="checkbox"
                checked={showInfra}
                onChange={(e) => onInfraChange(e.target.checked)}
                className="rounded accent-blue-600 cursor-pointer"
              />
            </label>

            <label className="flex items-center justify-between cursor-pointer group">
              <div className="flex items-center gap-2">
                <span className="inline-block h-0.5 w-4 rounded bg-emerald-400 align-middle" />
                <span className="group-hover:text-sm-text">
                  Evacuation Route & Closures
                </span>
              </div>
              <input
                type="checkbox"
                checked={showRoute}
                onChange={(e) => onRouteChange(e.target.checked)}
                className="rounded accent-emerald-600 cursor-pointer"
              />
            </label>
          </div>

          {/* Priority Filter */}
          <div className="pt-2 border-t border-sm-border space-y-1">
            <div className="flex items-center justify-between text-[11px] text-sm-muted">
              <span className="flex items-center gap-1">
                <Filter className="w-3 h-3 text-amber-400" /> Filter Villages
              </span>
            </div>
            <select
              id="map-priority-filter-select"
              value={priorityFilter}
              onChange={(e) => onPriorityFilterChange(e.target.value)}
              className="w-full bg-sm-panel-2 border border-sm-border text-sm-text rounded p-1 text-xs focus:ring-1 focus:ring-sm-green outline-none"
            >
              <option value="all">All Villages</option>
              <option value="immediate relocation">
                Immediate Relocation (75+)
              </option>
              <option value="short-term relocation">
                Short-Term Relocation (50-74)
              </option>
              <option value="medium-term relocation">
                Medium-Term Relocation (30-49)
              </option>
            </select>
          </div>

          {/* Data source summary */}
          {dataStatus && dataStatus.length > 0 && (
            <div className="pt-2 border-t border-sm-border space-y-1 text-[10px]">
              <div className="font-bold text-sm-muted uppercase tracking-wider">
                Data source
              </div>
              <div className="space-y-0.5">
                {dataStatus.slice(0, 5).map((entry) => (
                  <div
                    key={entry.layer}
                    className="flex items-center justify-between text-sm-muted"
                  >
                    <span className="capitalize">
                      {entry.layer.replace(/_/g, " ")}
                    </span>
                    <span className="font-bold text-sm-text">
                      {entry.status}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
};
