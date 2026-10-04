import React, { useState } from 'react';
import { Database, ChevronUp, ChevronDown } from 'lucide-react';
import { DataStatusEntry, DataLayerStatus } from '../types';

const STATUS_DOT: Record<string, { cls: string; chip: string; label: string }> = {
  LIVE: { cls: 'bg-emerald-400', chip: 'bg-emerald-400/20', label: 'Live' },
  MODEL: { cls: 'bg-teal-400', chip: 'bg-teal-400/20', label: 'Model' },
  CALCULATED: { cls: 'bg-indigo-400', chip: 'bg-indigo-400/20', label: 'Calculated' },
  STATIC: { cls: 'bg-violet-400', chip: 'bg-violet-400/20', label: 'Static' },
  FORECAST: { cls: 'bg-sky-400', chip: 'bg-sky-400/20', label: 'Forecast' },
  CACHED: { cls: 'bg-cyan-400', chip: 'bg-cyan-400/20', label: 'Cached' },
  DEMO: { cls: 'bg-amber-400', chip: 'bg-amber-400/20', label: 'Demo' },
  'NOT CONFIGURED': { cls: 'bg-slate-400', chip: 'bg-slate-400/20', label: 'Not configured' },
  NOT_CONFIGURED: { cls: 'bg-slate-400', chip: 'bg-slate-400/20', label: 'Not configured' },
  'API NOT ADDED': { cls: 'bg-amber-400', chip: 'bg-amber-400/20', label: 'Not added' },
  API_NOT_ADDED: { cls: 'bg-amber-400', chip: 'bg-amber-400/20', label: 'Not added' },
  UNAVAILABLE: { cls: 'bg-red-400', chip: 'bg-red-400/20', label: 'Unavailable' },
  HISTORICAL: { cls: 'bg-violet-400', chip: 'bg-violet-400/20', label: 'Historical' },
};

const LAYER_LABELS: Record<string, string> = {
  road_network: 'Road Network',
  hazard_zones: 'Hazard Zones',
  habitation_risk: 'Habitation Risk',
  relocation_sites: 'Relocation Sites',
  flood_forecast: 'Flood Forecast',
  weather: 'Weather',
  weather_forecast: 'Weather Forecast',
  terrain: 'Terrain (NASA SRTM)',
  satellite_tiles: 'Satellite Tiles',
  road_conditions: 'Road Conditions',
  evacuation_routes: 'Evacuation Routes',
  google_map_tiles: 'Google Map Tiles',
  historical_data: 'Historical Rainfall (imported)',
  era5: 'ERA5 Reanalysis (historical)',
};

const DEFAULT_LAYERS: DataStatusEntry[] = [
  { layer: 'google_map_tiles', status: 'NOT_CONFIGURED', source: 'Google Maps API key not configured', updated_at: '—' },
  { layer: 'flood_forecast', status: 'NOT_CONFIGURED', source: 'No GloFAS dataset configured', updated_at: '—' },
  { layer: 'satellite_tiles', status: 'LIVE', source: 'Esri World Imagery (free, no key)', updated_at: '—' },
  { layer: 'historical_data', status: 'NOT_CONFIGURED', source: 'Previous-year Kerala rainfall dataset (imported) — none imported yet', updated_at: '—' },
  { layer: 'era5', status: 'HISTORICAL', source: 'Open-Meteo ERA5 Archive (ECMWF reanalysis)', updated_at: '—' },
  { layer: 'hazard_zones', status: 'MODEL', source: 'Terrain-derived slope + rainfall modelling', updated_at: '—' },
  { layer: 'road_network', status: 'LIVE', source: 'OpenStreetMap road graph (Overpass API)', updated_at: '—' },
  { layer: 'evacuation_routes', status: 'MODEL', source: 'Route optimization over live road graph', updated_at: '—' },
];

export const DataSourceStatus: React.FC<{ layers?: DataStatusEntry[] | null }> = ({ layers }) => {
  const [expanded, setExpanded] = useState(false);
  const entries = layers && layers.length > 0 ? layers : DEFAULT_LAYERS;

  const summary: Record<string, number> = {};
  for (const e of entries) {
    if (e.status === 'LIVE') continue;
    summary[e.status] = (summary[e.status] ?? 0) + 1;
  }

  const summaryCounts: Array<[string, number]> = Object.entries(summary).sort((a, b) => b[1] - a[1]);
  const summaryLabel = summaryCounts
    .map(([status, count]) => `${status.toLowerCase()}×${count}`)
    .join(' · ');

  return (
    <div
      id="gis-data-status-panel"
      className="absolute bottom-3 left-3 sm:bottom-4 sm:left-4 z-10 bg-sm-panel/95 backdrop-blur-md text-sm-text p-3 rounded-xl border border-sm-border shadow-xl text-[11px] w-[calc(100%-1.5rem)] sm:w-64"
    >
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between cursor-pointer"
      >
        <span className="flex items-center gap-1.5 font-bold text-sm-text">
          <Database className="w-3.5 h-3.5 text-sm-green" /> Data Source Status
        </span>
        {expanded ? <ChevronUp className="w-3.5 h-3.5 text-sm-muted" /> : <ChevronDown className="w-3.5 h-3.5 text-sm-muted" />}
      </button>

      <p className="text-[10px] text-amber-300/90 mt-1">{summaryLabel || 'All layers live'}</p>

      {expanded && (
        <div className="mt-2 space-y-1.5 border-t border-sm-border pt-2">
          {entries.map((entry) => {
            const dot = STATUS_DOT[entry.status] ?? STATUS_DOT['NOT_CONFIGURED'];
            return (
              <div key={entry.layer} className="space-y-0.5">
                <div className="flex items-center justify-between">
                  <span className="text-sm-muted">{LAYER_LABELS[entry.layer] ?? entry.layer.replace(/_/g, ' ')}</span>
                  <span
                    className={`inline-flex items-center gap-1 text-[9px] font-bold px-1.5 py-0.5 rounded-full ${dot.chip} text-sm-text`}
                  >
                    <span className={`w-1.5 h-1.5 rounded-full ${dot.cls} inline-block`} />
                    {dot.label}
                  </span>
                </div>
                <p className="text-[9px] text-sm-muted leading-tight">{entry.source}</p>
                {(entry.version || entry.spatial_resolution) && (
                  <p className="text-[8px] text-sm-muted/60 leading-tight">
                    {[entry.version, entry.spatial_resolution].filter(Boolean).join(' · ')}
                  </p>
                )}
                {entry.valid_time && (
                  <p className="text-[8px] text-sm-muted/60 leading-tight">valid to {entry.valid_time}</p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};