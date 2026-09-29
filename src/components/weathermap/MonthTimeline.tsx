import React from 'react';
import { CalendarRange } from 'lucide-react';
import { MONTHS_SHORT } from '../../lib/historicalDates';

interface MonthTimelineProps {
  year: number;
  /** Number of completed months for the selected year (1-12). */
  completed: number;
  selected: number;
  onSelect: (month: number) => void;
}

/** Jan–Dec month timeline for the historical ERA5 archive. Months beyond the
 *  completed window are disabled (and the current year shows an honest
 *  caption handled by the caller). */
export const MonthTimeline: React.FC<MonthTimelineProps> = ({
  year,
  completed,
  selected,
  onSelect,
}) => {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="bg-amber-950/50 border border-amber-600/40 rounded-lg px-1.5 py-0.5 text-[9px] font-bold text-amber-300 tracking-wide inline-flex items-center gap-1 shrink-0">
        <CalendarRange className="w-3 h-3" />
        {year} months
      </span>
      <div className="flex items-center gap-1 flex-wrap">
        {MONTHS_SHORT.map((label, i) => {
          const m = i + 1;
          const disabled = m > completed;
          const active = m === selected && !disabled;
          return (
            <button
              key={m}
              type="button"
              disabled={disabled}
              onClick={() => onSelect(m)}
              id={`weather-month-${m}`}
              aria-pressed={active}
              className={`tl-btn !px-2 ${disabled ? 'opacity-30 cursor-not-allowed' : ''} ${active ? 'bg-violet-700/70 border-violet-400 text-white shadow' : ''}`}
            >
              {label}
            </button>
          );
        })}
      </div>
    </div>
  );
};