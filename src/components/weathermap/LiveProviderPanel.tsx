import React, { useState } from 'react';
import { Sparkles, X } from 'lucide-react';
import {
  LIVE_PROVIDER_TEMPLATES,
  getLiveProviders,
  saveLiveProvider,
  removeLiveProvider,
  liveProviderStatus,
  type LiveProviderConfig,
  type LiveProviderKind,
} from '../../lib/liveProviders';

/** Optional live-provider configuration panel. Providers are only stored
 *  locally and can never be enabled (backend WEATHER_LIVE_ENABLED=False) —
 *  the panel is purely declarative and fires no network calls. Configuration
 *  (add / remove) is restricted to administrators; every other portal sees the
 *  read-only status. */
export const LiveProviderPanel: React.FC<{ canManage?: boolean }> = ({ canManage = true }) => {
  const [providers, setProviders] = useState<LiveProviderConfig[]>(() => getLiveProviders());
  const [addOpen, setAddOpen] = useState(false);
  const [selectedKind, setSelectedKind] = useState<LiveProviderKind>('open-meteo');

  const refresh = () => setProviders(getLiveProviders());

  const handleAdd = () => {
    const template = LIVE_PROVIDER_TEMPLATES.find((t) => t.kind === selectedKind) ?? LIVE_PROVIDER_TEMPLATES[0];
    saveLiveProvider({
      id: template.id,
      name: template.name,
      kind: template.kind,
      baseUrl: template.baseUrl,
      note: template.note,
    });
    setAddOpen(false);
    setSelectedKind('open-meteo');
    refresh();
  };

  const handleRemove = (id: string) => {
    removeLiveProvider(id);
    refresh();
  };

  return (
    <div className="space-y-2" data-weather-live-provider-panel>
      <div className="flex items-center justify-between gap-2">
        <p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">Live Weather Provider</p>
        <span className="text-[9px] font-bold text-amber-300 border border-amber-500/40 rounded-full px-2 py-0.5">
          Disabled
        </span>
      </div>

      {providers.length === 0 ? (
        <p className="text-[10px] text-slate-400">Disabled — No live provider configured.</p>
      ) : (
        <ul className="space-y-1.5">
          {providers.map((p) => (
            <li
              key={p.id}
              className="flex items-start justify-between gap-2 rounded-lg border border-slate-700/70 bg-slate-900/60 px-2 py-1.5"
            >
              <div className="min-w-0">
                <p className="text-[11px] font-bold text-slate-200">{p.name}</p>
                {p.baseUrl && <p className="text-[9px] text-slate-500 truncate">{p.baseUrl}</p>}
                {p.note && <p className="text-[9px] text-slate-500">{p.note}</p>}
                <p className="text-[9px] text-amber-400/90 mt-0.5">
                  {liveProviderStatus(p).toUpperCase()} (backend live weather not enabled)
                </p>
              </div>
              {canManage && (
                <button
                  type="button"
                  onClick={() => handleRemove(p.id)}
                  id={`live-provider-remove-${p.id}`}
                  className="text-slate-500 hover:text-rose-400 shrink-0"
                  title="Remove provider"
                  aria-label={`Remove ${p.name}`}
                >
                  <X className="w-3 h-3" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {canManage && !addOpen ? (
        <button
          type="button"
          onClick={() => setAddOpen(true)}
          id="weather-add-live-provider"
          className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-slate-600 text-[10px] font-bold text-slate-300 px-2.5 py-1 hover:border-sky-500 hover:text-sky-300"
        >
          <Sparkles className="w-3 h-3" /> + Add Live Provider
        </button>
      ) : canManage && addOpen ? (
        <div className="rounded-lg border border-slate-700/70 bg-slate-900/60 p-2 space-y-2">
          <select
            aria-label="Provider type"
            className="w-full text-[10px] bg-slate-950 text-slate-200 border border-slate-700 rounded-lg px-2 py-1 outline-none"
            value={selectedKind}
            onChange={(e) => setSelectedKind(e.target.value as LiveProviderKind)}
            data-weather-provider-kind
          >
            {LIVE_PROVIDER_TEMPLATES.map((t) => (
              <option key={t.id} value={t.kind}>
                {t.name} — {t.note}
              </option>
            ))}
          </select>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleAdd}
              id="weather-provider-save"
              className="text-[10px] font-bold bg-sky-700 hover:bg-sky-600 text-white rounded-lg px-2.5 py-1"
            >
              Save provider
            </button>
            <button
              type="button"
              onClick={() => setAddOpen(false)}
              className="text-[10px] font-bold text-slate-400 hover:text-white px-2 py-1"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <p className="rounded-lg border border-slate-800 bg-slate-900/40 px-2 py-1.5 text-[9px] text-slate-400 leading-relaxed">
          Live-provider configuration is restricted to administrators. Live weather stays disabled in this build.
        </p>
      )}

      <p className="text-[9px] text-slate-500 leading-relaxed">
        Providers are optional and stay disabled — live weather is off in this build. Historical ERA5 mode never
        calls them.
      </p>
    </div>
  );
};