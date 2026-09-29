import React from 'react';
import { Users, AlertTriangle, Shield, Activity } from 'lucide-react';
import { DashboardSummary } from '../../types';

interface RiskSummaryRowProps {
  summary: DashboardSummary | null;
  regionLabel: string;
}

const LEVEL_STYLES: Record<string, string> = {
  'Immediate Relocation': 'border-red-600/60 bg-red-500/10 text-red-200',
  'Short-Term Relocation': 'border-orange-500/60 bg-orange-500/10 text-orange-200',
  'Medium-Term Relocation': 'border-yellow-500/60 bg-yellow-500/10 text-yellow-200',
  'Monitor Only': 'border-emerald-500/60 bg-emerald-500/10 text-emerald-200',
};

function Tile({
  label,
  value,
  unit,
  hint,
  tone,
  icon,
}: {
  label: string;
  value: string;
  unit?: string;
  hint?: string;
  tone?: string;
  icon?: React.ReactNode;
}) {
  return (
    <div className="bg-sm-panel border border-sm-border rounded-xl p-4 shadow flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-bold uppercase tracking-wider text-sm-muted">
          {label}
        </span>
        {icon && <span className="text-sm-muted">{icon}</span>}
      </div>
      <div className={`text-2xl font-extrabold ${tone ?? 'text-sm-text'}`}>
        {value}
        {unit && <span className="text-xs font-normal text-sm-muted"> {unit}</span>}
      </div>
      {hint && <span className="text-[10px] text-sm-muted">{hint}</span>}
    </div>
  );
}

export const RiskSummaryRow: React.FC<RiskSummaryRowProps> = ({ summary, regionLabel }) => {
  const noData =
    !summary || summary.region?.has_curated_data === false || summary.total_habitations_monitored === 0;

  if (noData) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="bg-sm-panel border border-sm-border rounded-xl p-4 shadow flex flex-col gap-1"
          >
            <span className="text-[10px] font-bold uppercase tracking-wider text-sm-muted">
              {['Critical', 'High', 'Medium', 'Low', 'Vulnerable Population', 'Monitored Habitations'][i]}
            </span>
            <p className="text-lg font-extrabold text-sm-muted">—</p>
          </div>
        ))}
      </div>
    );
  }

  const byLevel = (name: string) =>
    summary.relocation_priority_distribution.find((d) => d.level === name);

  const levels = [
    { name: 'Immediate Relocation', label: 'Critical' },
    { name: 'Short-Term Relocation', label: 'High' },
    { name: 'Medium-Term Relocation', label: 'Medium' },
    { name: 'Monitor Only', label: 'Low' },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3">
      {levels.map(({ name, label }) => {
        const level = byLevel(name);
        return (
          <div
            key={name}
            className={`rounded-xl border p-4 shadow flex flex-col gap-1 ${LEVEL_STYLES[name] ?? 'border-slate-700 bg-slate-900'}`}
          >
            <span className="text-[10px] font-bold uppercase tracking-wider opacity-80">
              {label}
            </span>
            <div className="text-2xl font-extrabold">
              {level?.count ?? 0}
              <span className="text-xs font-normal opacity-70"> habitations</span>
            </div>
            <span className="text-[10px] opacity-70">
              {level?.population?.toLocaleString() ?? '0'} people
            </span>
          </div>
        );
      })}

      <Tile
        label="Vulnerable Population"
        value={summary.high_risk_population.toLocaleString()}
        hint="Pop. in Immediate + Short-Term relocation"
        tone="text-amber-300"
        icon={<Users className="w-4 h-4" />}
      />
      <Tile
        label="Monitored Habitations"
        value={String(summary.total_habitations_monitored)}
        hint={regionLabel}
        tone="text-sky-300"
        icon={<Activity className="w-4 h-4" />}
      />

      {(summary.data_status === 'UNAVAILABLE') && (
        <p className="lg:col-span-6 text-[11px] text-slate-500">
          Summary aggregates reflect only genuinely curated records for{' '}
          {regionLabel}. None are fabricated for other locations.
        </p>
      )}
    </div>
  );
};