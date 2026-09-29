import React from 'react';
import {
  X,
  AlertTriangle,
  Users,
  Building2,
  HeartPulse,
  Navigation,
  History,
  ArrowRight,
  Shield,
} from 'lucide-react';
import { Habitation, HazardEvent, RelocationRecommendation } from '../types';
import { RiskBadge } from './RiskBadge';

interface VillageModalProps {
  habitation: Habitation | null;
  historicalEvents?: HazardEvent[];
  recommendation?: RelocationRecommendation;
  onClose: () => void;
  onSimulate?: (habitationId: string) => void;
  onPlanEvacuation?: (habitation: Habitation) => void;
}

export const VillageModal: React.FC<VillageModalProps> = ({
  habitation,
  historicalEvents = [],
  recommendation,
  onClose,
  onSimulate,
  onPlanEvacuation,
}) => {
  if (!habitation) return null;

  const dependentPercent = (
    ((habitation.children_count + habitation.elderly_count) / habitation.population) *
    100
  ).toFixed(1);

  return (
    <div
      id="village-details-modal-backdrop"
      className="fixed inset-0 bg-sm-bg/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 overflow-y-auto"
      onClick={onClose}
    >
      <div
        id="village-details-modal"
        className="bg-sm-panel rounded-xl shadow-2xl border border-sm-border max-w-2xl w-full overflow-hidden text-sm-text animate-in fade-in zoom-in-95 duration-150 my-8"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div className="bg-sm-bg text-sm-text p-5 flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="font-mono text-xs text-red-400 bg-red-950/80 px-2 py-0.5 rounded border border-red-800">
                {habitation.village_code}
              </span>
              <RiskBadge level={habitation.priority_level} size="sm" />
            </div>
            <h2 className="text-xl font-bold tracking-tight">{habitation.village_name}</h2>
            <p className="text-xs text-sm-muted">
              {habitation.district} District, {habitation.state} | Geo: {habitation.latitude.toFixed(4)}°N, {habitation.longitude.toFixed(4)}°E
            </p>
          </div>
          <button
            id="close-village-modal-btn"
            onClick={onClose}
            className="p-1.5 rounded-lg text-sm-muted hover:text-sm-text hover:bg-white/5 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 space-y-6 max-h-[75vh] overflow-y-auto">
          {/* Key Priority Score Banner */}
          <div className="bg-sm-panel-2 border border-sm-border rounded-lg p-4 flex flex-wrap items-center justify-between gap-4">
            <div>
              <span className="text-xs font-semibold text-sm-muted uppercase tracking-wider block">
                Relocation Priority Score
              </span>
              <div className="flex items-baseline gap-2 mt-0.5">
                <span className="text-3xl font-extrabold text-sm-text">
                  {habitation.priority_score}
                </span>
                <span className="text-xs text-sm-muted font-medium">/ 100 max index</span>
              </div>
            </div>
            <div className="flex gap-4">
              <div className="text-center px-3 py-1 bg-sm-bg rounded border border-sm-border">
                <span className="text-[10px] text-sm-muted block font-medium">Hazard Score (50%)</span>
                <span className="text-base font-bold text-red-400">{habitation.hazard_score}</span>
              </div>
              <div className="text-center px-3 py-1 bg-sm-bg rounded border border-sm-border">
                <span className="text-[10px] text-sm-muted block font-medium">Vulnerability (30%)</span>
                <span className="text-base font-bold text-amber-400">{habitation.vulnerability_score}</span>
              </div>
              <div className="text-center px-3 py-1 bg-sm-bg rounded border border-sm-border">
                <span className="text-[10px] text-sm-muted block font-medium">History (20%)</span>
                <span className="text-base font-bold text-blue-400">
                  {Math.min(100, habitation.disaster_history_count * 16)}
                </span>
              </div>
            </div>
          </div>

          {/* Demographic Metrics */}
          <div>
            <h3 className="text-xs font-bold text-sm-muted uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <Users className="w-3.5 h-3.5 text-sm-green" /> Demographic Profile
            </h3>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
              <div className="p-2.5 bg-sm-panel-2 rounded-lg border border-sm-border">
                <span className="text-sm-muted block">Total Population</span>
                <span className="text-sm font-bold text-sm-text">{habitation.population.toLocaleString()}</span>
              </div>
              <div className="p-2.5 bg-sm-panel-2 rounded-lg border border-sm-border">
                <span className="text-sm-muted block">Households</span>
                <span className="text-sm font-bold text-sm-text">{habitation.households.toLocaleString()}</span>
              </div>
              <div className="p-2.5 bg-sm-panel-2 rounded-lg border border-sm-border">
                <span className="text-sm-muted block">Dependents Ratio</span>
                <span className="text-sm font-bold text-sm-text">{dependentPercent}%</span>
              </div>
              <div className="p-2.5 bg-sm-panel-2 rounded-lg border border-sm-border">
                <span className="text-sm-muted block">Hospital Distance</span>
                <span className="text-sm font-bold text-sm-text">{habitation.hospital_distance_km} km</span>
              </div>
            </div>
          </div>

          {/* Multi-Hazard Sub-Factor Breakdown */}
          <div>
            <h3 className="text-xs font-bold text-sm-muted uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5 text-red-400" /> Hazard Component Breakdown
            </h3>
            <div className="space-y-2 text-xs">
              <div>
                <div className="flex justify-between text-sm-muted mb-1">
                  <span>Landslide / Slope Instability (40% weight)</span>
                  <span className="font-semibold text-sm-text">{habitation.landslide_risk} / 100</span>
                </div>
                <div className="h-2 bg-sm-bg rounded-full overflow-hidden">
                  <div
                    className="h-full bg-red-500 rounded-full"
                    style={{ width: `${habitation.landslide_risk}%` }}
                  />
                </div>
              </div>
              <div>
                <div className="flex justify-between text-sm-muted mb-1">
                  <span>Flash Flood / Inundation (30% weight)</span>
                  <span className="font-semibold text-sm-text">{habitation.flood_risk} / 100</span>
                </div>
                <div className="h-2 bg-sm-bg rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-500 rounded-full"
                    style={{ width: `${habitation.flood_risk}%` }}
                  />
                </div>
              </div>
              <div>
                <div className="flex justify-between text-sm-muted mb-1">
                  <span>Extreme Rainfall / Cloudburst (20% weight)</span>
                  <span className="font-semibold text-sm-text">{habitation.extreme_rainfall_risk} / 100</span>
                </div>
                <div className="h-2 bg-sm-bg rounded-full overflow-hidden">
                  <div
                    className="h-full bg-indigo-500 rounded-full"
                    style={{ width: `${habitation.extreme_rainfall_risk}%` }}
                  />
                </div>
              </div>
              <div>
                <div className="flex justify-between text-sm-muted mb-1">
                  <span>Past Disaster Frequency (10% weight)</span>
                  <span className="font-semibold text-sm-text">{habitation.past_disaster_frequency} / 100</span>
                </div>
                <div className="h-2 bg-sm-bg rounded-full overflow-hidden">
                  <div
                    className="h-full bg-amber-500 rounded-full"
                    style={{ width: `${habitation.past_disaster_frequency}%` }}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Geological Notes */}
          {habitation.notes && (
            <div className="p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg text-xs text-amber-200">
              <span className="font-bold block mb-0.5">Geological & Field Assessment Note:</span>
              <p>{habitation.notes}</p>
            </div>
          )}

          {/* Historical Disasters List */}
          {historicalEvents.length > 0 && (
            <div>
              <h3 className="text-xs font-bold text-sm-muted uppercase tracking-wider mb-2 flex items-center gap-1.5">
                <History className="w-3.5 h-3.5 text-purple-400" /> Recorded Historical Events ({historicalEvents.length})
              </h3>
              <div className="space-y-2 max-h-40 overflow-y-auto text-xs pr-1">
                {historicalEvents.map((evt) => (
                  <div
                    key={evt.id}
                    className="p-2.5 bg-sm-panel-2 rounded border border-sm-border flex justify-between items-start"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-sm-text">{evt.hazard_type}</span>
                        <span className="text-[10px] text-sm-muted">{evt.event_date}</span>
                      </div>
                      <p className="text-[11px] text-sm-muted mt-0.5">{evt.intensity}</p>
                    </div>
                    <div className="text-right text-[11px]">
                      <span className="text-red-400 font-medium">{evt.affected_people} affected</span>
                      {evt.houses_damaged > 0 && (
                        <span className="text-sm-muted block">{evt.houses_damaged} homes damaged</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Relocation Recommendation Section */}
          {recommendation && (
            <div className="p-4 bg-emerald-500/10 border border-emerald-500/30 rounded-lg text-xs text-emerald-100 space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-bold flex items-center gap-1.5 text-emerald-300">
                  <Shield className="w-4 h-4 text-emerald-400" /> Proposed Relocation Allocation
                </span>
                <span className="bg-emerald-500/20 text-emerald-300 font-semibold px-2 py-0.5 rounded text-[10px]">
                  {recommendation.status}
                </span>
              </div>
              <p className="text-sm-text/90">{recommendation.explanation}</p>
              <div className="flex items-center justify-between pt-1 border-t border-emerald-500/30 font-medium">
                <span>Destination: <strong>{recommendation.relocation_site_name}</strong></span>
                <span className="text-emerald-300">Estimated Hazard Reduction: <strong>{recommendation.risk_reduction_percent}%</strong></span>
              </div>
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="bg-sm-panel-2 px-6 py-4 border-t border-sm-border flex items-center justify-between">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-xs font-semibold text-sm-muted hover:text-sm-text bg-sm-panel-2 hover:bg-white/5 border border-sm-border transition cursor-pointer"
          >
            Close
          </button>
          <div className="flex items-center gap-2">
            {onPlanEvacuation && (
              <button
                id={`evacuate-modal-btn-${habitation.id}`}
                onClick={() => {
                  onPlanEvacuation(habitation);
                  onClose();
                }}
                className="flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold text-white bg-emerald-600 hover:bg-emerald-700 shadow-sm transition cursor-pointer"
              >
                <span>Plan Evacuation Route</span>
                <Navigation className="w-3.5 h-3.5" />
              </button>
            )}
            {onSimulate && (
              <button
                id={`simulate-modal-btn-${habitation.id}`}
                onClick={() => {
                  onSimulate(habitation.id);
                  onClose();
                }}
                className="flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold text-slate-950 bg-sm-green hover:bg-sm-green-hover shadow-sm transition cursor-pointer"
              >
                <span>Simulate Relocation</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
