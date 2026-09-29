import React from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { daysInMonth, fmtDateLabel } from '../../lib/historicalDates';

export type DayMode = 'monthly' | 'daily';

interface DateControlProps {
  mode: DayMode;
  year: number;
  month: number;
  day: number;
  onModeChange: (mode: DayMode) => void;
  onDayChange: (day: number) => void;
}

/** Historical date control: Monthly/Daily readout toggle plus a day picker
 *  (chevrons + native date input) bounded to the selected archived month.
 *  In Daily mode the choice also drives the map raster — the grid request
 *  carries that day (real archived values, never fabricated). */
export const DateControl: React.FC<DateControlProps> = ({
  mode,
  year,
  month,
  day,
  onModeChange,
  onDayChange,
}) => {
  const last = daysInMonth(year, month);
  const clDay = Math.max(1, Math.min(day, last));
  const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(clDay).padStart(2, '0')}`;
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-[9px] font-bold uppercase tracking-wider text-slate-500 w-9 shrink-0">Date</span>
      <div className="flex items-center gap-0.5 rounded-lg border border-slate-700 bg-slate-900/70 p-0.5" id="weather-res-scale">
        {(['monthly', 'daily'] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => onModeChange(m)}
            aria-pressed={mode === m}
            className={`text-[9px] font-bold px-2 py-0.5 rounded-md transition-colors ${
              mode === m ? 'bg-sky-600 text-white' : 'text-slate-400 hover:text-white'
            }`}
          >
            {m === 'monthly' ? 'Monthly' : 'Daily'}
          </button>
        ))}
      </div>
      {mode === 'daily' && (
        <div className="flex items-center gap-1 flex-wrap">
          <button
            type="button"
            onClick={() => onDayChange(Math.max(1, clDay - 1))}
            disabled={clDay <= 1}
            className={`tl-btn ${clDay <= 1 ? 'opacity-30 cursor-not-allowed' : ''}`}
            title="Previous day"
            aria-label="Previous day"
          >
            <ChevronLeft className="w-3 h-3" />
          </button>
          <input
            id="weather-historical-date"
            type="date"
            value={dateStr}
            min={`${year}-${String(month).padStart(2, '0')}-01`}
            max={`${year}-${String(month).padStart(2, '0')}-${String(last).padStart(2, '0')}`}
            onChange={(e) => {
              if (!e.target.value) return;
              const dd = new Date(`${e.target.value}T00:00:00`).getDate();
              if (!Number.isNaN(dd)) onDayChange(dd);
            }}
            aria-label="Historical day"
            className="bg-transparent text-[11px] font-bold text-sky-300 outline-none border border-slate-700 rounded-lg px-2 py-0.5 [color-scheme:dark]"
          />
          <button
            type="button"
            onClick={() => onDayChange(Math.min(last, clDay + 1))}
            disabled={clDay >= last}
            className={`tl-btn ${clDay >= last ? 'opacity-30 cursor-not-allowed' : ''}`}
            title="Next day"
            aria-label="Next day"
          >
            <ChevronRight className="w-3 h-3" />
          </button>
          <span className="text-[11px] font-bold text-sky-300 whitespace-nowrap" id="weather-historical-day-label">
            {fmtDateLabel(year, month, clDay)}
          </span>
        </div>
      )}
    </div>
  );
};