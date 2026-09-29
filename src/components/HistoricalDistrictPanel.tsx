import React from 'react';
import { History, Droplets, TrendingUp, Radar } from 'lucide-react';
import {
  HistoricalAvailability,
  HistoricalBaseline,
  HistoricalDistrictSummary,
} from '../types';
import { DISTRICTS_BY_STATE } from '../data/regions/hierarchy';

const KERALA_STATE_CODE = 32;

interface HistoricalDistrictPanelProps {
  districtId: number | null;
  onDistrictChange: (districtId: number) => void;
  baseline: HistoricalBaseline | null;
  summaries: HistoricalDistrictSummary[];
  availability: HistoricalAvailability | null;
}

export const HistoricalDistrictPanel: React.FC<HistoricalDistrictPanelProps> = ({
  districtId,
  onDistrictChange,
  baseline,
  summaries,
  availability,
}) => {
  const keralaDistricts = DISTRICTS_BY_STATE[KERALA_STATE_CODE] ?? [];
  const configured = baseline?.status === 'HISTORICAL';

  const summary = summaries.find((s) => s.district_id === districtId) ?? null;

  return (
    <div
      id="historical-district-panel"
      className="absolute right-3 top-[78px] sm:right-4 sm:top-[88px] z-10 w-[calc(100%-1.5rem)] sm:w-72 bg-slate-900/90 backdrop-blur-md text-white p-3 rounded-xl border border-slate-700 shadow-xl text-[11px] space-y-2.5"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 font-bold text-slate-200">
          <History className="w-3.5 h-3.5 text-violet-400" />
          Historical Rainfall
        </span>
        <span
          className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full border ${
            configured
              ? 'bg-violet-500/20 text-violet-200 border-violet-500/40'
              : 'bg-slate-700/40 text-slate-300 border-slate-600'
          }`}
        >
          {configured ? 'HISTORICAL' : 'NOT CONFIGURED'}
        </span>
      </div>

      <select
        id="historical-district-panel-select"
        value={districtId ?? ''}
        onChange={(e) => onDistrictChange(Number(e.target.value))}
        className="w-full px-2 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-[11px] text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-500"
      >
        <option value="" disabled>
          Select a Kerala district…
        </option>
        {keralaDistricts.map((d) => (
          <option key={d.code} value={d.code}>
            {d.name}
          </option>
        ))}
      </select>

      {!configured && (
        <div
          id="historical-panel-not-configured"
          className="flex items-start gap-1.5 p-2 rounded-lg bg-slate-800/60 border border-slate-700"
        >
          <Radar className="w-3.5 h-3.5 text-slate-400 shrink-0 mt-0.5" />
          <p className="text-[10px] text-slate-400 leading-snug">
            <span className="font-bold text-slate-200">
              HISTORICAL DATA SOURCE NOT CONFIGURED.
            </span>{' '}
            No previous-year dataset imported for this district.
          </p>
        </div>
      )}

      {configured && baseline && (
        <>
          <div className="grid grid-cols-2 gap-2">
            <div className="p-2 rounded-lg bg-violet-500/10 border border-violet-500/30">
              <span className="text-[9px] uppercase font-bold text-violet-300 flex items-center gap-1">
                <Droplets className="w-3 h-3" /> Avg Daily
              </span>
              <span className="text-base font-extrabold text-white block mt-0.5">
                {baseline.average_rainfall_mm != null
                  ? `${baseline.average_rainfall_mm.toFixed(1)} mm`
                  : '—'}
              </span>
            </div>
            <div className="p-2 rounded-lg bg-slate-800/60 border border-slate-700">
              <span className="text-[9px] uppercase font-bold text-slate-400 flex items-center gap-1">
                <TrendingUp className="w-3 h-3" /> Observed
              </span>
              <span className="text-base font-extrabold text-white block mt-0.5">
                {baseline.observation_count}
              </span>
            </div>
          </div>

          <div className="text-[10px] text-slate-400 space-y-0.5">
            <p>
              Peak {baseline.max_rainfall_mm != null ? `${baseline.max_rainfall_mm.toFixed(1)} mm` : '—'} · Total{' '}
              {baseline.total_rainfall_mm != null ? `${Math.round(baseline.total_rainfall_mm)} mm` : '—'}
            </p>
            {baseline.median_rainfall_mm != null && (
              <p>
                P50 {baseline.median_rainfall_mm} · P90 {baseline.p90_rainfall_mm} · P95{' '}
                {baseline.p95_rainfall_mm}
              </p>
            )}
            <span
              className={`inline-block mt-1 px-1.5 py-0.5 rounded-full border font-bold ${
                baseline.quality.grade === 'GOOD'
                  ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/40'
                  : baseline.quality.grade === 'LIMITED'
                    ? 'bg-amber-500/10 text-amber-300 border-amber-500/40'
                    : 'bg-slate-700/40 text-slate-300 border-slate-600'
              }`}
            >
              Coverage: {baseline.quality.grade} ({baseline.quality.coverage_percent}%)
            </span>
            {baseline.source && (
              <p className="truncate pt-0.5" title={baseline.source}>
                Source: {baseline.source}
              </p>
            )}
          </div>
        </>
      )}

      {!configured && districtId && summary && (
        <p className="text-[10px] text-slate-400">
          {summary.district}: 0 records imported for the dataset year.
        </p>
      )}

      {availability && (
        <p className="text-[9px] text-slate-500 border-t border-slate-700/70 pt-1.5">
          Dataset year {availability.dataset_year} · {availability.total_records} records across{' '}
          {availability.districts.filter((d) => d.records > 0).length} Kerala districts
        </p>
      )}
    </div>
  );
};