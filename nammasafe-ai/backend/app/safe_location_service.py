"""Safe-location ranking engine.

Candidates come from two sources:
  * curated relocation_sites (kind=relocation_site, dataGrade derived from seed)
  * OpenStreetMap schools / colleges / community facilities (kind=school |
    college | facility, dataGrade=ESTIMATE)

Filtering rule: any candidate whose *estimated* risk band is HIGH or CRITICAL is
excluded from recommendations. Estimates:
  * relocation_sites -> derived transparently from low_hazard_score/suitability
  * OSM places        -> derived from live terrain elevation/slope when SRTM is
                         reachable; otherwise risk is UNKNOWN (never silently
                         assumed safe) and the place stays in the list flagged.

Capacities are recomputed with the existing carrying-capacity formula.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from app import config
from app.bhuvan_service import bhuvan_service
from app.geo import haversine
from app.nearby_places import NearbyPlacesService
from app.risk_engine import calculate_carrying_capacity, calculate_site_suitability
from app.terrain_service import TerrainService

_RISKY_BANDS = {"HIGH", "CRITICAL"}
_SLOPE_BAND_RISK = {
    "STEEP": "HIGH",
    "VERY_STEEP": "CRITICAL",
    "MODERATELY_SLOPING": "MEDIUM",
    "GENTLY_SLOPING": "LOW",
    "NEARLY_LEVEL": "LOW",
    None: "UNKNOWN",
}


def _site_risk_from_scores(low_hazard: float, suitability: float) -> Tuple[str, str]:
    if low_hazard >= 80.0:
        return "LOW", "Low"
    if low_hazard >= 60.0:
        return "MEDIUM", "Medium"
    return "CRITICAL", "Critical"


class SafeLocationService:
    def __init__(self) -> None:
        self._nearby = NearbyPlacesService()
        self._terrain = TerrainService()

    @staticmethod
    def _relocation_candidates(data: Dict[str, Any]) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        for site in data.get("relocation_sites", []):
            low_hazard = site.get("low_hazard_score", 50.0)
            suitability = site.get("suitability_score", 50.0)
            band, level = _site_risk_from_scores(low_hazard, suitability)
            final_capacity = calculate_carrying_capacity(
                site.get("land_capacity_families", 400),
                site.get("water_capacity_families", 400),
                site.get("school_capacity_families", 400),
                site.get("health_capacity_families", 400),
                site.get("road_capacity_families", 400),
            )
            available_capacity = site.get("available_capacity_families", final_capacity)
            candidates.append({
                "id": site["id"],
                "name": site["site_name"],
                "kind": "relocation_site",
                "latitude": site["latitude"],
                "longitude": site["longitude"],
                "capacity_families": final_capacity,
                "current_occupancy_families": site.get("current_occupancy_families", 0),
                "available_capacity_families": available_capacity,
                "suitability_score": suitability,
                "risk_band": band,
                "risk_level": level,
                "features": [
                    "Water" if site.get("water_score", 0) >= 70 else "Water insufficient",
                    "Road access" if site.get("road_score", 0) >= 70 else "Road access limited",
                    "School" if site.get("school_score", 0) >= 70 else "School limited",
                    "Healthcare" if site.get("hospital_score", 0) >= 70 else "Healthcare limited",
                ],
                # Phase 6: survey-based shelter/facility attributes (None = unknown)
                "toilets": site.get("toilets_available"),
                "drinking_water": site.get("drinking_water_available"),
                "electricity": site.get("electricity_available"),
                "medical_facility": site.get("medical_facility"),
                "accessibility": (
                    "Road accessible"
                    if site.get("accessible_by_road")
                    else "Not road accessible" if site.get("accessible_by_road") is False else None
                ),
                "contact": (
                    (site.get("contact_name") or "") + (
                        " · " + site["contact_phone"] if site.get("contact_phone") else ""
                    ) or None
                ),
                "verified": site.get("verified"),
                "last_verified": site.get("last_verified"),
                "data_grade": "REAL",
                "data_source": "Curated relocation sites (DDMA planning data)",
            })
        return candidates

    @staticmethod
    def _osm_candidates(payload: Dict[str, Any], kind: str) -> List[Dict[str, Any]]:
        converted_kind = {
            "schools": "school",
            "colleges": "college",
            "facilities": "facility",
        }.get(kind, kind)
        places = []
        for place in payload.get("places", []):
            places.append({
                "id": f"{place.get('osm_type')}-{place.get('osm_id')}",
                "name": place.get("name", "Unnamed facility"),
                "kind": converted_kind,
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "distance_km": place.get("distance_km", 0.0),
                "osm_source_kind": place.get("kind"),
                "data_grade": "ESTIMATE",
                "data_source": "OpenStreetMap (Overpass API)",
            })
        return places

    def _bhuvan_candidates(self, latitude: float, longitude: float) -> List[Dict[str, Any]]:
        """Bhuvan / ISRO hospitals as additional, clearly-labelled candidates.

        Only records the upstream actually returns (token configured AND
        Andhra-Pradesh coverage) are attached — nothing is fabricated or
        duplicated silently. Any failure returns no candidates.
        """
        payload = bhuvan_service.get_hospitals(latitude, longitude, buffer_m=8000)
        if payload.get("data_status") not in ("AVAILABLE", "CACHED"):
            return []
        candidates: List[Dict[str, Any]] = []
        for hospital in payload.get("hospitals", []):
            name = hospital.get("name")
            lat = hospital.get("latitude")
            lng = hospital.get("longitude")
            if not name or not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
                continue
            candidates.append({
                "id": f"bhuvan-{abs(hash((name, lat)))}",
                "name": str(name),
                "kind": "bhuvan_hospital",
                "latitude": lat,
                "longitude": lng,
                "distance_km": (hospital.get("distance_m") or 0.0) / 1000.0,
                "osm_source_kind": None,
                "data_grade": "ESTIMATE",
                "data_source": "Bhuvan / ISRO hospitals (Andhra Pradesh)",
            })
        return candidates

    def _estimate_osm_risk(self, lat: float, lng: float) -> Tuple[str, str]:
        terrain = self._terrain.get_terrain(lat, lng)
        if terrain.get("data_status") != "LIVE":
            return "UNKNOWN", "Unknown"
        return _SLOPE_BAND_RISK.get(terrain.get("slope_category"), "UNKNOWN"), terrain.get("slope_category") or "Unknown"

    def get_safe_locations(
        self,
        data: Dict[str, Any],
        latitude: float,
        longitude: float,
        affected_population: int = 0,
        exclude_status: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        families = max(1, round(affected_population / 4.5)) if affected_population else 100

        candidates = self._relocation_candidates(data)
        for kind in ("schools", "colleges", "facilities"):
            payload = self._nearby.get_nearby(kind, latitude, longitude)
            candidates.extend(self._osm_candidates(payload, kind))
        candidates.extend(self._bhuvan_candidates(latitude, longitude))

        exclude = set(exclude_status or ["HIGH", "CRITICAL"])
        locations: List[Dict[str, Any]] = []
        excluded_locations: List[Dict[str, Any]] = []

        for candidate in candidates:
            distance_km = round(
                haversine(latitude, longitude, candidate["latitude"], candidate["longitude"]) / 1000.0, 2
            )
            risk_band = candidate.get("risk_band")
            if risk_band is None:
                risk_band, risk_level = self._estimate_osm_risk(candidate["latitude"], candidate["longitude"])
                candidate["risk_band"] = risk_band
                candidate["risk_level"] = risk_level

            capacity = candidate.get("capacity_families")
            current = candidate.get("current_occupancy_families", 0)
            available = candidate.get("available_capacity_families")
            if available is None and capacity is not None:
                available = max(0, capacity - current)

            entry: Dict[str, Any] = {
                "id": candidate["id"],
                "name": candidate["name"],
                "kind": candidate["kind"],
                "latitude": candidate["latitude"],
                "longitude": candidate["longitude"],
                "distance_km": distance_km,
                "capacity_families": capacity,
                "current_occupancy_families": current,
                "available_capacity_families": available,
                "suitability_score": candidate.get("suitability_score"),
                "risk_band": risk_band,
                "features": candidate.get("features", []),
                "data_grade": candidate.get("data_grade"),
                "data_source": candidate.get("data_source"),
                # Phase 6 shelter/facility attributes (None when not provided)
                "toilets": candidate.get("toilets"),
                "drinking_water": candidate.get("drinking_water"),
                "electricity": candidate.get("electricity"),
                "medical_facility": candidate.get("medical_facility"),
                "accessibility": candidate.get("accessibility"),
                "contact": candidate.get("contact"),
                "verified": candidate.get("verified"),
                "last_verified": candidate.get("last_verified"),
                "reason": (
                    f"{candidate['name']} ({candidate['kind'].replace('_', ' ')}), "
                    f"{distance_km} km away, estimated risk {risk_band}."
                ),
            }
            if candidate.get("kind") == "relocation_site" and available is not None:
                entry["reason"] += f" Available capacity {available} families (requested {families})."

            if risk_band in exclude:
                excluded_locations.append(entry)
            else:
                entry["site_score"] = self._site_score(candidate, distance_km)
                locations.append(entry)

        locations.sort(key=lambda item: (-(item.get("site_score") or 0.0), item["distance_km"]))

        return {
            "center": {"latitude": round(latitude, 6), "longitude": round(longitude, 6)},
            "affected_population": affected_population,
            "units": families,
            "data_status": "LIVE",
            "excluded_status": sorted(exclude),
            "locations": locations,
            "excluded_locations": excluded_locations,
            "computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    @staticmethod
    def _site_score(candidate: Dict[str, Any], distance_km: float) -> float:
        suitability = candidate.get("suitability_score") or 60.0
        capacity = candidate.get("available_capacity_families")
        capacity_score = min(100.0, 60.0 + (capacity or 0) / 5.0) if capacity is not None else 70.0
        distance_score = max(0.0, 100.0 - distance_km * 2.5)
        if candidate["kind"] == "relocation_site":
            return round(0.50 * suitability + 0.25 * capacity_score + 0.25 * distance_score, 1)
        return round(0.45 * suitability + 0.30 * distance_score + 0.25 * capacity_score, 1)


safe_location_service = SafeLocationService()