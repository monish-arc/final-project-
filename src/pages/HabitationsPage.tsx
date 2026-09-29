import React, { useState } from 'react';
import {
  Search,
  Filter,
  SlidersHorizontal,
  Home,
  Users,
  AlertTriangle,
  ArrowUpDown,
  Compass,
  ArrowRight,
  Navigation,
} from 'lucide-react';
import { Habitation } from '../types';
import { RiskBadge } from '../components/RiskBadge';

interface HabitationsPageProps {
  habitations: Habitation[];
  onSelectHabitation: (hab: Habitation) => void;
  onSimulateHabitation: (habId: string) => void;
  onPlanEvacuation?: (hab: Habitation) => void;
}

export const HabitationsPage: React.FC<HabitationsPageProps> = ({
  habitations,
  onSelectHabitation,
  onSimulateHabitation,
  onPlanEvacuation,
}) => {
  const [search, setSearch] = useState('');
  const [priorityFilter, setPriorityFilter] = useState('all');
  const [sortBy, setSortBy] = useState<'priority' | 'population' | 'hazard' | 'vulnerability'>('priority');

  const filtered = habitations
    .filter((h) => {
      const matchSearch =
        h.village_name.toLowerCase().includes(search.toLowerCase()) ||
        h.village_code.toLowerCase().includes(search.toLowerCase());
      const matchPriority =
        priorityFilter === 'all' || h.priority_level.toLowerCase() === priorityFilter.toLowerCase();
      return matchSearch && matchPriority;
    })
    .sort((a, b) => {
      if (sortBy === 'priority') return b.priority_score - a.priority_score;
      if (sortBy === 'population') return b.population - a.population;
      if (sortBy === 'hazard') return b.hazard_score - a.hazard_score;
      if (sortBy === 'vulnerability') return b.vulnerability_score - a.vulnerability_score;
      return 0;
    });

  return (
    <div id="habitations-view" className="space-y-5 animate-in fade-in duration-200">
      {/* Header */}
      <div className="bg-sm-panel p-5 rounded-xl border border-sm-border shadow-sm flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-sm-text tracking-tight flex items-center gap-2">
            <Home className="w-5 h-5 text-red-400" />
            <span>Habitations & Vulnerability Registry</span>
          </h2>
          <p className="text-xs text-sm-muted mt-0.5">
            Geolocated census habitations across Chamoli district with quantified multi-hazard exposure
          </p>
        </div>

        <div className="flex items-center gap-2 text-xs">
          <span className="bg-red-500/10 text-red-300 border border-red-500/30 px-3 py-1.5 rounded-lg font-medium">
            5 Immediate Relocation
          </span>
          <span className="bg-amber-500/10 text-amber-300 border border-amber-500/30 px-3 py-1.5 rounded-lg font-medium">
            5 Short-Term Relocation
          </span>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="bg-sm-panel p-4 rounded-xl border border-sm-border shadow-sm flex flex-wrap items-center justify-between gap-3">
        <div className="flex-1 min-w-0 relative">
          <Search className="w-4 h-4 text-sm-muted absolute left-3 top-2.5" />
          <input
            id="habitations-search-input"
            type="text"
            placeholder="Search village name or code (e.g. Joshimath, Raini, VIL-CHM-001)..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-2 rounded-lg bg-sm-panel-2 border border-sm-border text-xs text-sm-text placeholder-sm-muted focus:bg-sm-panel-2 focus:outline-none focus:ring-2 focus:ring-sm-green/40 focus:border-sm-green"
          />
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 text-xs text-sm-muted">
            <Filter className="w-3.5 h-3.5 text-sm-muted" />
            <span>Tier:</span>
            <select
              id="habitations-priority-filter"
              value={priorityFilter}
              onChange={(e) => setPriorityFilter(e.target.value)}
              className="bg-sm-panel-2 border border-sm-border text-sm-text rounded-lg px-2.5 py-1.5 text-xs focus:ring-1 focus:ring-sm-green outline-none"
            >
              <option value="all">All Priority Tiers</option>
              <option value="immediate relocation">Immediate Relocation (75+)</option>
              <option value="short-term relocation">Short-Term Relocation (50-74)</option>
              <option value="medium-term relocation">Medium-Term Relocation (30-49)</option>
            </select>
          </div>

          <div className="flex items-center gap-1.5 text-xs text-sm-muted">
            <ArrowUpDown className="w-3.5 h-3.5 text-sm-muted" />
            <span>Sort:</span>
            <select
              id="habitations-sort-by"
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as any)}
              className="bg-sm-panel-2 border border-sm-border text-sm-text rounded-lg px-2.5 py-1.5 text-xs focus:ring-1 focus:ring-sm-green outline-none"
            >
              <option value="priority">Priority Score (Highest)</option>
              <option value="population">Population</option>
              <option value="hazard">Hazard Score</option>
              <option value="vulnerability">Vulnerability Score</option>
            </select>
          </div>
        </div>
      </div>

      {/* Habitations Grid Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filtered.map((hab) => {
          const dependentPercent = (
            ((hab.children_count + hab.elderly_count) / hab.population) *
            100
          ).toFixed(0);

          const borderLeftClass =
            hab.priority_score >= 75
              ? 'border-l-4 border-l-red-500'
              : hab.priority_score >= 50
              ? 'border-l-4 border-l-orange-500'
              : hab.priority_score >= 30
              ? 'border-l-4 border-l-yellow-500'
              : 'border-l-4 border-l-emerald-500';

          return (
            <div
              key={hab.id}
              id={`hab-card-${hab.id}`}
              className={`bg-sm-panel rounded-xl border border-sm-border shadow-sm hover:shadow-md transition p-5 flex flex-col justify-between space-y-4 ${borderLeftClass}`}
            >
              <div>
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div>
                    <span className="text-[10px] font-mono text-sm-muted uppercase">
                      {hab.village_code}
                    </span>
                    <h3 className="text-base font-bold text-sm-text line-clamp-1">
                      {hab.village_name}
                    </h3>
                  </div>
                  <RiskBadge level={hab.priority_level} size="sm" />
                </div>

                <p className="text-xs text-sm-muted line-clamp-2 leading-relaxed">
                  {hab.notes}
                </p>

                {/* Score Indicators */}
                <div className="grid grid-cols-3 gap-2 mt-4 text-center">
                  <div className="bg-sm-panel-2 p-2 rounded border border-sm-border">
                    <span className="text-[10px] text-sm-muted block font-medium">Priority</span>
                    <span className="text-base font-extrabold text-sm-text">
                      {hab.priority_score}
                    </span>
                  </div>
                  <div className="bg-red-500/10 p-2 rounded border border-red-500/20">
                    <span className="text-[10px] text-red-400 block font-medium">Hazard (50%)</span>
                    <span className="text-base font-bold text-red-400">{hab.hazard_score}</span>
                  </div>
                  <div className="bg-amber-500/10 p-2 rounded border border-amber-500/20">
                    <span className="text-[10px] text-amber-400 block font-medium">Vuln (30%)</span>
                    <span className="text-base font-bold text-amber-400">{hab.vulnerability_score}</span>
                  </div>
                </div>

                {/* Demographics Bar */}
                <div className="mt-3 pt-3 border-t border-sm-border grid grid-cols-3 text-[11px] text-sm-muted">
                  <div>
                    <span className="text-sm-muted block text-[10px]">Population</span>
                    <span className="font-semibold">{hab.population.toLocaleString()}</span>
                  </div>
                  <div>
                    <span className="text-sm-muted block text-[10px]">Dependents</span>
                    <span className="font-semibold">{dependentPercent}%</span>
                  </div>
                  <div>
                    <span className="text-sm-muted block text-[10px]">Hospital Dist</span>
                    <span className="font-semibold">{hab.hospital_distance_km} km</span>
                  </div>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex items-center gap-2 pt-2 border-t border-sm-border">
                <button
                  id={`inspect-hab-${hab.id}`}
                  onClick={() => onSelectHabitation(hab)}
                  className="flex-1 px-3 py-2 rounded-lg bg-sm-panel-2 hover:bg-sm-panel-2/80 text-sm-text text-xs font-semibold border border-sm-border transition cursor-pointer"
                >
                  Analyze Risk
                </button>
                <button
                  id={`simulate-hab-${hab.id}`}
                  onClick={() => onSimulateHabitation(hab.id)}
                  title="Simulate in Relocation Simulator"
                  className="px-3 py-2 rounded-lg bg-sm-green hover:bg-sm-green-hover text-slate-900 text-xs font-semibold flex items-center gap-1 shadow-sm transition cursor-pointer"
                >
                  <Compass className="w-3.5 h-3.5" />
                  <span>Simulate</span>
                </button>
                {onPlanEvacuation && (
                  <button
                    id={`evacuate-hab-${hab.id}`}
                    onClick={() => onPlanEvacuation(hab)}
                    title="Plan a safe evacuation route"
                    className="px-3 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold flex items-center gap-1 shadow-sm transition cursor-pointer"
                  >
                    <Navigation className="w-3.5 h-3.5" />
                    <span>Evacuate</span>
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};