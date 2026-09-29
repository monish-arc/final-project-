import React from 'react';
import { ShieldAlert, ArrowRight } from 'lucide-react';
import { Habitation, RegionSelection } from '../../types';
import { RiskBadge } from '../RiskBadge';

interface HabitationRiskTableProps {
  habitations: Habitation[];
  region: RegionSelection;
  activeHabId?: string | null;
  onSelectHabitation: (hab: Habitation) => void;
}

export const HabitationRiskTable: React.FC<HabitationRiskTableProps> = ({
  habitations,
  region,
  activeHabId,
  onSelectHabitation,
}) => {
  const stateName = region.state?.name ?? 'this state';
  const districtName = region.district?.name ?? 'selected district';
  const sorted = [...habitations].sort((a, b) => (b.priority_score ?? 0) - (a.priority_score ?? 0));

  return (
    <section className="bg-sm-panel border border-sm-border rounded-xl shadow overflow-hidden">
      <div className="px-4 py-3 border-b border-sm-border flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <ShieldAlert className="w-4 h-4 text-red-400" />
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-sm-text">
              Habitation Risk Intelligence
            </h3>
            <p className="text-[10px] text-sm-muted">
              Only {stateName} / {districtName} — ranked by the relocation priority engine.
            </p>
          </div>
        </div>
        <span className="text-[11px] text-sm-muted">{sorted.length} habitations</span>
      </div>

      {sorted.length === 0 ? (
        <p className="text-[11px] text-sm-muted p-4">
          No surveyed habitations for {region.district?.name || region.state?.name || 'the selected location'}.
          Select a State and District with monitored villages.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-sm-text">
            <thead className="bg-sm-panel-2 text-sm-muted uppercase tracking-wider font-semibold border-b border-sm-border">
              <tr>
                <th className="px-4 py-2.5">Village</th>
                <th className="px-3 py-2.5">Priority</th>
                <th className="px-3 py-2.5">Level</th>
                <th className="px-3 py-2.5">Hazard</th>
                <th className="px-3 py-2.5">Vulnerability</th>
                <th className="px-3 py-2.5">Population</th>
                <th className="px-4 py-2.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-sm-border">
              {sorted.map((hab) => {
                const active = hab.id === activeHabId;
                return (
                  <tr
                    key={hab.id}
                    onClick={() => onSelectHabitation(hab)}
                    className={`cursor-pointer transition ${
                      active ? 'bg-sm-green/10 hover:bg-sm-green/15' : 'hover:bg-white/5'
                    }`}
                  >
                    <td className="px-4 py-2.5">
                      <span className="font-bold text-sm-text block">{hab.village_name}</span>
                      <span className="text-[10px] text-sm-muted font-mono">{hab.village_code}</span>
                    </td>
                    <td className="px-3 py-2.5 font-extrabold text-sm-text">{hab.priority_score}</td>
                    <td className="px-3 py-2.5">
                      <RiskBadge level={hab.priority_level} size="sm" />
                    </td>
                    <td className="px-3 py-2.5 text-red-300 font-semibold">{hab.hazard_score}</td>
                    <td className="px-3 py-2.5 text-amber-300 font-semibold">{hab.vulnerability_score}</td>
                    <td className="px-3 py-2.5">
                      {hab.population.toLocaleString()}{' '}
                      <span className="text-[10px] text-sm-muted">({hab.households} hh)</span>
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelectHabitation(hab);
                        }}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-sm-green/20 border border-sm-green/30 text-sm-green hover:bg-sm-green/30 font-semibold text-[11px] transition cursor-pointer"
                      >
                        Analyze Risk <ArrowRight className="w-3 h-3" />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
};