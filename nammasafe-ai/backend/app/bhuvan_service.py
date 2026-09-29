"""Bhuvan / ISRO geospatial integration (India-wide supporting layer).

A thin, honest proxy over the official Bhuvan v2 REST APIs:

  * village geocode          -> /api_proximity/curl_village_geocode.php
  * reverse geocode          -> /api_proximity/curl_reverse_village.php
  * hospitals proximity      -> /api_proximity/curl_hos_pos_prox.php
  * LULC 50K district stats  -> /lulc/curljson.php
  * LULC 50K AOI statistics  -> /lulc/curl_aoi.php
  * LULC 250K point class    -> /lulc250k/curl_lulc250k_point.php
  * LULC 250K AOI breakdown  -> /lulc250k/curl_lulc250k.php
  * intra-state shortest path-> /routing/curl_routing_state.php
  * CartoDEM geoid tile      -> /geoid/curl_gdal_api.php  (download proxy)

Honesty contract (mirrors the platform spec):
  * The access token / key lives only in backend/.env (gitignored) and is never
    exposed through payloads or logs.
  * Census village geocoding returns NO coordinates: the payload says so
    instead of inventing a lat/lng.
  * When Bhuvan returns False / Null / empty (or the location is outside the
    documented coverage, e.g. AP & Karnataka for census, Andhra Pradesh for
    hospitals, intra-state only for routing) the payload is UNAVAILABLE — never
    fabricated.
  * Static/historical datasets are labelled AVAILABLE (or CACHED when served
    from the in-process TTL cache), never LIVE.
  * When the returned census record belongs to a different district than the
    requested one, the payload is LOCATION_MISMATCH — the record is kept
    separate, it is never silently merged onto another location.

Status vocabulary: AVAILABLE | CACHED | UNAVAILABLE | ERROR | LOCATION_MISMATCH
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from app import config
from app.cache import TTLCache
from app.geo import haversine
from app.http_client import HttpFetchError, http_get

SOURCE_NAME = "Bhuvan / ISRO"

STATUS_AVAILABLE = "AVAILABLE"
STATUS_CACHED = "CACHED"
STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_ERROR = "ERROR"
STATUS_MISMATCH = "LOCATION_MISMATCH"

# Documented requirement: Bhuvan accepts these calls only with a
# application/x-www-form-urlencoded content-type header (otherwise 400).
_BHUVAN_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}

# ISRO LULC class -> heuristic flood/inundation susceptibility. Documented in
# the payload as a heuristic surface-cover reading, never as a flood model.
_LULC_SUSCEPTIBILITY: Dict[str, float] = {
    "water bodies": 80.0,
    "waterbodies": 80.0,
    "reservoir/lakes": 80.0,
    "rivers/streams": 80.0,
    "wetlands": 75.0,
    "swampy/marshy": 75.0,
    "waterlogged": 75.0,
    "river island": 70.0,
    "coastal sands": 60.0,
    "salt affected": 60.0,
    "built-up (urban)": 40.0,
    "built-up (rural)": 35.0,
    "built-up": 35.0,
    "agriculture": 40.0,
    "kharif": 40.0,
    "rabi": 40.0,
    "double/triple": 40.0,
    "current fallow": 40.0,
    "shifting cultivation": 45.0,
    "plantation": 30.0,
    "orchards": 30.0,
    "forest": 25.0,
    "degraded forest": 30.0,
    "grassland": 25.0,
    "barren rocky": 20.0,
    "wastelands": 20.0,
    "snow": 20.0,
    "snow covered": 20.0,
}
_DEFAULT_LULC_SUSCEPTIBILITY = 30.0


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _has_data(payload: Any) -> bool:
    if payload is None or payload is False:
        return False
    if isinstance(payload, (dict, list)) and not payload:
        return False
    if isinstance(payload, str) and not payload.strip():
        return False
    return True


def _as_list(payload: Any) -> Optional[List[Any]]:
    """Defensive unwrap of Bhuvan response containers (Result / data / ...)."""
    if payload is None or payload is False:
        return None
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("Result", "results", "data", "Records", "records", "Features", "features"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if value is not None and value is not False:
                return [value]
    return None


def _credentials(use_key: bool) -> Optional[Dict[str, str]]:
    if use_key:
        value = config.BHUVAN_API_KEY
        return {"key": value} if value else None
    value = config.BHUVAN_API_TOKEN
    return {"token": value} if value else None


class BhuvanService:
    def __init__(self) -> None:
        self._geocode_cache = TTLCache(config.BHUVAN_GEOCODE_TTL_SEC)
        self._lulc_cache = TTLCache(config.BHUVAN_CACHE_TTL_SEC)
        self._route_cache = TTLCache(config.BHUVAN_CACHE_TTL_SEC)
        self._hospital_cache = TTLCache(config.BHUVAN_CACHE_TTL_SEC)

    # ---------------- internal fetch ----------------
    def _fetch_json(
        self, path: str, params: Dict[str, Any], use_key: bool = False
    ) -> Tuple[str, Any, Dict[str, str]]:
        """Returns (status, payload_or_reason, credentials)."""
        creds = _credentials(use_key)
        if creds is None:
            env = "BHUVAN_API_KEY" if use_key else "BHUVAN_API_TOKEN"
            return STATUS_UNAVAILABLE, f"{env} is not configured in backend/.env", {}
        url = f"{config.BHUVAN_API_BASE_URL}{path}"
        full_params = {**creds, **params}
        try:
            response = http_get(
                url,
                params=full_params,
                timeout=config.BHUVAN_TIMEOUT_SEC,
                headers=_BHUVAN_HEADERS,
            )
        except HttpFetchError as exc:
            return STATUS_ERROR, f"Bhuvan unreachable ({exc})", creds
        if response.status_code >= 400:
            return STATUS_ERROR, f"Bhuvan rejected request ({response.status_code})", creds
        try:
            return STATUS_AVAILABLE, response.json(), creds
        except Exception:  # pragma: no cover - non-JSON upstream
            return STATUS_ERROR, "Bhuvan returned a non-JSON response.", creds

    @staticmethod
    def _failure(service: str, status: str, reason: Any) -> Dict[str, Any]:
        return {
            "source": SOURCE_NAME,
            "service": service,
            "data_status": status,
            "data_source": SOURCE_NAME,
            "reason": str(reason),
            "computed_at": _now(),
        }

    @staticmethod
    def _from_cache(cached: Dict[str, Any]) -> Dict[str, Any]:
        copied = dict(cached)
        copied["data_status"] = STATUS_CACHED
        copied["computed_at"] = _now()
        return copied

    # ---------------- village geocode (census-2001) ----------------
    def resolve_village(
        self, village: str, state: Optional[str] = None, district: Optional[str] = None
    ) -> Dict[str, Any]:
        cache_key = f"village:{village}:{state or ''}:{district or ''}"
        cached = self._geocode_cache.get(cache_key)
        if cached is not None:
            return self._from_cache(cached)

        status, payload, _creds = self._fetch_json(
            "/api_proximity/curl_village_geocode.php", {"village": village}
        )
        if status != STATUS_AVAILABLE:
            return self._failure("village_geocode", status, payload)

        records = _as_list(payload)
        if not records:
            return {
                "source": SOURCE_NAME,
                "service": "village_geocode",
                "data_status": STATUS_UNAVAILABLE,
                "data_source": "Bhuvan village geocode (census-2001)",
                "dataset_year": "2001",
                "query": {"village": village, "state": state, "district": district},
                "record": None,
                "has_coordinates": False,
                "coordinate_note": "Bhuvan census geocoding returns no coordinates; coordinates are resolved from OpenStreetMap/Nominatim.",
                "coverage_note": "Bhuvan village geocode coverage: Andhra Pradesh & Karnataka (census-2001).",
                "reason": "No Bhuvan census-2001 record for this village.",
                "computed_at": _now(),
            }

        first = records[0] if isinstance(records[0], dict) else {}
        census_district = str(first.get("dhq_name") or "").strip()
        census_sub = str(first.get("thq_name") or "").strip()

        status_out = STATUS_AVAILABLE
        note: Optional[str] = None
        if district and census_district:
            requested = str(district).strip().lower()
            census = census_district.lower()
            if not (requested in census or census in requested):
                status_out = STATUS_MISMATCH
                note = (
                    f"Bhuvan census record belongs to district '{census_district}', "
                    f"requested '{district}'. Kept separate — never merged onto the request."
                )

        result = {
            "source": SOURCE_NAME,
            "service": "village_geocode",
            "data_status": status_out,
            "data_source": "Bhuvan village geocode (census-2001)",
            "dataset_year": "2001",
            "query": {"village": village, "state": state, "district": district},
            "record": {
                "name": first.get("name1") or None,
                "census_village_code": first.get("vid") or None,
                "district": census_district or None,
                "sub_district": census_sub or None,
                "households": first.get("no_hh") or None,
            },
            "has_coordinates": False,
            "coordinate_note": "Bhuvan census geocoding returns no coordinates; coordinates are resolved from OpenStreetMap/Nominatim.",
            "reason": note,
            "computed_at": _now(),
        }
        self._geocode_cache.set(cache_key, result)
        return result

    # ---------------- reverse geocode ----------------
    def reverse_geocode(self, latitude: float, longitude: float) -> Dict[str, Any]:
        cache_key = f"rev:{round(latitude, 4)}:{round(longitude, 4)}"
        cached = self._geocode_cache.get(cache_key)
        if cached is not None:
            return self._from_cache(cached)

        status, payload, _creds = self._fetch_json(
            "/api_proximity/curl_reverse_village.php", {"lat": latitude, "lon": longitude}
        )
        if status != STATUS_AVAILABLE:
            return self._failure("reverse_geocode", status, payload)

        records = _as_list(payload)
        villages: List[str] = []
        for item in records or []:
            if isinstance(item, dict):
                name = (
                    item.get("name") or item.get("name1")
                    or item.get("village") or item.get("villagename")
                )
                if name:
                    villages.append(str(name))
            elif isinstance(item, str) and item.strip():
                villages.append(item.strip())

        if not villages:
            return {
                "source": SOURCE_NAME,
                "service": "reverse_geocode",
                "data_status": STATUS_UNAVAILABLE,
                "data_source": "Bhuvan reverse village geocode",
                "villages": [],
                "reverse_latitude": round(latitude, 6),
                "reverse_longitude": round(longitude, 6),
                "coverage_note": "Coverage: Andhra Pradesh & Karnataka (v1).",
                "reason": "No Bhuvan village near these coordinates (coverage limited to AP & Karnataka).",
                "computed_at": _now(),
            }

        result = {
            "source": SOURCE_NAME,
            "service": "reverse_geocode",
            "data_status": STATUS_AVAILABLE,
            "data_source": "Bhuvan reverse village geocode",
            "villages": villages[:20],
            "reverse_latitude": round(latitude, 6),
            "reverse_longitude": round(longitude, 6),
            "coverage_note": "Coverage: Andhra Pradesh & Karnataka (v1).",
            "reason": None,
            "computed_at": _now(),
        }
        self._geocode_cache.set(cache_key, result)
        return result

    # ---------------- hospitals proximity (Andhra Pradesh) ----------------
    def get_hospitals(self, latitude: float, longitude: float, buffer_m: int = 3000) -> Dict[str, Any]:
        cache_key = f"hop:{round(latitude, 4)}:{round(longitude, 4)}:{buffer_m}"
        cached = self._hospital_cache.get(cache_key)
        if cached is not None:
            return self._from_cache(cached)

        status, payload, _creds = self._fetch_json(
            "/api_proximity/curl_hos_pos_prox.php",
            {"theme": "hospital", "lat": latitude, "lon": longitude, "buffer": buffer_m},
        )
        if status != STATUS_AVAILABLE:
            return self._failure("hospitals", status, payload)

        hospitals: List[Dict[str, Any]] = []
        for item in _as_list(payload) or []:
            if not isinstance(item, dict):
                continue
            name = (
                item.get("name") or item.get("facility_name")
                or item.get("hospital_name") or item.get("h_name")
            )
            if not name:
                continue
            hospitals.append({
                "name": str(name),
                "latitude": _num(item.get("lat") or item.get("latitude")),
                "longitude": _num(item.get("lon") or item.get("long") or item.get("longitude")),
                "distance_m": _num(item.get("distance") or item.get("dist") or item.get("distance_m")),
                "type": item.get("type"),
            })

        if not hospitals:
            return {
                "source": SOURCE_NAME,
                "service": "hospitals",
                "data_status": STATUS_UNAVAILABLE,
                "data_source": "Bhuvan hospitals proximity (Andhra Pradesh)",
                "center": {"latitude": round(latitude, 6), "longitude": round(longitude, 6)},
                "buffer_m": buffer_m,
                "count": 0,
                "hospitals": [],
                "coverage_note": "Bhuvan hospital proximity coverage: Andhra Pradesh.",
                "reason": "No Bhuvan hospital records within the buffer for this location (coverage limited to Andhra Pradesh).",
                "computed_at": _now(),
            }

        result = {
            "source": SOURCE_NAME,
            "service": "hospitals",
            "data_status": STATUS_AVAILABLE,
            "data_source": "Bhuvan hospitals proximity (Andhra Pradesh)",
            "center": {"latitude": round(latitude, 6), "longitude": round(longitude, 6)},
            "buffer_m": buffer_m,
            "count": len(hospitals),
            "hospitals": hospitals,
            "coverage_note": "Bhuvan hospital proximity coverage: Andhra Pradesh.",
            "reason": None,
            "computed_at": _now(),
        }
        self._hospital_cache.set(cache_key, result)
        return result

    # ---------------- LULC 50K (district statistics) ----------------
    def get_lulc_50k(
        self,
        state_abbr: Optional[str] = None,
        district_code: Optional[str] = None,
        year: str = "1112",
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"year": year}
        if district_code:
            params["distcode"] = str(district_code)
        elif state_abbr:
            params["statcode"] = str(state_abbr).upper()
        else:
            return {
                "source": SOURCE_NAME,
                "service": "lulc_50k",
                "data_status": STATUS_UNAVAILABLE,
                "data_source": "Bhuvan LULC 50K district statistics (ISRO)",
                "reason": "state_abbr or district_code is required.",
                "computed_at": _now(),
            }

        cache_key = f"lulc50k:{district_code or ''}:{state_abbr or ''}:{year}"
        cached = self._lulc_cache.get(cache_key)
        if cached is not None:
            return self._from_cache(cached)

        status, payload, _creds = self._fetch_json("/lulc/curljson.php", params)
        if status != STATUS_AVAILABLE:
            return self._failure("lulc_50k", status, payload)
        if not _has_data(payload):
            return self._failure("lulc_50k", STATUS_UNAVAILABLE, "No Bhuvan LULC 50K statistics returned for this district/state.")

        stats = payload if isinstance(payload, dict) else {"raw": payload}
        result = {
            "source": SOURCE_NAME,
            "service": "lulc_50k",
            "data_status": STATUS_AVAILABLE,
            "data_source": "Bhuvan LULC 50K district statistics (ISRO)",
            "dataset_year": year,
            "state_abbr": state_abbr,
            "district_code": district_code,
            "stats": {str(k): v for k, v in stats.items() if not isinstance(v, (dict, list))},
            "reason": None,
            "computed_at": _now(),
        }
        self._lulc_cache.set(cache_key, result)
        return result

    # ---------------- LULC 50K (AOI) ----------------
    def get_lulc_50k_aoi(self, geom_wkt: str, year: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"geom": geom_wkt}
        if year:
            params["year"] = year
        cache_key = f"lulc50k-aoi:{hash((geom_wkt, year))}"
        cached = self._lulc_cache.get(cache_key)
        if cached is not None:
            return self._from_cache(cached)

        status, payload, _creds = self._fetch_json("/lulc/curl_aoi.php", params)
        if status != STATUS_AVAILABLE:
            return self._failure("lulc_50k_aoi", status, payload)
        if not _has_data(payload):
            return self._failure("lulc_50k_aoi", STATUS_UNAVAILABLE, "No Bhuvan LULC 50K AOI statistics returned for this geometry.")

        stats = payload if isinstance(payload, dict) else {"raw": payload}
        result = {
            "source": SOURCE_NAME,
            "service": "lulc_50k_aoi",
            "data_status": STATUS_AVAILABLE,
            "data_source": "Bhuvan LULC 50K AOI (ISRO)",
            "year": year,
            "stats": {str(k): v for k, v in stats.items() if not isinstance(v, (dict, list))},
            "reason": None,
            "computed_at": _now(),
        }
        self._lulc_cache.set(cache_key, result)
        return result

    # ---------------- LULC 250K (point class) ----------------
    def get_lulc_250k(self, longitude: float, latitude: float, year: str = "all") -> Dict[str, Any]:
        cache_key = f"lulc250k:{round(latitude, 4)}:{round(longitude, 4)}:{year}"
        cached = self._lulc_cache.get(cache_key)
        if cached is not None:
            return self._from_cache(cached)

        status, payload, _creds = self._fetch_json(
            "/lulc250k/curl_lulc250k_point.php", {"lon": longitude, "lat": latitude, "year": year}
        )
        if status != STATUS_AVAILABLE:
            return self._failure("lulc_250k", status, payload)

        class_name: Optional[str] = None
        area = None
        pct = None
        if isinstance(payload, dict):
            class_name = payload.get("class") or payload.get("class_name") or payload.get("CLASS")
            class_name = str(class_name) if class_name else None
            area = _num(payload.get("area"))
            pct = _num(payload.get("percent"))
        elif isinstance(payload, str) and payload.strip().lower() not in ("", "null", "false"):
            class_name = payload.strip()

        if not class_name:
            return {
                "source": SOURCE_NAME,
                "service": "lulc_250k",
                "data_status": STATUS_UNAVAILABLE,
                "data_source": "Bhuvan LULC 250K (ISRO)",
                "reason": "No Bhuvan LULC 250K class returned for this point.",
                "computed_at": _now(),
            }

        result = {
            "source": SOURCE_NAME,
            "service": "lulc_250k",
            "data_status": STATUS_AVAILABLE,
            "data_source": "Bhuvan LULC 250K (ISRO)",
            "dataset_year": year,
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "class": class_name,
            "area": area,
            "percent": pct,
            "reason": None,
            "computed_at": _now(),
        }
        self._lulc_cache.set(cache_key, result)
        return result

    # ---------------- LULC 250K (AOI breakdown) ----------------
    def get_lulc_250k_aoi(self, polygon: str, year: str = "all", option: str = "json") -> Dict[str, Any]:
        params: Dict[str, Any] = {"polygon": polygon, "year": year, "option": option}
        cache_key = f"lulc250k-aoi:{hash((polygon, year, option))}"
        cached = self._lulc_cache.get(cache_key)
        if cached is not None:
            return self._from_cache(cached)

        status, payload, _creds = self._fetch_json("/lulc250k/curl_lulc250k.php", params)
        if status != STATUS_AVAILABLE:
            return self._failure("lulc_250k_aoi", status, payload)
        if not _has_data(payload):
            return self._failure("lulc_250k_aoi", STATUS_UNAVAILABLE, "No Bhuvan LULC 250K AOI breakdown returned for this polygon.")

        classes = payload if isinstance(payload, dict) else {"raw": payload}
        result = {
            "source": SOURCE_NAME,
            "service": "lulc_250k_aoi",
            "data_status": STATUS_AVAILABLE,
            "data_source": "Bhuvan LULC 250K AOI (ISRO)",
            "dataset_year": year,
            "classes": classes,
            "reason": None,
            "computed_at": _now(),
        }
        self._lulc_cache.set(cache_key, result)
        return result

    # ---------------- intra-state shortest path ----------------
    def get_shortest_path(self, lat1: float, lon1: float, lat2: float, lon2: float) -> Dict[str, Any]:
        cache_key = f"route:{round(lat1, 4)}:{round(lon1, 4)}:{round(lat2, 4)}:{round(lon2, 4)}"
        cached = self._route_cache.get(cache_key)
        if cached is not None:
            return self._from_cache(cached)

        status, payload, _creds = self._fetch_json(
            "/routing/curl_routing_state.php",
            {"lat1": lat1, "lon1": lon1, "lat2": lat2, "lon2": lon2},
        )
        geometry: Optional[Dict[str, Any]] = None
        if status == STATUS_AVAILABLE:
            if isinstance(payload, dict) and payload.get("type") == "FeatureCollection":
                for feat in payload.get("features", []):
                    geom = (feat or {}).get("geometry") or {}
                    if geom.get("type") == "MultiLineString":
                        geometry = geom
                        break
            elif isinstance(payload, dict) and payload.get("type") == "MultiLineString":
                geometry = payload

        if geometry is None:
            return {
                "source": SOURCE_NAME,
                "service": "shortest_path",
                "data_status": STATUS_UNAVAILABLE,
                "data_source": "Bhuvan intra-state routing (v1)",
                "origin": [lat1, lon1],
                "destination": [lat2, lon2],
                "geometry": None,
                "distance_km": None,
                "coverage_note": "Bhuvan routing is intra-state only.",
                "reason": "Bhuvan intra-state routing returned no route (Null) for these points.",
                "computed_at": _now(),
            }

        coordinates = geometry.get("coordinates") or [[]]
        ring = coordinates[0] if coordinates and isinstance(coordinates[0], list) else []
        distance_km = 0.0
        for (lon_a, lat_a), (lon_b, lat_b) in zip(ring[:-1], ring[1:]):
            try:
                distance_km += haversine(float(lat_a), float(lon_a), float(lat_b), float(lon_b)) / 1000.0
            except (TypeError, ValueError):  # pragma: no cover - malformed geometry
                continue

        result = {
            "source": SOURCE_NAME,
            "service": "shortest_path",
            "data_status": STATUS_AVAILABLE,
            "data_source": "Bhuvan intra-state routing (v1)",
            "origin": [lat1, lon1],
            "destination": [lat2, lon2],
            "geometry": geometry,
            "distance_km": round(distance_km, 2),
            "coverage_note": "Bhuvan routing is intra-state only.",
            "reason": None,
            "computed_at": _now(),
        }
        self._route_cache.set(cache_key, result)
        return result

    # ---------------- CartoDEM geoid tile (download proxy) ----------------
    def convert_geoid(self, tile_id: str, datum: str = "elipsoid") -> Dict[str, Any]:
        if _credentials(use_key=True) is None:
            return {
                "source": SOURCE_NAME,
                "service": "geoid_tile_proxy",
                "data_status": STATUS_UNAVAILABLE,
                "data_source": "Bhuvan CartoDEM v3R1 (CDEM) geoid tile proxy",
                "tile_id": tile_id,
                "datum": datum,
                "proxy": True,
                "reason": "BHUVAN_API_KEY is not configured in backend/.env.",
                "computed_at": _now(),
            }
        return {
            "source": SOURCE_NAME,
            "service": "geoid_tile_proxy",
            "data_status": STATUS_AVAILABLE,
            "data_source": "Bhuvan CartoDEM v3R1 (CDEM) geoid tile proxy",
            "tile_id": tile_id,
            "datum": datum,
            "proxy": True,
            "download_endpoint": f"{config.BHUVAN_API_BASE_URL}/geoid/curl_gdal_api.php",
            "note": "The documented geoid API downloads a CartoDEM tile (id.zip / converted tile) — it does not resolve a single-point height.",
            "height_note": "Elevation in the risk engine keeps the verified SRTM/Open-Meteo source; no height is fabricated from this proxy.",
            "reason": None,
            "computed_at": _now(),
        }

    # ---------------- lulc susceptibility (risk engine helper) ----------------
    @staticmethod
    def lulc_susceptibility(class_name: Optional[str]) -> Optional[float]:
        if not class_name:
            return None
        return _LULC_SUSCEPTIBILITY.get(str(class_name).strip().lower(), _DEFAULT_LULC_SUSCEPTIBILITY)


bhuvan_service = BhuvanService()