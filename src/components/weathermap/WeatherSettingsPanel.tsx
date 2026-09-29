import React from 'react';
import { CloudSun, History, X } from 'lucide-react';
import { LiveProviderPanel } from './LiveProviderPanel';

export type WeatherDataSource = 'historical' | 'live';

interface WeatherSettingsPanelProps {
  open: boolean;
  source: WeatherDataSource;
  onSourceChange: (source: WeatherDataSource) => void;
  onClose: () => void;
  canManageLiveProviders?: boolean;
}

/** Weather settings popover: data-source toggle (Historical vs Live-optional)
 *  plus the (always-disabled) live provider panel. Selecting Live changes the
 *  UI only — the map keeps historical ERA5 data because backend live weather
 *  is disabled in this build (honesty over pretend). Live-provider
 *  configuration is restricted to administrators. */
export const WeatherSettingsPanel: React.FC<WeatherSettingsPanelProps> = ({
  open,
  source,
  onSourceChange,
  onClose,
  canManageLiveProviders = true,
}) => {
  if (!open) return null;
  return (
    <div
      className="absolute top-14 right-3 z-40 w-80 max-w-[calc(100%-16px)] rounded-xl bg-slate-950/95 backdrop-blur-md border border-slate-700/80 shadow-2xl p-3 pointer-events-auto"
      id="weather-settings-panel"
    >
      <div className="flex items-center justify-between gap-2 mb-2">
        <p className="text-[11px] font-bold uppercase tracking-wide text-slate-200">Weather Settings</p>
        <button type="button" onClick={onClose} className="text-slate-500 hover:text-white" aria-label="Close settings">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      <p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">Weather Data Source</p>
      <div className="mt-1.5 grid grid-cols-2 gap-0.5 rounded-lg bg-slate-900/70 border border-slate-700/70 p-0.5">
        <button
          type="button"
          onClick={() => onSourceChange('historical')}
          aria-pressed={source === 'historical'}
          className={`flex items-center justify-center gap-1 rounded-md px-2 py-1 text-[10px] font-bold ${
            source === 'historical' ? 'bg-violet-700/80 text-white' : 'text-slate-400 hover:text-white'
          }`}
        >
          <History className="w-3 h-3" /> Historical
        </button>
        <button
          type="button"
          onClick={() => onSourceChange('live')}
          aria-pressed={source === 'live'}
          id="weather-source-live"
          className={`flex items-center justify-center gap-1 rounded-md px-2 py-1 text-[10px] font-bold ${
            source === 'live' ? 'bg-sky-700/80 text-white' : 'text-slate-400 hover:text-white'
          }`}
        >
          <CloudSun className="w-3 h-3" /> Live (Optional)
        </button>
      </div>

      {source === 'live' && (
        <p className="mt-2 rounded-lg border border-amber-500/40 bg-amber-950/60 px-2 py-1.5 text-[10px] leading-relaxed text-amber-200">
          Live selected, but no provider is enabled — map data is unchanged and still comes from the historical ERA5
          archive. Live weather requires the backend to enable its live provider.
        </p>
      )}

      <div className="mt-3 border-t border-slate-800 pt-2">
        <LiveProviderPanel canManage={canManageLiveProviders} />
      </div>
    </div>
  );
};