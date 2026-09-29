import React, { useEffect, useRef, useState } from 'react';
import { Hospital, School, GraduationCap, Home, Landmark } from 'lucide-react';
import { NearbyPlacesResponse } from '../../types';
import type { RegionViewportFocus } from '../../lib/regionViewport';
import { apiService } from '../../services/api';
import { DataStatusBadge } from '../DataStatusBadge';

interface EmergencyServicesRowProps {
  anchor: { lat: number; lng: number; label: string } | null;
  anchorKey: string;
  onLocateOnMap: (focus: RegionViewportFocus) => void;
}

const KINDS: Array<{ key: string; label: string; icon: React.ReactNode }> = [
  { key: 'hospitals', label: 'Hospitals & clinics', icon: <Hospital className="w-3.5 h-3.5" /> },
  { key: 'schools', label: 'Schools', icon: <School className="w-3.5 h-3.5" /> },
  { key: 'colleges', label: 'Colleges & universities', icon: <GraduationCap className="w-3.5 h-3.5" /> },
  { key: 'facilities', label: 'Police · Fire · Shelter', icon: <Landmark className="w-3.5 h-3.5" /> },
  { key: 'bridges', label: 'Bridges', icon: <Home className="w-3.5 h-3.5" /> },
];

export const EmergencyServicesRow: React.FC<EmergencyServicesRowProps> = ({
  anchor,
  anchorKey,
  onLocateOnMap,
}) => {
  const [byKind, setByKind] = useState<Record<string, NearbyPlacesResponse | null>>({});
  const [loading, setLoading] = useState(false);
  const seqRef = useRef(0);

  useEffect(() => {
    if (!anchor) {
      setByKind({});
      setLoading(false);
      return;
    }
    const seq = ++seqRef.current;
    setLoading(true);
    Promise.all(
      KINDS.map((k) =>
        apiService
          .getNearby(k.key, anchor.lat, anchor.lng, 10)
          .then((res) => ({ key: k.key, res }))
          .catch(() => ({ key: k.key, res: null }))
      )
    ).then((results) => {
      if (seq !== seqRef.current) return;
      const next: Record<string, NearbyPlacesResponse | null> = {};
      results.forEach((r) => {
        next[r.key] = r.res;
      });
      setByKind(next);
      setLoading(false);
    });
    return () => {
      seqRef.current += 1;
    };
  }, [anchorKey, anchor]);

  const anyLive = KINDS.some((k) => byKind[k.key]?.data_status === 'LIVE');
  const spans = KINDS.length === 5 ? 3 : 2;

  return (
    <section className="bg-sm-panel border border-sm-border rounded-xl shadow p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <h3 className="text-xs font-bold uppercase tracking-wider text-sm-text">
          Emergency services near anchor
        </h3>
        <span className="text-[10px] text-sm-muted">
          {anchor ? `Around ${anchor.label}` : 'No anchor selected'} · OpenStreetMap (Overpass)
        </span>
      </div>

      {!anchor ? (
        <p className="text-[11px] text-sm-muted">
          Select a habitation from the control bar to load nearby emergency services.
        </p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {KINDS.map((k) => {
            const res = byKind[k.key];
            const places = res?.places ?? [];
            return (
              <div key={k.key} className="rounded-lg border border-sm-border bg-sm-panel-2/60 p-3">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="inline-flex items-center gap-1.5 text-[11px] font-bold text-sm-text">
                    {k.icon} {k.label}
                  </span>
                  <DataStatusBadge
                    status={res?.data_status ?? (loading ? null : 'UNAVAILABLE')}
                    title={res?.reason || 'OpenStreetMap (Overpass API)'}
                  />
                </div>
                {loading ? (
                  <p className="text-[10px] text-sm-muted">Fetching…</p>
                ) : places.length === 0 ? (
                  <p className="text-[10px] text-sm-muted">
                    {res?.reason ?? 'No facilities within radius.'}
                  </p>
                ) : (
                  <ul className="space-y-1">
                    {places.slice(0, 3).map((p, i) => (
                      <li
                        key={`${p.osm_id ?? p.name}-${i}`}
                        className="flex items-center justify-between gap-2 text-[11px] text-sm-muted"
                      >
                        <span className="truncate">{p.name}</span>
                        <button
                          onClick={() =>
                            onLocateOnMap({
                              lat: p.latitude,
                              lng: p.longitude,
                              zoom: 15,
                              key: `nearby-${k.key}-${p.osm_id ?? p.name}`,
                              label: `${k.label}: ${p.name}`,
                            })
                          }
                          className="shrink-0 text-sm-green hover:text-sm-green-hover font-semibold cursor-pointer"
                        >
                          {p.distance_km?.toFixed(1)} km
                        </button>
                      </li>
                    ))}
                    {places.length > 3 && (
                      <li className="text-[10px] text-sm-muted">+ {places.length - 3} more</li>
                    )}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      )}

      <p className="mt-3 text-[10px] text-sm-muted">
        {anchor
          ? anyLive
            ? 'Live results from OpenStreetMap (Overpass API), rate-limited and cached.'
            : 'OpenStreetMap unreachable or returned nothing for this radius — no fabricated facilities.'
          : ''}
      </p>
    </section>
  );
};