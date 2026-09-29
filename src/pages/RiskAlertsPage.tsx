import React from 'react';
import { AlertTriangle, CalendarDays, MapPin } from 'lucide-react';
import { HazardEvent, Habitation, RedZone } from '../types';
import { buildFocus, focusFromPoints } from '../lib/regionViewport';
import type { RegionViewportFocus } from '../lib/regionViewport';

interface RiskAlertsPageProps {
  redZones: RedZone[];
  events: HazardEvent[];
  habitations?: Habitation[];
  onLocateOnMap?: (focus: RegionViewportFocus) => void;
}

interface LatLng {
  latitude: number;
  longitude: number;
}

// GeoJSON [lng, lat] → {latitude, longitude}, flattened over polygon rings.
function geometryToPoints(zone_geometry: RedZone['zone_geometry']): LatLng[] {
  const out: LatLng[] = [];
  // zone_geometry.coordinates: Polygon → number[][][], MultiPolygon → number[][][][]
  const raw = zone_geometry.coordinates as unknown as number[][][];
  const rings = zone_geometry.type === 'MultiPolygon'
    ? (raw as unknown as number[][][][]).flat(1)
    : raw;
  rings.forEach((ring) => {
    ring.forEach(([lng, lat]) => out.push({ latitude: lat, longitude: lng }));
  });
  return out;
}

function zoneFocus(zone: RedZone): RegionViewportFocus | null {
  const points = geometryToPoints(zone.zone_geometry);
  return focusFromPoints(points, { lat: 30.42, lng: 79.35, zoom: 12 }, zone.zone_name);
}

function eventFocus(event: HazardEvent, habitations: Habitation[]): RegionViewportFocus | null {
  const hab = habitations.find((h) => h.id === event.habitation_id);
  if (!hab) return null;
  return buildFocus(
    { lat: hab.latitude, lng: hab.longitude, zoom: 14 },
    event.habitation_name || event.id,
    hab.id
  );
}

export const RiskAlertsPage: React.FC<RiskAlertsPageProps> = ({
  redZones,
  events,
  habitations = [],
  onLocateOnMap,
}) => (
  <div className="space-y-6 animate-in fade-in duration-200">
    <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-5">
      <div className="flex items-center gap-2 text-red-300">
        <AlertTriangle className="w-5 h-5" />
        <h2 className="font-bold text-lg">Risk alerts and active hazard zones</h2>
      </div>
      <p className="mt-1 text-sm text-red-300/90">View-only public safety information for the selected area.</p>
    </div>

    <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
      <section className="rounded-xl border border-sm-border bg-sm-panel shadow-sm overflow-hidden">
        <div className="border-b border-sm-border px-5 py-3 font-bold text-sm-text">Mapped risk zones</div>
        <div className="divide-y divide-sm-border">
          {redZones.map((zone) => {
            const focus = zoneFocus(zone);
            return (
              <article key={zone.id} className="p-4 flex gap-3">
                <AlertTriangle className="w-4 h-4 mt-0.5 text-red-400" />
                <div className="flex-1 min-w-0">
                  <h3 className="font-semibold text-sm text-sm-text">{zone.zone_name}</h3>
                  <p className="text-xs text-sm-muted mt-1">{zone.hazard_type} · {zone.risk_level} risk · score {zone.hazard_score}/100</p>
                  <div className="mt-2">
                    {onLocateOnMap && focus ? (
                      <button
                        id={`locate-zone-${zone.id}`}
                        onClick={() => onLocateOnMap(focus)}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-sm-green/20 hover:bg-sm-green/30 text-sm-green border border-sm-green/30 text-[11px] font-semibold transition cursor-pointer"
                      >
                        <MapPin className="w-3 h-3" />
                        Locate on map
                      </button>
                    ) : (
                      <span className="text-[11px] text-sm-muted">Location unavailable</span>
                    )}
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <section className="rounded-xl border border-sm-border bg-sm-panel shadow-sm overflow-hidden">
        <div className="border-b border-sm-border px-5 py-3 font-bold text-sm-text">Recent recorded events</div>
        <div className="divide-y divide-sm-border">
          {events.slice(0, 8).map((event) => {
            const focus = eventFocus(event, habitations);
            return (
              <article key={event.id} className="p-4 flex gap-3">
                <CalendarDays className="w-4 h-4 mt-0.5 text-amber-400" />
                <div className="flex-1 min-w-0">
                  <h3 className="font-semibold text-sm text-sm-text">{event.hazard_type}</h3>
                  <p className="text-xs text-sm-muted mt-1 flex items-center gap-1"><MapPin className="w-3 h-3" /> {event.habitation_name} · {event.event_date}</p>
                  <div className="mt-2">
                    {onLocateOnMap && focus ? (
                      <button
                        id={`locate-event-${event.id}`}
                        onClick={() => onLocateOnMap(focus)}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-sm-green/20 hover:bg-sm-green/30 text-sm-green border border-sm-green/30 text-[11px] font-semibold transition cursor-pointer"
                      >
                        <MapPin className="w-3 h-3" />
                        Locate on map
                      </button>
                    ) : (
                      <span className="text-[11px] text-sm-muted">Location unavailable</span>
                    )}
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      </section>
    </div>
  </div>
);