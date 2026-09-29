import React from 'react';
import { Database } from 'lucide-react';
import { DataStatusEntry, DataLayerStatus } from '../../types';
import { DataStatusBadge } from '../DataStatusBadge';

interface DataSourcesPanelProps {
  dataStatus: DataStatusEntry[] | null;
  checkedAt?: string | null;
}

export const DataSourcesPanel: React.FC<DataSourcesPanelProps> = ({ dataStatus, checkedAt }) => {
  const layers = dataStatus ?? [];
  const liveCount = layers.filter((l) =>
    ['LIVE', 'MODEL', 'CALCULATED', 'FORECAST', 'AVAILABLE', 'CACHED', 'RECENT'].includes(String(l.status))
  ).length;

  return (
    <section className="bg-sm-panel border border-sm-border rounded-xl shadow p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <Database className="w-4 h-4 text-sm-green" />
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-sm-text">
              Data Sources & Status
            </h3>
            <p className="text-[10px] text-sm-muted">
              Every layer reports the source that actually served it — honesty over hardcoded labels.
            </p>
          </div>
        </div>
        <span className="text-[11px] text-sm-muted">
          {liveCount}/{layers.length} live
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
                  <DataStatusBadge status={status} title="" />
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
};