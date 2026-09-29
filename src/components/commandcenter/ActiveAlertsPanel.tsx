import React from 'react';
import { AlertTriangle, MapPin, ShieldAlert } from 'lucide-react';
import { RiskAlert, RedZone } from '../../types';
import type { RegionViewportFocus } from '../../lib/regionViewport';

interface ActiveAlertsPanelProps {
  riskAlerts: RiskAlert[];
  redZones: RedZone[];
  regionLabel: string;
  onLocateOnMap: (focus: RegionViewportFocus) => void;
}

const SEVERITY_STYLE: Record<string, string> = {
  Critical: 'bg-red-500/20 text-red-300 border-red-500/40',
  High: 'bg-orange-500/20 text-orange-300 border-orange-500/40',
  Medium: 'bg-yellow-500/20 text-yellow-200 border-yellow-500/40',
  Low: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
};

function focusFor(lat: number, lng: number, label: string, key: string): RegionViewportFocus {
  return { lat, lng, zoom: 13, key, label };
}

export const ActiveAlertsPanel: React.FC<ActiveAlertsPanelProps> = ({
  riskAlerts,
  redZones,
  regionLabel,
  onLocateOnMap,
}) => {
  const sorted = [...riskAlerts]
    .sort((a, b) => String(b.reported_at ?? '').localeCompare(String(a.reported_at ?? '')))
    .slice(0, 6);

  return (
    <section className="bg-sm-panel border border-sm-border rounded-xl shadow overflow-hidden flex flex-col">
      <div className="px-4 py-3 border-b border-sm-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-red-400" />
          <h3 className="text-xs font-bold uppercase tracking-wider text-sm-text">
            Active Alerts
          </h3>
        </div>
        <span className="text-[10px] text-sm-muted">
          {riskAlerts.length} published · {redZones.length} hazard zones
        </span>
      </div>

      <div className="flex-1 space-y-2 p-3 overflow-y-auto max-h-[300px]">
        {sorted.length === 0 && (
          <p className="text-[11px] text-sm-muted p-2">
            No published alerts for {regionLabel || 'this region'}. Hazard zones are
            still listed below for context.
          </p>
        )}
        {sorted.map((alert) => (
          <div key={alert.id} className="rounded-lg border border-sm-border bg-sm-panel-2/60 p-2.5 space-y-1.5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-bold text-sm-text">
                {alert.hazard_type}
              </span>
              <span
                className={`text-[9px] font-bold px-1.5 py-0.5 rounded border ${
                  SEVERITY_STYLE[alert.severity] ?? 'bg-sm-panel-2 text-sm-muted border-sm-border'
                }`}
              >
                {alert.severity}
              </span>
            </div>
            <p className="text-[11px] text-sm-muted leading-snug line-clamp-2">{alert.description}</p>
            <div className="flex items-center justify-between pt-1 border-t border-sm-border text-[10px] text-sm-muted">
              <span>
                {alert.reported_at
                  ? new Date(alert.reported_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
                  : '—'}
              </span>
              <button
                onClick={() =>
                  onLocateOnMap(focusFor(alert.latitude, alert.longitude, `${alert.hazard_type} alert`, `alert-${alert.id}`))
                }
                className="inline-flex items-center gap-1 text-sm-green hover:text-sm-green-hover font-semibold cursor-pointer"
              >
                <MapPin className="w-3 h-3" /> Locate
              </button>
            </div>
          </div>
        ))}

        {redZones.length > 0 && (
          <div className="pt-2 border-t border-sm-border">
            <p className="text-[10px] font-bold uppercase tracking-wider text-sm-muted mb-1.5 flex items-center gap-1.5">
              <ShieldAlert className="w-3 h-3" /> Derived hazard zones ({redZones.length})
            </p>
            <p className="text-[11px] text-sm-muted leading-snug">
              {redZones.slice(0, 5).map((z) => z.zone_name).join(' · ') || '—'}
            </p>
          </div>
        )}
      </div>
    </section>
  );
};