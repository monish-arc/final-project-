import React from 'react';
import { ChevronDown, RefreshCw, ShieldAlert, Clock } from 'lucide-react';
import { RegionSelection, Habitation, DataStatusEntry } from '../../types';
import { REGION_STATES, DISTRICTS_BY_STATE } from '../../data/regions/hierarchy';

interface LocationControlBarProps {
  region: RegionSelection;
  habitations: Habitation[];
  activeHabId?: string | null;
  loading: boolean;
  dataLastUpdated: Date | null;
  dataStatus: DataStatusEntry[] | null;
  onRegionChange: (region: RegionSelection) => void;
  onSelectHabitation: (hab: Habitation | null) => void;
  onRefresh: () => void;
}

const selectClass =
  'w-full sm:w-56 px-2.5 py-2 rounded-lg bg-sm-panel-2 border border-sm-border text-sm text-sm-text font-medium focus:outline-none focus:ring-2 focus:ring-sm-green/40 appearance-none cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed';

function systemHealth(dataStatus: DataStatusEntry[] | null): { label: string; live: number; unavailable: number; ok: boolean } {
  if (!dataStatus || dataStatus.length === 0) {
    return { label: 'Unknown', live: 0, unavailable: 0, ok: false };
  }
  const live = dataStatus.filter((e) =>
    ['LIVE', 'MODEL', 'CALCULATED', 'FORECAST', 'AVAILABLE', 'CACHED', 'RECENT'].includes(String(e.status))
  ).length;
  const unavailable = dataStatus.length - live;
  return {
    label: unavailable > live ? 'Degraded' : 'Operational',
    live,
    unavailable,
    ok: unavailable <= live,
  };
}

export const LocationControlBar: React.FC<LocationControlBarProps> = ({
  region,
  habitations,
  activeHabId,
  loading,
  dataLastUpdated,
  dataStatus,
  onRegionChange,
  onSelectHabitation,
  onRefresh,
}) => {
  const health = systemHealth(dataStatus);
  const stateCode = region.state?.code ?? '';
  const districtCode = region.district?.code ?? '';
  const districts = stateCode ? DISTRICTS_BY_STATE[stateCode] ?? [] : [];
  const activeHab = habitations.find((h) => h.id === activeHabId) ?? null;

  return (
    <div className="bg-sm-panel border border-sm-border rounded-xl px-4 py-3 flex flex-wrap items-center gap-x-4 gap-y-3 shadow-lg">
      {/* State ▼ */}
      <label className="flex items-center gap-2">
        <span className="text-[10px] font-bold uppercase tracking-wider text-sm-muted">State</span>
        <div className="relative">
          <select
            className={selectClass}
            value={String(stateCode)}
            onChange={(e) => {
              const code = Number(e.target.value);
              const state = REGION_STATES.find((s) => s.code === code) ?? null;
              onRegionChange({ state, district: null, subDistrict: null, place: null });
            }}
          >
            <option value="">— National —</option>
            {REGION_STATES.map((s) => (
              <option key={s.code} value={s.code}>{s.name}</option>
            ))}
          </select>
          <ChevronDown className="w-3.5 h-3.5 text-sm-muted absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
        </div>
      </label>

      {/* District ▼ */}
      <label className="flex items-center gap-2">
        <span className="text-[10px] font-bold uppercase tracking-wider text-sm-muted">District</span>
        <div className="relative">
          <select
            className={selectClass}
            value={String(districtCode)}
            disabled={!stateCode}
            onChange={(e) => {
              const code = Number(e.target.value);
              const district = districts.find((d) => d.code === code) ?? null;
              onRegionChange({ state: region.state, district, subDistrict: null, place: null });
            }}
          >
            <option value="">— Select district —</option>
            {districts.map((d) => (
              <option key={d.code} value={d.code}>{d.name}</option>
            ))}
          </select>
          <ChevronDown className="w-3.5 h-3.5 text-sm-muted absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
        </div>
      </label>

      {/* Habitation / Village ▼ (anchor point — focuses map + live cards) */}
      <label className="flex items-center gap-2">
        <span className="text-[10px] font-bold uppercase tracking-wider text-sm-muted">Habitation / Village</span>
        <div className="relative">
          <select
            className={selectClass}
            value={activeHab?.id ?? ''}
            disabled={habitations.length === 0}
            onChange={(e) => {
              const hab = habitations.find((h) => h.id === e.target.value) ?? null;
              onSelectHabitation(hab);
            }}
          >
            <option value="">
              {habitations.length ? '— select a village (anchor) —' : '— no surveyed habitations —'}
            </option>
            {[...habitations]
              .sort((a, b) => (b.priority_score ?? 0) - (a.priority_score ?? 0))
              .map((h) => (
                <option key={h.id} value={h.id}>
                  {h.village_name} ({h.priority_score ?? '—'}/100)
                </option>
              ))}
          </select>
          <ChevronDown className="w-3.5 h-3.5 text-sm-muted absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
        </div>
      </label>

      <div className="ml-auto flex items-center gap-4">
        {/* Last updated (honest — set when the batch actually resolved) */}
        <span className="inline-flex items-center gap-1.5 text-[11px] text-sm-muted">
          <Clock className="w-3.5 h-3.5" />
          Last updated:{' '}
          <b className="text-sm-text">
            {dataLastUpdated
              ? dataLastUpdated.toLocaleString(undefined, {
                  month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
                })
              : '—'}
          </b>
        </span>

        {/* System status */}
        <span
          className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold border ${
            health.ok
              ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30'
              : 'bg-amber-500/10 text-amber-300 border-amber-500/30'
          }`}
        >
          <span className={`w-2 h-2 rounded-full ${health.ok ? 'bg-emerald-400' : 'bg-amber-400'}`} />
          System {health.label}
          <span className="font-normal text-sm-muted">
            · {health.live}/{health.live + health.unavailable} sources live
          </span>
        </span>

        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-sm-green/20 border border-sm-green/30 text-sm-green text-[11px] font-bold">
          <ShieldAlert className="w-3.5 h-3.5" />
          Command Center
        </span>

        <button
          onClick={onRefresh}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-sm-green hover:bg-sm-green-hover disabled:opacity-50 disabled:cursor-not-allowed text-slate-950 text-xs font-bold transition cursor-pointer"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>
    </div>
  );
};