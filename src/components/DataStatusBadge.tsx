import React from 'react';
import type { DataLayerStatus } from '../types';

// Maps a backend provider status to the user-facing data-status vocabulary:
//   LIVE        →  live data stream, current
//   MODEL       →  model/algorithm-derived layer (forecast/estimate)
//   CALCULATED  →  derived terrain product (SRTM)
//   STATIC      →  curated static inventory (survey-based)
//   FORECAST    →  model forecast within the last hours (recent)
//   HISTORICAL  →  archived/previous-year records (cached)
//   AVAILABLE / CACHED / RECENT →  static/annotated datasets (cached/recent)
//   DEMO        →  clearly-labelled simulated/demo dataset
//   NOT CONFIGURED (legacy spaced) / NOT_CONFIGURED / UNAVAILABLE / ERROR /
//   LOCATION_MISMATCH →  no usable data
type DisplayLabel = 'LIVE' | 'MODEL' | 'CALCULATED' | 'STATIC' | 'RECENT' | 'CACHED' | 'SIMULATED' | 'UNAVAILABLE';

const DISPLAY_LABELS: Record<string, DisplayLabel> = {
  LIVE: 'LIVE',
  MODEL: 'MODEL',
  CALCULATED: 'CALCULATED',
  STATIC: 'STATIC',
  FORECAST: 'RECENT',
  RECENT: 'RECENT',
  HISTORICAL: 'CACHED',
  AVAILABLE: 'LIVE',
  CACHED: 'CACHED',
  DEMO: 'SIMULATED',
  SIMULATED: 'SIMULATED',
  'NOT CONFIGURED': 'UNAVAILABLE',
  NOT_CONFIGURED: 'UNAVAILABLE',
  'API NOT ADDED': 'UNAVAILABLE',
  API_NOT_ADDED: 'UNAVAILABLE',
  UNAVAILABLE: 'UNAVAILABLE',
  ERROR: 'UNAVAILABLE',
  LOCATION_MISMATCH: 'UNAVAILABLE',
};

const DOT_CLASS: Record<DisplayLabel, string> = {
  LIVE: 'bg-emerald-500',
  MODEL: 'bg-teal-400',
  CALCULATED: 'bg-indigo-400',
  STATIC: 'bg-violet-400',
  RECENT: 'bg-sky-400',
  CACHED: 'bg-violet-400',
  SIMULATED: 'bg-amber-400',
  UNAVAILABLE: 'bg-red-400',
};

interface DataStatusBadgeProps {
  status?: DataLayerStatus | string | null;
  timestamp?: string | null;
  title?: string;
  className?: string;
}

function formatTime(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export const DataStatusBadge: React.FC<DataStatusBadgeProps> = ({
  status,
  timestamp,
  title,
  className = '',
}) => {
  const key = String(status ?? 'UNAVAILABLE');
  const label: DisplayLabel = DISPLAY_LABELS[key] ?? 'UNAVAILABLE';

  return (
    <div
      className={`inline-flex flex-col items-end gap-0.5 leading-tight ${className}`}
      title={title}
    >
      <span className="inline-flex items-center gap-1 text-[10px] font-bold text-sm-text">
        <span className={`w-1.5 h-1.5 rounded-full ${DOT_CLASS[label]} inline-block`} />
        <span className="uppercase tracking-wider">{label}</span>
      </span>
      {timestamp && (
        <span className="text-[9px] text-sm-muted">Last updated: {formatTime(timestamp)}</span>
      )}
    </div>
  );
};