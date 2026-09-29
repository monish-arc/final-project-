import React, { useState } from 'react';
import {
  SlidersHorizontal,
  ShieldAlert,
  ArrowRight,
  TrendingDown,
  Compass,
  CheckCircle2,
  RefreshCw,
  Info,
  Layers,
  Navigation,
} from 'lucide-react';
import { Habitation, RelocationRecommendation } from '../types';
import { RiskBadge } from '../components/RiskBadge';

interface PriorityPageProps {
  habitations: Habitation[];
  recommendations: RelocationRecommendation[];
  onSelectHabitation: (hab: Habitation) => void;
  onSimulate: (habId: string, siteId?: string) => void;
  onPlanEvacuation?: (hab: Habitation) => void;
  onRecalculatePriority: (params: any) => Promise<any>;
}

export const PriorityPage: React.FC<PriorityPageProps> = ({
  habitations,
  recommendations,
  onSelectHabitation,
  onSimulate,
  onPlanEvacuation,
  onRecalculatePriority,
}) => {
  const [selectedFilter, setSelectedFilter] = useState('all');
  const [isRecalculating, setIsRecalculating] = useState(false);
  const [showFormulaInfo, setShowFormulaInfo] = useState(false);

  // Recalculate simulation state
  const [recalcHabId, setRecalcHabId] = useState<string | null>(null);
  const [recalcLandslide, setRecalcLandslide] = useState<number>(80);
  const [recalcFlood, setRecalcFlood] = useState<number>(80);
  const [recalcRain, setRecalcRain] = useState<number>(80);

  const sortedHabs = [...habitations].sort((a, b) => b.priority_score - a.priority_score);

  const filteredHabs = sortedHabs.filter((h) => {
    if (selectedFilter === 'all') return true;
    return h.priority_level.toLowerCase() === selectedFilter.toLowerCase();
  });

  const handleOpenRecalcModal = (hab: Habitation) => {
    setRecalcHabId(hab.id);
    setRecalcLandslide(hab.landslide_risk);
    setRecalcFlood(hab.flood_risk);
    setRecalcRain(hab.extreme_rainfall_risk);
  };

  const handleExecuteRecalc = async () => {
    if (!recalcHabId) return;
    setIsRecalculating(true);
    try {
      await onRecalculatePriority({
        habitation_id: recalcHabId,
        landslide_risk: recalcLandslide,
        flood_risk: recalcFlood,
        extreme_rainfall_risk: recalcRain,
      });
      setRecalcHabId(null);
    } finally {
      setIsRecalculating(false);
    }
  };

  return (
    <div id="relocation-priority-matrix-view" className="space-y-6 animate-in fade-in duration-200">
      {/* Header */}
      <div className="bg-sm-panel p-5 rounded-xl border border-sm-border shadow-sm flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-semibold uppercase tracking-wider text-red-300 bg-red-500/10 border border-red-500/30 px-2 py-0.5 rounded">
              DECISION SUPPORT MATRIX
            </span>
          </div>
          <h2 className="text-xl font-bold text-sm-text tracking-tight flex items-center gap-2">
            <SlidersHorizontal className="w-5 h-5 text-red-400" />
            <span>Habitation Relocation Priority Ranking</span>
          </h2>
          <p className="text-xs text-sm-muted mt-0.5">
            Objective mathematical ranking combining 50% Hazard Exposure, 30% Demographic Vulnerability, and 20% Empirical Disaster History
          </p>
        </div>

        <button
          onClick={() => setShowFormulaInfo(!showFormulaInfo)}
          className="flex items-center gap-1.5 text-xs text-sm-muted hover:text-sm-text bg-sm-panel-2 hover:bg-sm-panel-2/80 px-3 py-1.5 rounded-lg border border-sm-border transition"
        >
          <Info className="w-4 h-4 text-sm-green" />
          <span>{showFormulaInfo ? 'Hide Math Formula' : 'View Decision Formula'}</span>
        </button>
      </div>

      {/* Formula Explainer Panel */}
      {showFormulaInfo && (
        <div className="p-4 bg-sm-bg text-sm-text rounded-xl border border-sm-border text-xs space-y-2 animate-in fade-in duration-150">
          <h3 className="font-bold text-sm text-sm-text flex items-center gap-2">
            <Layers className="w-4 h-4 text-red-400" /> Official Decision Support Formula
          </h3>
          <p className="text-sm-muted font-mono text-[11px] bg-sm-bg p-2.5 rounded border border-sm-border">
            Priority Index = 0.50 &times; Hazard Score + 0.30 &times; Vulnerability Score + 0.20 &times; Disaster History Score
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-[11px] pt-1 border-t border-sm-border">
            <div>
              <span className="text-red-400 font-bold block">50% Hazard Component:</span>
              <span>40% Landslide + 30% Flood + 20% Extreme Rain + 10% Past Frequency</span>
            </div>
            <div>
              <span className="text-amber-400 font-bold block">30% Vulnerability Component:</span>
              <span>35% Pop Density + 25% Dependents Ratio + 20% Road Access + 20% Hospital Distance</span>
            </div>
            <div>
              <span className="text-blue-400 font-bold block">20% History Component:</span>
              <span>Documented historical extreme events (Min(100, Events &times; 16))</span>
            </div>
          </div>
        </div>
      )}

      {/* Filter Tabs */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-sm-panel p-3 rounded-xl border border-sm-border shadow-sm">
        <div className="flex items-center gap-1.5 overflow-x-auto text-xs">
          <button
            onClick={() => setSelectedFilter('all')}
            className={`px-3 py-1.5 rounded-lg font-medium transition ${
              selectedFilter === 'all'
                ? 'bg-sm-green text-slate-900'
                : 'text-sm-muted hover:bg-sm-panel-2'
            }`}
          >
            All Habitations ({sortedHabs.length})
          </button>
          <button
            onClick={() => setSelectedFilter('immediate relocation')}
            className={`px-3 py-1.5 rounded-lg font-medium transition ${
              selectedFilter === 'immediate relocation'
                ? 'bg-red-600 text-white'
                : 'text-sm-muted hover:bg-sm-panel-2'
            }`}
          >
            Immediate (75+)
          </button>
          <button
            onClick={() => setSelectedFilter('short-term relocation')}
            className={`px-3 py-1.5 rounded-lg font-medium transition ${
              selectedFilter === 'short-term relocation'
                ? 'bg-amber-600 text-white'
                : 'text-sm-muted hover:bg-sm-panel-2'
            }`}
          >
            Short-Term (50 - 74)
          </button>
          <button
            onClick={() => setSelectedFilter('medium-term relocation')}
            className={`px-3 py-1.5 rounded-lg font-medium transition ${
              selectedFilter === 'medium-term relocation'
                ? 'bg-yellow-600 text-white'
                : 'text-sm-muted hover:bg-sm-panel-2'
            }`}
          >
            Medium-Term (30 - 49)
          </button>
        </div>

        <span className="text-xs text-sm-muted font-medium">
          Showing {filteredHabs.length} of {sortedHabs.length} Habitations
        </span>
      </div>

      {/* Priority Matrix Table */}
      <div className="bg-sm-panel rounded-xl border border-sm-border shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-sm-muted">
            <thead className="bg-sm-panel-2 text-sm-muted uppercase tracking-wider font-semibold border-b border-sm-border">
              <tr>
                <th className="px-5 py-3.5">Rank & Habitation</th>
                <th className="px-4 py-3.5">Priority Index</th>
                <th className="px-4 py-3.5">Classification</th>
                <th className="px-4 py-3.5">Hazard (50%)</th>
                <th className="px-4 py-3.5">Vulnerability (30%)</th>
                <th className="px-4 py-3.5">History (20%)</th>
                <th className="px-4 py-3.5">Destination Safe Site</th>
                <th className="px-4 py-3.5">Risk Reduction</th>
                <th className="px-5 py-3.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-sm-border">
              {filteredHabs.map((hab, index) => {
                const rec = recommendations.find((r) => r.habitation_id === hab.id);
                const histScore = Math.min(100, hab.disaster_history_count * 16);

                return (
                  <tr
                    key={hab.id}
                    className="hover:bg-sm-panel-2/60 transition cursor-pointer"
                    onClick={() => onSelectHabitation(hab)}
                  >
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-2.5">
                        <span className="w-6 h-6 rounded-full bg-sm-panel-2 border border-sm-border text-sm-text font-bold flex items-center justify-center text-[10px]">
                          #{index + 1}
                        </span>
                        <div>
                          <span className="font-bold text-sm-text block">{hab.village_name}</span>
                          <span className="text-[10px] text-sm-muted font-mono">
                            {hab.village_code} | Pop: {hab.population.toLocaleString()}
                          </span>
                        </div>
                      </div>
                    </td>

                    <td className="px-4 py-3.5">
                      <div className="flex items-baseline gap-1">
                        <span className="text-base font-extrabold text-sm-text">
                          {hab.priority_score}
                        </span>
                        <span className="text-[10px] text-sm-muted">/100</span>
                      </div>
                    </td>

                    <td className="px-4 py-3.5">
                      <RiskBadge level={hab.priority_level} size="sm" />
                    </td>

                    <td className="px-4 py-3.5 font-semibold text-red-400">
                      {hab.hazard_score}
                    </td>

                    <td className="px-4 py-3.5 font-semibold text-amber-400">
                      {hab.vulnerability_score}
                    </td>

                    <td className="px-4 py-3.5 font-semibold text-blue-400">
                      {histScore} ({hab.disaster_history_count} evts)
                    </td>

                    <td className="px-4 py-3.5">
                      {rec ? (
                        <div>
                          <span className="font-semibold text-sm-text block">
                            {rec.relocation_site_name.split(' ')[0]} Enclave
                          </span>
                          <span className="text-[10px] text-emerald-400 font-medium">
                            {rec.recommended_families} families
                          </span>
                        </div>
                      ) : (
                        <span className="text-sm-muted italic">Evaluating</span>
                      )}
                    </td>

                    <td className="px-4 py-3.5">
                      {rec ? (
                        <span className="inline-flex items-center gap-1 font-bold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/30">
                          <TrendingDown className="w-3 h-3" />
                          <span>-{rec.risk_reduction_percent}%</span>
                        </span>
                      ) : (
                        <span className="text-sm-muted">-</span>
                      )}
                    </td>

                    <td className="px-5 py-3.5 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <button
                          title="Plan safe evacuation route"
                          onClick={(e) => {
                            e.stopPropagation();
                            onPlanEvacuation?.(hab);
                          }}
                          className="p-1.5 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 transition cursor-pointer"
                        >
                          <Navigation className="w-4 h-4" />
                        </button>
                        <button
                          title="Simulate in Relocation Simulator"
                          onClick={(e) => {
                            e.stopPropagation();
                            onSimulate(hab.id, rec?.relocation_site_id);
                          }}
                          className="p-1.5 rounded-lg bg-sm-green/20 hover:bg-sm-green/30 text-sm-green border border-sm-green/30 transition cursor-pointer"
                        >
                          <Compass className="w-4 h-4" />
                        </button>
                        <button
                          title="Recalculate with updated hazard inputs"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleOpenRecalcModal(hab);
                          }}
                          className="p-1.5 rounded-lg bg-sm-panel-2 hover:bg-sm-panel-2/80 text-sm-muted border border-sm-border transition cursor-pointer"
                        >
                          <RefreshCw className="w-4 h-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Recalculate Modal */}
      {recalcHabId && (
        <div
          id="recalc-modal-backdrop"
          className="fixed inset-0 bg-sm-bg/70 backdrop-blur-sm z-50 flex items-center justify-center p-4"
          onClick={() => setRecalcHabId(null)}
        >
          <div
            id="recalc-modal"
            className="bg-sm-panel rounded-xl shadow-2xl border border-sm-border max-w-md w-full p-5 space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="border-b border-sm-border pb-3">
              <h3 className="font-bold text-sm-text text-base">
                Recalculate Priority Index
              </h3>
              <p className="text-xs text-sm-muted">
                Simulate updated sensor or satellite survey inputs for{' '}
                <strong>
                  {habitations.find((h) => h.id === recalcHabId)?.village_name}
                </strong>
              </p>
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <div className="flex justify-between text-sm-muted mb-1">
                  <span>Landslide Risk Score</span>
                  <span className="font-bold">{recalcLandslide} / 100</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={recalcLandslide}
                  onChange={(e) => setRecalcLandslide(Number(e.target.value))}
                  className="w-full accent-red-600"
                />
              </div>

              <div>
                <div className="flex justify-between text-sm-muted mb-1">
                  <span>Flash Flood Risk Score</span>
                  <span className="font-bold">{recalcFlood} / 100</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={recalcFlood}
                  onChange={(e) => setRecalcFlood(Number(e.target.value))}
                  className="w-full accent-blue-600"
                />
              </div>

              <div>
                <div className="flex justify-between text-sm-muted mb-1">
                  <span>Extreme Rainfall Risk Score</span>
                  <span className="font-bold">{recalcRain} / 100</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={recalcRain}
                  onChange={(e) => setRecalcRain(Number(e.target.value))}
                  className="w-full accent-indigo-600"
                />
              </div>
            </div>

            <div className="pt-2 border-t border-sm-border flex items-center justify-end gap-2">
              <button
                onClick={() => setRecalcHabId(null)}
                className="px-3.5 py-2 rounded-lg text-xs font-semibold text-sm-muted hover:bg-sm-panel-2 border border-sm-border transition cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={handleExecuteRecalc}
                disabled={isRecalculating}
                className="px-4 py-2 rounded-lg text-xs font-bold text-slate-900 bg-sm-green hover:bg-sm-green-hover shadow-sm transition disabled:opacity-50 cursor-pointer"
              >
                {isRecalculating ? 'Recomputing...' : 'Apply & Update'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};