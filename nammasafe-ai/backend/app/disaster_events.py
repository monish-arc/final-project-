"""Disaster-events service: historical, real, curated events (provenance data).

The table is seeded from backend/scripts/seed_disaster_events.py with real,
well-documented India events and public source references. Nothing in this
module fabricates an event — rows without a source reference are rejected by the
seeding script.

Status contract: every payload carries data_status="HISTORICAL".
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.geo import haversine
from app.models import DisasterEvent

STATUS = "HISTORICAL"


def to_dict(event: DisasterEvent) -> Dict[str, Any]:
    return {
        "id": event.id,
        "name": event.name,
        "hazard_type": event.hazard_type,
        "event_date": event.event_date.isoformat(),
        "state": event.state,
        "district": event.district,
        "latitude": event.latitude,
        "longitude": event.longitude,
        "severity_level": event.severity_level,
        "affected_population": event.affected_population,
        "fatalities": event.fatalities,
        "damage_estimate_inr_crore": event.damage_estimate_inr_crore,
        "description": event.description,
        "source": event.source,
        "source_reference": event.source_reference,
        "data_status": event.data_status or STATUS,
    }


def get_disaster_events(
    db: Session,
    state: Optional[str] = None,
    district: Optional[str] = None,
    hazard_type: Optional[str] = None,
    limit: int = 200,
) -> Dict[str, Any]:
    stmt = select(DisasterEvent).order_by(DisasterEvent.event_date.desc())
    if state:
        stmt = stmt.where(DisasterEvent.state.ilike(f"%{state}%"))
    if district:
        stmt = stmt.where(DisasterEvent.district.ilike(f"%{district}%"))
    if hazard_type:
        stmt = stmt.where(DisasterEvent.hazard_type == hazard_type.upper())
    events = db.execute(stmt.limit(limit)).scalars().all()
    return {
        "data_status": STATUS,
        "total": len(events),
        "events": [to_dict(event) for event in events],
    }


def get_disaster_events_near(
    db: Session,
    latitude: float,
    longitude: float,
    radius_km: Optional[float] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """Events within a radius; bounding-box prefilter + exact haversine check.

    Kept dependency-free (works on both SQLite local runs and PostGIS).
    """
    radius = radius_km if (radius_km and radius_km > 0) else 50.0
    # ~1 degree lat ~= 111 km; pad a little with longitude scaling.
    pad = min(5.0, radius / 111.0)
    stmt = select(DisasterEvent).where(
        DisasterEvent.latitude.between(latitude - pad, latitude + pad),
        DisasterEvent.longitude.between(longitude - pad, longitude + pad),
    ).order_by(DisasterEvent.event_date.desc())
    candidates = db.execute(stmt.limit(2000)).scalars().all()

    events = []
    for event in candidates:
        distance_km = haversine(latitude, longitude, event.latitude, event.longitude) / 1000.0
        if distance_km <= radius:
            entry = to_dict(event)
            entry["distance_km"] = round(distance_km, 2)
            events.append(entry)
    events.sort(key=lambda entry: entry["distance_km"])
    return {
        "data_status": STATUS,
        "center": {"latitude": round(latitude, 6), "longitude": round(longitude, 6)},
        "radius_km": round(radius, 1),
        "total": len(events[:limit]),
        "events": events[:limit],
    }


def count_events(db: Session) -> int:
    return int(db.execute(select(DisasterEvent.id).count()).scalar() or 0)