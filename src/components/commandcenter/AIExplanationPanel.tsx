import React from 'react';
import { Sparkles, ShieldCheck } from 'lucide-react';
import { RiskAssessmentResponse } from '../../types';

interface AIExplanationPanelProps {
  assessment: RiskAssessmentResponse | null;
  loading: boolean;
  anchorLabel: string | null;
}

const BAND_STYLE: Record<string, string> = {
  CRITICAL: 'bg-red-500/20 text-red-300 border-red-500/50',
  HIGH: 'bg-orange-500/20 text-orange-300 border-orange-500/50',
  MEDIUM: 'bg-yellow-500/20 text-yellow-200 border-yellow-500/50',
  LOW: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/50',
  UNKNOWN: 'bg-slate-700 text-slate-300 border-slate-500',
};

export const AIExplanationPanel: React.FC<AIExplanationPanelProps> = ({
  assessment,
  loading,
  anchorLabel,
}) => {
  return (
    <section className="bg-sm-panel border border-sm-border rounded-xl shadow p-4">
      <div className="flex items-center gap-2 mb-3">
        <Sparkles className="w-4 h-4 text-sm-green" />
        <div>
          <h3 className="text-xs font-bold uppercase tracking-wider text-sm-text">
            AI Risk Explanation
          </h3>
          <p className="text-[10px] text-sm-muted">
            Explanation is generated only from retrieved factor data — never assumed.
          </p>
        </div>
      </div>

      {loading ? (
        <p className="text-[11px] text-sm-muted">Running the susceptibility engine…</p>
      ) : !assessment ? (
        <p className="text-[11px] text-sm-muted">
          {anchorLabel
            ? 'No assessment returned for this point.'
            : 'Select a habitation and run the risk engine to see the explanation.'}
        </p>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border font-bold text-xs ${
                BAND_STYLE[assessment.risk_band] ?? BAND_STYLE.UNKNOWN
              }`}
            >
              <ShieldCheck className="w-3.5 h-3.5" />
              {assessment.risk_band} — {assessment.risk_score ?? 'no score'}
              {assessment.risk_score != null ? '/100' : ''}
            </span>
            {assessment.disaster_type && (
              <span className="text-[11px] text-sm-muted">
                Primary hazard class:{' '}
                <b className="text-sm-text">{String(assessment.disaster_type).replace(/_/g, ' ')}</b>
              </span>
            )}
            <span className="text-[10px] text-sm-muted">
              Mode {String(assessment.assessment_mode).toUpperCase()} · model{' '}
              {String(assessment.model_status ?? 'RULE_BASED').replace(/_/g, ' ')}
            </span>
          </div>

          {(assessment.factors ?? []).length > 0 && (
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-sm-muted mb-1">
                Top contributing factors
              </p>
              <ul className="space-y-1">
                {assessment.factors
                  .slice()
                  .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
                  .slice(0, 4)
                  .map((f) => (
                    <li key={f.key} className="text-[11px] text-sm-text/90">
                      • <b>{f.label}</b>
                      {f.score != null ? ` (${f.score})` : ''} —{' '}
                      {f.detail || String(f.impact ?? '').replace(/_/g, ' ').toLowerCase()}
                    </li>
                  ))}
              </ul>
            </div>
          )}

          {assessment.caveat && (
            <p className="text-[11px] text-sm-muted italic leading-snug">{assessment.caveat}</p>
          )}

          {(assessment.sources ?? []).length > 0 && (
            <div className="text-[10px] text-sm-muted leading-relaxed">
              Sources:{' '}
              {assessment.sources
                .map((s) => `${s.name} (${String(s.status).replace(/_/g, ' ').toLowerCase()})`)
                .join(' · ')}
            </div>
          )}
        </div>
      )}
    </section>
  );
};