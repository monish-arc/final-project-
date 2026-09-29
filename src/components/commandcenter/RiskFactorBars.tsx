import React from 'react';
import { Activity } from 'lucide-react';
import { RiskAssessmentResponse } from '../../types';

interface RiskFactorBarsProps {
  assessment: RiskAssessmentResponse | null;
  loading: boolean;
  anchorLabel: string | null;
}

export const RiskFactorBars: React.FC<RiskFactorBarsProps> = ({ assessment, loading, anchorLabel }) => {
  const factors = assessment?.factors ?? [];

  return (
    <section className="bg-sm-panel border border-sm-border rounded-xl shadow p-4">
      <div className="flex items-center gap-2 mb-3">
        <Activity className="w-4 h-4 text-violet-400" />
        <div>
          <h3 className="text-xs font-bold uppercase tracking-wider text-sm-text">
            Risk Factor Analysis
          </h3>
          <p className="text-[10px] text-sm-muted">
            Contributing risk factors — not validated AI certainty.
          </p>
        </div>
      </div>

      {loading ? (
        <p className="text-[11px] text-sm-muted">Computing factor decomposition…</p>
      ) : !assessment || factors.length === 0 ? (
        <p className="text-[11px] text-sm-muted">
          {anchorLabel
            ? 'No factor data returned for this point — run the risk engine.'
            : 'Select a habitation and run the risk engine to decompose contributing factors.'}
        </p>
      ) : (
        <div className="space-y-2.5">
          {factors
            .slice()
            .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
            .map((f) => {
              const score = f.score;
              const width = score != null ? Math.max(0, Math.min(100, score)) : 0;
              const impact = String(f.impact ?? '').replace(/_/g, ' ').toLowerCase();
              const color =
                f.impact === 'HIGH'
                  ? 'bg-red-500'
                  : f.impact === 'MEDIUM'
                    ? 'bg-orange-400'
                    : f.impact === 'LOW'
                      ? 'bg-emerald-500'
                      : 'bg-slate-500';
              return (
                <div key={f.key} className="space-y-1">
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="font-semibold text-sm-text">{f.label}</span>
                    <span className="text-sm-muted">
                      {score != null ? `${score}` : 'no signal'}
                      {impact ? ` · ${impact}` : ''}
                    </span>
                  </div>
                  <div className="h-2 rounded-full bg-sm-bg overflow-hidden">
                    <div
                      className={`h-full rounded-full ${color}`}
                      style={{ width: `${width}%` }}
                    />
                  </div>
                  {f.detail && (
                    <p className="text-[10px] text-sm-muted leading-snug">{f.detail}</p>
                  )}
                </div>
              );
            })}
        </div>
      )}
    </section>
  );
};