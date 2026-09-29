"""Geocoding via OpenStreetMap Nominatim (server-side, cached).

Used to resolve India-wide village labels that have no coordinates stored in the
region hierarchy. Falls back to district/sub-district centroids in the caller.

Status contract:
  LIVE           -> a match was returned by Nominatim (possibly none matched)
  UNAVAILABLE    -> Nominatim unreachable or rate-limited (never fabricated)
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from app import config
from app.cache import TTLCache
from app.http_client import HttpFetchError, http_get


class NominatimRateLimiter:
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


class GeocodeService:
    def __init__(self, base_url: Optional[str] = None) -> None:
        self._base_url = base_url or config.NOMINATIM_BASE_URL
        self._cache = TTLCache(config.GEOCODE_CACHE_TTL_SEC)
        self._limiter = NominatimRateLimiter(config.GEOCODE_MIN_INTERVAL_SEC)

    def search(self, query: str, limit: int = 1, country: str = "in") -> Dict[str, Any]:
        cache_key = f"geocode:{query}:{limit}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        params: Dict[str, Any] = {
            "q": query,
            "format": "jsonv2",
            "limit": limit,
            "addressdetails": 1,
            "countrycodes": country,
        }
        self._limiter.wait()
        try:
            response = http_get(
                f"{self._base_url}/search",
                params=params,
                timeout=10.0,
            )
            if response.status_code == 429:
                raise HttpFetchError("Nominatim rate-limited (429)")
            if response.status_code >= 400:
                raise HttpFetchError(f"Nominatim rejected ({response.status_code})")
            results = response.json()
            places = [
                {
                    "place_id": item.get("place_id"),
                    "display_name": item.get("display_name"),
                    "latitude": float(item["lat"]),
                    "longitude": float(item["lon"]),
                    "type": item.get("type"),
                    "category": item.get("category"),
                    "address": item.get("address", {}),
                }
                for item in results
                if item.get("lat") and item.get("lon")
            ]
            payload = {
                "query": query,
                "data_status": "LIVE",
                "data_source": "OpenStreetMap Nominatim",
                "count": len(places),
                "places": places,
            }
        except HttpFetchError:
            payload = {
                "query": query,
                "data_status": "UNAVAILABLE",
                "data_source": "OpenStreetMap Nominatim",
                "count": 0,
                "places": [],
                "reason": "Nominatim unreachable or rate-limited.",
            }
        self._cache.set(cache_key, payload)
        return payload


geocode_service = GeocodeService()