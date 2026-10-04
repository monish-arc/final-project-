import React from 'react';
import { Database } from 'lucide-react';
import { DataStatusEntry, DataLayerStatus, ProviderStatusEntry } from '../../types';
import { DataStatusBadge } from '../DataStatusBadge';

interface DataSourcesPanelProps {
  dataStatus: DataStatusEntry[] | null;
  checkedAt?: string | null;
  /** Official Historical Data providers (ERA5 / IMD / India-WRIS / KSDMA). */
  providers?: ProviderStatusEntry[] | null;
}

// Human labels for the provider ids emitted by the backend registry. Anything
// unrecognised falls back to the raw id so a new provider is never hidden.
const PROVIDER_LABELS: Record<string, string> = {
  era5: 'ERA5 Reanalysis (Open-Meteo)',
  imd: 'IMD — India Meteorological Dept',
  indiawris: 'India-WRIS / National Water Data',
  ksdma: 'KSDMA — Kerala SDMA',
};

export const DataSourcesPanel: React.FC<DataSourcesPanelProps> = ({ dataStatus, checkedAt, providers }) => {
  const layers = dataStatus ?? [];
  const statusOf = (l: DataStatusEntry): string => String(l.status ?? 'UNAVAILABLE');
  // Only statuses that mean "currently serving" count as live. CACHED and
  // CALCULATED are deliberately excluded: a cached or derived value is not the
  // same claim as live data, and folding them in would overstate freshness.
  const LIVE_STATUSES = ['LIVE', 'MODEL', 'FORECAST', 'RECENT'];
  const liveCount = layers.filter((l) => LIVE_STATUSES.includes(statusOf(l))).length;
  const cachedCount = layers.filter((l) => statusOf(l) === 'CACHED').length;
  const unavailableCount = layers.filter((l) =>
    ['UNAVAILABLE', 'ERROR', 'NOT CONFIGURED', 'NOT_CONFIGURED'].includes(statusOf(l))
  ).length;
  // Official provider rows, shown only when the backend actually reports them.
  const providerRows = providers ?? [];

  return (
    <section className="bg-sm-panel border border-sm-border rounded-xl shadow p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <Database className="w-4 h-4 text-sm-green" />
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-sm-text">
              Data Sources &amp; Status
            </h3>
            <p className="text-[10px] text-sm-muted">
              Every layer reports the source that actually served it — honesty over hardcoded labels.
            </p>
          </div>
        </div>
        <span className="text-[11px] text-sm-muted">
          {liveCount}/{layers.length} live
          {cachedCount > 0 ? ` · ${cachedCount} cached` : ''}
          {unavailableCount > 0 ? ` · ${unavailableCount} unavailable` : ''}
          {checkedAt ? ` · checked ${new Date(checkedAt).toLocaleTimeString()}` : ''}
        </span>
      </div>

      {layers.length === 0 ? (
        <p className="text-[11px] text-sm-muted">
          No data-status report available for the selected region.
        </p>
      ) : (
        <ul className="space-y-1.5">
          {layers.map((layer) => {
            const status = String(layer.status ?? 'UNAVAILABLE') as DataLayerStatus;
            return (
              <li
                key={`${layer.layer}-${layer.source}`}
                className="flex flex-wrap items-center justify-between gap-x-3 gap-y-0.5 rounded-md px-2 py-1.5 bg-sm-panel-2/60"
              >
                <span className="text-[11px] font-semibold text-sm-text capitalize">
                  {String(layer.layer).replace(/_/g, ' ')}
                </span>
                <span className="inline-flex items-center gap-2">
                  <span className="text-[10px] text-sm-muted truncate max-w-[220px]">{layer.source}</span>
                  {layer.updated_at ? (
                    <span className="text-[10px] text-sm-muted shrink-0">
                      {new Date(layer.updated_at).toLocaleDateString(undefined, {
                        year: 'numeric',
                      })}
                    </span>
                  ) : null}
                  {/* Raw status from the backend, shown verbatim. `DataStatusBadge`
                      normalises several distinct states (NOT CONFIGURED and ERROR
                      both collapse to UNAVAILABLE) and is shared with the GIS map,
                      so it is left untouched. Printing the raw value here keeps
                      those statuses distinguishable without changing that badge. */}
                  <span
                    className="shrink-0 font-mono text-[10px] text-sm-muted border border-sm-border rounded px-1 py-0.5"
                    title="Raw status reported by the backend"
                  >
                    {String(layer.status ?? 'UNAVAILABLE')}
                  </span>
                  <DataStatusBadge status={status} title="" />
                </span>
              </li>
            );
          })}
        </ul>
      )}

      {providerRows.length > 0 && (
        <>
          <h4 className="mt-4 mb-2 text-[10px] font-bold uppercase tracking-wider text-sm-muted">
            Official Historical Data Providers
          </h4>
          <ul className="space-y-1.5">
            {providerRows.map((provider) => {
              const status = String(provider.status ?? 'UNAVAILABLE') as DataLayerStatus;
              return (
                <li
                  key={provider.provider}
                  className="flex flex-wrap items-start justify-between gap-x-3 gap-y-0.5 rounded-md px-2 py-1.5 bg-sm-panel-2/60"
                >
                  <span className="min-w-0">
                    <span className="block text-[11px] font-semibold text-sm-text">
                      {PROVIDER_LABELS[provider.provider] ?? provider.provider}
                    </span>
                    <span className="block text-[10px] text-sm-muted truncate max-w-[320px]">
                      {provider.source}
                    </span>
                    {/* The honest reason a provider is not serving. Rendered
                        verbatim: this is the operator-facing explanation of what
                        is missing, so it must not be summarised away. */}
                    {provider.error ? (
                      <span className="block text-[10px] text-amber-300/90 leading-tight">
                        {provider.error}
                      </span>
                    ) : null}
                    {provider.coverage ? (
                      <span className="block text-[9px] text-sm-muted/70 leading-tight">
                        {provider.coverage}
                        {provider.period ? ` · ${provider.period}` : ''}
                      </span>
                    ) : null}
                  </span>
                  <span className="inline-flex items-center gap-2 shrink-0">
                    {/* Raw status verbatim, matching the layer rows above. */}
                    <span
                      className="font-mono text-[10px] text-sm-muted border border-sm-border rounded px-1 py-0.5"
                      title="Raw status reported by the backend"
                    >
                      {String(provider.status ?? 'UNAVAILABLE')}
                    </span>
                    <DataStatusBadge status={status} title="" />
                  </span>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
};