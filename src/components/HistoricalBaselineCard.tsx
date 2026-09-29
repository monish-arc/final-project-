import React from 'react';
import { History, Droplets, Radar, TrendingUp } from 'lucide-react';
import {
  HistoricalAvailability,
  HistoricalBaseline,
  HistoricalDistrictSummary,
  HistoricalQuality,
} from '../types';
import { DISTRICTS_BY_STATE } from '../data/regions/hierarchy';

const KERALA_STATE_CODE = 32;
const NOT_CONFIGURED_MSG = 'HISTORICAL DATA SOURCE NOT CONFIGURED';

const QUALITY_STYLES: Record<HistoricalQuality['grade'], string> = {
  GOOD: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
  LIMITED: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
  INSUFFICIENT: 'bg-sm-panel-2 text-sm-muted border-sm-border',
};

interface HistoricalBaselineCardProps {
  availability: HistoricalAvailability | null;
  summaries: HistoricalDistrictSummary[];
  baseline: HistoricalBaseline | null;
  selectedDistrictId: number | null;
  onDistrictChange: (districtId: number) => void;
}

export const HistoricalBaselineCard: React.FC<HistoricalBaselineCardProps> = ({
  availability,
  summaries,
  baseline,
  selectedDistrictId,
  onDistrictChange,
}) => {
  const keralaDistricts = DISTRICTS_BY_STATE[KERALA_STATE_CODE] ?? [];
  const configured = baseline?.status === 'HISTORICAL';
  const districtName =
    keralaDistricts.find((d) => d.code === selectedDistrictId)?.name ??
    selectedDistrictId ??
    null;

  const summary =
    summaries.find((s) => s.district_id === selectedDistrictId) ?? null;

  const qualityGrade = (baseline?.quality?.grade ?? summary?.quality_grade ?? 'INSUFFICIENT') as HistoricalQuality['grade'];

  return (
    <div
      id="historical-baseline-card"
      className="bg-sm-panel rounded-xl border border-sm-border shadow-sm p-4 space-y-3"
    >
      <div className="flex items-start justify-between gap-2 flex-wrap">
        <div>
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-md bg-violet-500/10 text-violet-400 flex items-center justify-center">
              <History className="w-4 h-4" />
            </div>
            <h3 className="text-xs font-bold uppercase text-sm-text tracking-wider">
              Historical Rainfall (Previous-Year)
            </h3>
          </div>
          <p className="text-[10px] text-sm-muted mt-1">
            Kerala previous-year {baseline?.data_year ?? availability?.dataset_year ?? 2025} baseline · provenance data only
          </p>
        </div>

        <span
          className={`text-[9px] font-bold px-2 py-1 rounded-full border ${
            configured
              ? 'bg-violet-500/20 text-violet-300 border-violet-500/40'
              : 'bg-sm-panel-2 text-sm-muted border-sm-border'
          }`}
        >
          {configured ? 'HISTORICAL' : 'NOT CONFIGURED'}
        </span>
      </div>

      <label htmlFor="historical-district-select" className="sr-only">
        Historical rainfall district
      </label>
      <select
        id="historical-district-select"
        value={selectedDistrictId ?? ''}
        onChange={(e) => onDistrictChange(Number(e.target.value))}
        className="w-full px-2.5 py-2 rounded-lg bg-sm-panel-2 border border-sm-border text-xs text-sm-text focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-500"
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
          id="historical-not-configured-banner"
          className="flex items-start gap-2 p-2.5 rounded-lg bg-sm-panel-2 border border-sm-border"
        >
          <Radar className="w-3.5 h-3.5 text-sm-muted shrink-0 mt-0.5" />
          <p className="text-[10px] text-sm-muted leading-snug">
            <span className="font-bold text-sm-text">{NOT_CONFIGURED_MSG}.</span>{' '}
            No verified previous-year dataset has been imported yet. Data will
            appear here once a source-documented CSV (India-WRIS / IMD / KSDMA)
            is loaded via the import CLI.
          </p>
        </div>
      )}

      {configured && baseline && (
        <div className="grid grid-cols-2 gap-2.5">
          <div className="p-2.5 rounded-lg bg-violet-500/10 border border-violet-500/30">
            <span className="text-[9px] uppercase font-bold text-violet-300 flex items-center gap-1">
              <Droplets className="w-3 h-3" /> Avg Daily Rainfall
            </span>
            <span className="text-lg font-extrabold text-sm-text block mt-0.5">
              {baseline.average_rainfall_mm != null
                ? `${baseline.average_rainfall_mm.toFixed(1)} mm`
                : '—'}
            </span>
          </div>
          <div className="p-2.5 rounded-lg bg-sm-panel-2 border border-sm-border">
            <span className="text-[9px] uppercase font-bold text-sm-muted flex items-center gap-1">
              <TrendingUp className="w-3 h-3" /> Observed Days
            </span>
            <span className="text-lg font-extrabold text-sm-text block mt-0.5">
              {baseline.observation_count}
            </span>
          </div>
          <div className="p-2.5 rounded-lg bg-sm-panel-2 border border-sm-border">
            <span className="text-[9px] uppercase font-bold text-sm-muted">Peak (Max)</span>
            <span className="text-sm font-bold text-sm-text block mt-0.5">
              {baseline.max_rainfall_mm != null ? `${baseline.max_rainfall_mm.toFixed(1)} mm` : '—'}
            </span>
          </div>
          <div className="p-2.5 rounded-lg bg-sm-panel-2 border border-sm-border">
            <span className="text-[9px] uppercase font-bold text-sm-muted">Season Total</span>
            <span className="text-sm font-bold text-sm-text block mt-0.5">
              {baseline.total_rainfall_mm != null ? `${Math.round(baseline.total_rainfall_mm)} mm` : '—'}
            </span>
          </div>
        </div>
      )}

      {configured && baseline && (
        <div className="space-y-1.5 text-[10px] text-sm-muted">
          <span
            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border font-bold ${
              QUALITY_STYLES[qualityGrade] ?? QUALITY_STYLES.INSUFFICIENT
            }`}
          >
            Coverage: {qualityGrade} ({baseline.quality.coverage_percent}%)
          </span>
          {baseline.median_rainfall_mm != null && (
            <p>
              Median {baseline.median_rainfall_mm} mm · P90 {baseline.p90_rainfall_mm} mm · P95{' '}
              {baseline.p95_rainfall_mm} mm
            </p>
          )}
          {baseline.source && (
            <p className="truncate" title={baseline.source}>
              Source: {baseline.source}
            </p>
          )}
          {baseline.source_reference && (
            <p className="truncate text-sm-muted" title={baseline.source_reference}>
              Ref: {baseline.source_reference}
            </p>
          )}
        </div>
      )}

      {!configured && districtName && summary && (
        <div className="text-[10px] text-sm-muted">
          <span className="font-semibold text-sm-text">{districtName}:</span> 0 records imported
          for the dataset year.
        </div>
      )}
    </div>
  );
};