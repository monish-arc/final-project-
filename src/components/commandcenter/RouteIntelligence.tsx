import React, { useEffect, useRef, useState } from 'react';
import { Route as RouteIcon, CircleDot, CloudOff } from 'lucide-react';
import { SafeRoutesResponse, SafeRouteOption, BhuvanShortestPathResponse } from '../../types';
import type { RegionViewportFocus } from '../../lib/regionViewport';
import { apiService } from '../../services/api';
import { DataStatusBadge } from '../DataStatusBadge';

interface RouteIntelligenceProps {
  origin: { lat: number; lng: number; label: string } | null;
  destination: { lat: number; lng: number; label: string } | null;
  anchorKey: string;
  running: boolean;
  onSafeRouteChange: (route: SafeRouteOption | null) => void;
  onBhuvanRouteLoaded?: (route: BhuvanShortestPathResponse | null) => void;
  onLocateOnMap: (focus: RegionViewportFocus) => void;
}

export const RouteIntelligence: React.FC<RouteIntelligenceProps> = ({
  origin,
  destination,
  anchorKey,
  running,
  onSafeRouteChange,
  onBhuvanRouteLoaded,
  onLocateOnMap,
}) => {
  const [routes, setRoutes] = useState<SafeRoutesResponse | null>(null);
  const [bhuvan, setBhuvan] = useState<BhuvanShortestPathResponse | null>(null);
  const [chosenIdx, setChosenIdx] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const seqRef = useRef(0);

  useEffect(() => {
if (!origin || !destination) {
      setRoutes(null);
      setBhuvan(null);
      setChosenIdx(null);
      onSafeRouteChange(null);
      onBhuvanRouteLoaded?.(null);
      setLoading(false);
      return;
    }
    const seq = ++seqRef.current;
    setLoading(true);

    Promise.all([
      apiService
        .getSafeRoutes(origin.lat, origin.lng, destination.lat, destination.lng)
        .catch(() => null),
      apiService
        .bhuvanShortestPath(origin.lat, origin.lng, destination.lat, destination.lng)
        .catch(() => null),
    ]).then(([r, b]) => {
      if (seq !== seqRef.current) return;
      setRoutes(r);
      setBhuvan(b);
      onBhuvanRouteLoaded?.(b);
      setLoading(false);
      const options = r?.options ?? [];
      if (options.length > 0) {
        setChosenIdx(0);
        onSafeRouteChange(options[0] ?? null);
      } else {
        setChosenIdx(null);
        onSafeRouteChange(null);
      }
    });
    return () => {
      seqRef.current += 1;
      onSafeRouteChange(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anchorKey, origin, destination]);

  const options = routes?.options ?? [];
  const chosen = chosenIdx != null ? options[chosenIdx] ?? null : null;
  const shortestDist = bhuvan?.distance_km ?? null;
  const safestDist = options.length
    ? Math.min(...options.map((o) => o.distance_km ?? Infinity))
    : null;

  const hazardText = (h: Record<string, unknown> | undefined): string | null => {
    if (!h) return null;
    const zone = h.zone ?? h.zone_id;
    const hazard = h.hazard;
    if (zone && hazard) return `${hazard} · ${zone}`;
    if (zone) return String(zone);
    if (hazard) return String(hazard);
    return h.edge_id != null ? `Hazard on ${h.edge_id}` : null;
  };

  return (
    <section className="bg-sm-panel border border-sm-border rounded-xl shadow p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-1">
        <div className="flex items-center gap-2">
          <RouteIcon className="w-4 h-4 text-sm-green" />
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-sm-text">
              Route Intelligence
            </h3>
            <p className="text-[10px] text-sm-muted">
              Best route algorithms run only on engine results — “Safer Route” reflects real risk analysis.
            </p>
          </div>
        </div>
        {chosen && (
          <DataStatusBadge status={chosen.data_status ?? 'UNAVAILABLE'} title={chosen.data_source} />
        )}
      </div>

      <p className="text-[11px] text-sm-muted mb-3">
        {origin && destination ? (
          <>
            {origin.label} → {destination.label}
          </>
        ) : (
          'Select a source village and a safe location to evaluate routes.'
        )}
      </p>

      {loading || running ? (
        <p className="text-[11px] text-sm-muted">Evaluating routes…</p>
      ) : !origin || !destination ? (
        <p className="text-[11px] text-sm-muted">
          Choose a habitation anchor (route start) and a safe location (route end).
        </p>
      ) : options.length === 0 && !bhuvan ? (
        <p className="text-[11px] text-sm-muted">
          Neither safe-route engine nor Bhuvan network returned a path. Nothing fabricated.
        </p>
      ) : (
        <div className="space-y-3">
          {options.length > 0 && (
            <div className="space-y-2">
              <p className="text-[10px] font-bold uppercase tracking-wider text-sm-muted">
                Safe route engine ({routes?.routing_provider ?? routes?.data_source ?? 'engine'})
              </p>
              {options.map((o, idx) => (
                <button
                  key={`route-${idx}`}
                  onClick={() => {
                    setChosenIdx(idx);
                    onSafeRouteChange(o);
                  }}
                  className={`w-full text-left rounded-lg border p-2.5 transition cursor-pointer ${
                    idx === chosenIdx
                      ? 'border-emerald-500/60 bg-emerald-500/10'
                      : 'border-sm-border bg-sm-panel-2/60 hover:border-sm-border/80'
                  }`}
                >
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="inline-flex items-center gap-1.5 font-bold text-sm-text">
                      <CircleDot className="w-3 h-3 text-emerald-400" />
                      Safer Route {idx + 1}
                      {o.is_synthetic_route ? ' (synthetic — no mapped network)' : ''}
                    </span>
                    <span className="text-sm-muted">
                      {o.distance_km != null ? `${o.distance_km.toFixed(1)} km` : '—'} ·{' '}
                      {o.travel_time_min != null ? `${o.travel_time_min.toFixed(0)} min` : '—'}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-sm-muted">
                    <span>
                      Safety <b className="text-emerald-300">{o.safety_score ?? '—'}%</b>
                    </span>
                    <span>
                      Risk <b className="text-amber-300">{o.risk_score ?? '—'}</b>
                    </span>
                    {(o.hazards_encountered ?? [])
                      .map(hazardText)
                      .filter(Boolean)
                      .slice(0, 3)
                      .map((h, i) => (
                        <span key={i} className="text-red-300/80">
                          hazards: {h}
                        </span>
                      ))}
                    {o.assumption && <span className="italic text-sm-muted">Assumption: {o.assumption}</span>}
                  </div>
                </button>
              ))}
            </div>
          )}

          {bhuvan && (
            <div className="rounded-lg border border-sm-border bg-sm-panel-2/60 p-2.5 space-y-1">
              <div className="flex items-center justify-between text-[11px]">
                <span className="inline-flex items-center gap-1.5 font-bold text-sm-text">
                  <CloudOff className="w-3 h-3 text-violet-400" />
                  Bhuvan (ISRO) — shortest path
                </span>
                <span className="text-sm-muted">
                  {shortestDist != null ? `${shortestDist.toFixed(1)} km` : '—'}
                  {safestDist != null && safestDist < (shortestDist ?? Infinity)
                    ? ` (Safer Route adds ${(safestDist - shortestDist).toFixed(1)} km)`
                    : ''}
                </span>
              </div>
              <p className="text-[10px] text-sm-muted leading-snug">
                {bhuvan.coverage_note ?? 'Network coverage may be partial.'} The engineered
                Safer Route above, not this raw path, is the recommended evacuation path.
              </p>
            </div>
          )}

          {chosen?.route_geometry && (
            <p className="text-[10px] text-sm-muted">
              The recommended route is drawn on the map in emerald.
            </p>
          )}
        </div>
      )}

      {routes?.reason && options.length === 0 && (
        <p className="mt-2 text-[10px] text-sm-muted italic">{routes.reason}</p>
      )}
    </section>
  );
};