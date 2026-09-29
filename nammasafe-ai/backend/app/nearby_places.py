"""Nearby critical-facility lookup from OpenStreetMap via the Overpass API.

Used for hospitals, schools, colleges, bridges and generic facilities within a
radius. Requests are rate-limited and cached so we respect the public Overpass
instances' usage policy.

Status contract:
  LIVE           -> facilities found / query answered (possibly empty list)
  UNAVAILABLE    -> Overpass unreachable or rate-limited (never fabricated)
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from app import config
from app.cache import TTLCache
from app.geo import haversine
from app.http_client import HttpFetchError, http_get

# kind -> (label, list of OSM filters)
_KINDS: Dict[str, Dict[str, Any]] = {
    "hospitals": {
        "label": "Hospitals & clinics",
        "queries": [
            'node["amenity"~"^(hospital|clinic)$"]',
            'way["amenity"~"^(hospital|clinic)$"]',
        ],
    },
    "schools": {
        "label": "Schools",
        "queries": [
            'node["amenity"~"^(school|college|university)$"]',
            'way["amenity"~"^(school|college|university)$"]',
        ],
    },
    "colleges": {
        "label": "Colleges & universities",
        "queries": [
            'node["amenity"~"^(college|university)$"]',
            'way["amenity"~"^(college|university)$"]',
        ],
    },
    "bridges": {
        "label": "Bridges",
        "queries": [
            'way["bridge"~"^(yes|movable|cantilever|trestle)$"]',
            'node["man_made"="bridge"]',
        ],
    },
    "villages": {
        "label": "Villages & towns",
        "queries": [
            'node["place"~"^(town|village|hamlet|suburb)$"]["name"]',
            'way["place"~"^(town|village|hamlet|suburb)$"]["name"]',
        ],
    },
    "facilities": {
        "label": "Community facilities",
        "queries": [
            'node["amenity"~"^(hospital|clinic|school|college|community_centre|police|fire_station|shelter|place_of_worship)$"]',
            'way["amenity"~"^(hospital|clinic|school|college|community_centre|police|fire_station|shelter|place_of_worship)$"]',
        ],
    },
}


class OverpassRateLimiter:
    """Tiny single-host rate limiter (in-process)."""

    def __init__(self, min_interval_sec: float) -> None:
        self._min_interval = max(0.0, min_interval_sec)
        self._last_call = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_call
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_call = time.monotonic()


class NearbyPlacesService:
    def __init__(
        self,
        overpass_url: Optional[str] = None,
        radius_km: Optional[float] = None,
    ) -> None:
        self._url = overpass_url or config.OVERPASS_API_URL
        self._radius_m = int((radius_km or config.NEARBY_RADIUS_KM_DEFAULT) * 1000.0)
        self._cache = TTLCache(config.NEARBY_CACHE_TTL_SEC)
        self._limiter = OverpassRateLimiter(config.OVERPASS_MIN_INTERVAL_SEC)

    @staticmethod
    def _query_for(kind: str, lat: float, lng: float, radius_m: int) -> str:
        filters = ""
        for query in _KINDS[kind]["queries"]:
            filters += f"  {query}(around:{radius_m},{lat:.6f},{lng:.6f});\n"
        return f"[out:json][timeout:25];\n(\n{filters});\nout center tags;\n"

    def _fetch(self, kind: str, latitude: float, longitude: float) -> Dict[str, Any]:
        query = self._query_for(kind, latitude, longitude, self._radius_m)
        self._limiter.wait()
        response = http_get(
            self._url,
            params={"data": query},
            headers={"Content-Type": "text/plain"},
            timeout=30.0,
        )
        if response.status_code == 429:
            raise HttpFetchError("Overpass rate-limited (429)")
        if response.status_code >= 400:
            raise HttpFetchError(f"Overpass rejected ({response.status_code})")
        return response.json()

    def _build_payload(
        self, kind: str, latitude: float, longitude: float, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        places: List[Dict[str, Any]] = []
        for element in data.get("elements", []):
            lat = element.get("lat")
            lng = element.get("lon")
            if lat is None and element.get("center"):
                lat = element["center"].get("lat")
                lng = element["center"].get("lon")
            if lat is None or lng is None:
                continue
            tags = element.get("tags", {}) or {}
            name = tags.get("name") or tags.get("operator") or _KINDS[kind]["label"]
            places.append(
                {
                    "osm_id": element.get("id"),
                    "osm_type": element.get("type"),
                    "kind": kind,
                    "label": _KINDS[kind]["label"],
                    "name": name,
                    "amenity": tags.get("amenity"),
                    "operator": tags.get("operator"),
                    "latitude": round(float(lat), 6),
                    "longitude": round(float(lng), 6),
                    "distance_km": round(haversine(latitude, longitude, float(lat), float(lng)) / 1000.0, 2),
                }
            )
        places.sort(key=lambda item: item["distance_km"])
        return {
            "kind": kind,
            "label": _KINDS[kind]["label"],
            "center": {"latitude": round(float(latitude), 6), "longitude": round(float(longitude), 6)},
            "radius_km": round(self._radius_m / 1000.0, 1),
            "data_status": "LIVE",
            "data_source": "OpenStreetMap (Overpass API)",
            "count": len(places),
            "places": places,
        }

    def get_nearby(self, kind: str, latitude: float, longitude: float) -> Dict[str, Any]:
        if kind not in _KINDS:
            raise ValueError(f"Unknown nearby kind: {kind}")
        cache_key = f"nearby:{kind}:{round(latitude, 3)}:{round(longitude, 3)}:{self._radius_m}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            payload = self._build_payload(
                kind, latitude, longitude, self._fetch(kind, latitude, longitude)
            )
        except HttpFetchError:
            payload = {
                "kind": kind,
                "label": _KINDS[kind]["label"],
                "center": {"latitude": round(float(latitude), 6), "longitude": round(float(longitude), 6)},
                "radius_km": round(self._radius_m / 1000.0, 1),
                "data_status": "UNAVAILABLE",
                "data_source": "OpenStreetMap (Overpass API)",
                "count": 0,
                "places": [],
                "reason": "Overpass unreachable or rate-limited.",
            }
        self._cache.set(cache_key, payload)
        return payload


nearby_places_service = NearbyPlacesService()

SUPPORTED_KINDS = tuple(_KINDS.keys())