import React from 'react';
import { MapPin, Star } from 'lucide-react';
import { SafeLocation } from '../../types';

interface SafeLocationsCardsProps {
  locations: SafeLocation[];
  loading: boolean;
  anchor: { lat: number; lng: number; label: string } | null;
}

export const SafeLocationsCards: React.FC<SafeLocationsCardsProps> = ({ locations, loading, anchor }) => {
  return (
    <section className="bg-sm-panel border border-sm-border rounded-xl shadow p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <MapPin className="w-4 h-4 text-emerald-400" />
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-sm-text">
              Safe Locations & Capacity
            </h3>
            <p className="text-[10px] text-sm-muted">
              {anchor
                ? `Shortlisted for ${anchor.label} — judged by suitability, not by assumption.`
                : 'Select an anchor habitation to shortlist safe locations.'}
            </p>
          </div>
        </div>
        <span className="text-[11px] text-sm-muted">{locations.length} candidates</span>
      </div>

      {loading ? (
        <p className="text-[11px] text-sm-muted">Searching safe locations…</p>
      ) : locations.length === 0 ? (
        <p className="text-[11px] text-sm-muted">
          {anchor
            ? 'No safe-location candidates returned for this point.'
            : 'No anchor selected.'}
        </p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
          {locations.map((loc, i) => {
            const estimated = loc.data_grade === 'ESTIMATE';
            const riskBand = String(loc.risk_band ?? '').replace(/_/g, ' ');
            return (
              <div key={loc.id ?? i} className="rounded-lg border border-sm-border bg-sm-panel-2/60 p-3 space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-xs font-bold text-sm-text">
                      {loc.name}
                      <span className="text-[10px] font-normal text-sm-muted"> · {String(loc.kind).replace(/_/g, ' ')}</span>
                    </p>
                    <span className={`inline-flex items-center gap-1 mt-1 px-1.5 py-0.5 rounded border text-[9px] font-bold ${
                      estimated
                        ? 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                        : 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                    }`}>
                      {estimated ? 'Estimated' : 'Reported/Curated'}
                    </span>
                    {riskBand && (
                      <span className="ml-1 text-[9px] text-sm-muted uppercase">{riskBand} risk</span>
                    )}
                  </div>
                  <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-300">
                    <Star className="w-3.5 h-3.5" />
                    {loc.suitability_score != null ? Math.round(loc.suitability_score) : '—'}
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-2 text-[11px]">
                  <span className="text-sm-muted">
                    Distance{' '}
                    <b className="text-sm-text">
                      {loc.distance_km != null ? `${loc.distance_km.toFixed(1)} km` : 'not computed'}
                    </b>
                  </span>
                  <span className="text-sm-muted">
                    Capacity{' '}
                    <b className="text-sm-text">
                      {loc.available_capacity_families != null
                        ? `${loc.available_capacity_families} fam`
                        : loc.capacity_families != null
                          ? `${loc.capacity_families} fam`
                          : '—'}
                    </b>
                  </span>
                </div>

                <p className="text-[10px] text-sm-muted leading-snug">
                  {loc.reason || 'No reason attached.'}
                </p>

                {(loc.features ?? []).length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {loc.features.slice(0, 4).map((f) => (
                      <span key={f} className="text-[9px] px-1.5 py-0.5 rounded bg-sm-bg border border-sm-border text-sm-muted">
                        {String(f).replace(/_/g, ' ')}
                      </span>
                    ))}
                  </div>
                )}

                {(loc.toilets != null || loc.drinking_water != null || loc.electricity != null || loc.medical_facility != null) && (
                  <div className="flex flex-wrap gap-1">
                    {loc.drinking_water != null && (
                      <span className="text-[9px] px-1.5 py-0.5 rounded bg-sky-500/20 text-sky-300">
                        Water {loc.drinking_water ? 'yes' : 'no'}
                      </span>
                    )}
                    {loc.toilets != null && (
                      <span className="text-[9px] px-1.5 py-0.5 rounded bg-sky-500/20 text-sky-300">
                        {loc.toilets} toilets
                      </span>
                    )}
                    {loc.electricity != null && (
                      <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300">
                        Power {loc.electricity ? 'yes' : 'no'}
                      </span>
                    )}
                    {loc.medical_facility != null && (
                      <span className="text-[9px] px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300">
                        Medical {loc.medical_facility ? 'yes' : 'no'}
                      </span>
                    )}
                    {loc.verified != null && (
                      <span className={`text-[9px] px-1.5 py-0.5 rounded ${loc.verified ? 'bg-emerald-500/20 text-emerald-300' : 'bg-amber-500/20 text-amber-300'}`}>
                        {loc.verified ? 'Verified' : 'Unverified'}{loc.last_verified ? ` · ${loc.last_verified}` : ''}
                      </span>
                    )}
                  </div>
                )}

                <p className="text-[9px] text-sm-muted pt-1 border-t border-sm-border">
                  {loc.data_source || 'Data source —'}
                </p>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
};