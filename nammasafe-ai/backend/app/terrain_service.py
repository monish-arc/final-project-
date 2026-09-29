"""Terrain service: real SRTM-derived elevation + measured ground steepness.

Primary provider is NASA Earthdata SRTM (LP DAAC Earthdata Cloud SRTMGL1.003).
Elevation comes from the actual 1-arc-second DEM (bilinear), and slope is the
real gradient of a DEM window around the point (Horn's method) -- never a
fabricated value.

Open-Meteo's elevation endpoint (SRTM/COP90-derived) acts as a fallback
provider via config.NASA_TERRAIN_FALLBACK_OPENMETEO. The fallback is ON by
default so a fresh deployment serves elevation with no secrets; such payloads
are always labelled "fallback" and never pretend to be NASA data.

Data-status contract (mirrors weather_service):
  LIVE         -> elevations fetched from the serving provider
  NOT_CONFIGURED -> NASA token missing and no fallback configured
  UNAVAILABLE  -> upstream unreachable/rejected; no fabricated values
"""

from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from app import config
from app.cache import TTLCache
from app.http_client import HttpFetchError, http_get
from app.nasa_elevation_client import (
    NasaAuthError,
    NasaElevationError,
    NasaSrtmElevationClient,
    NasaTileMissingError,
)
from app.weather_service import (
    _inflight_acquire,
    _inflight_done,
    _inflight_wait,
    _mark_provider_cooldown,
    _PROVIDER_HTTP_SEMAPHORE,
    _provider_in_cooldown,
    _retry_after_seconds,
)

_OPENMETEO_ELEVATION_PROVIDER = "Open-Meteo elevation"

# Fraction of stair-step count by steepness (typical building-regulation style bands).
_SLOPE_BANDS: List[tuple] = [
    (3.0, "NEARLY_LEVEL"),
    (8.0, "GENTLY_SLOPING"),
    (15.0, "MODERATELY_SLOPING"),
    (30.0, "STEEP"),
]


def _slope_category(percent: Optional[float]) -> Optional[str]:
    if percent is None:
        return None
    for max_pct, label in _SLOPE_BANDS:
        if percent <= max_pct:
            return label
    return "VERY_STEEP"


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class TerrainService:
    """Orchestrates NASA SRTM (primary) with an opt-in Open-Meteo fallback.

    Passing an explicit `base_url` (a non-default Open-Meteo URL) constructs an
    Open-Meteo-only instance, used by tests and operators isolating a provider.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        db: Optional[Any] = None,
    ) -> None:
        self._base_url = base_url or config.OPEN_METEO_BASE_URL
        self._openmeteo_only = base_url is not None
        self._cache = TTLCache(config.TERRAIN_CACHE_TTL_SEC)
        self._nasa = NasaSrtmElevationClient()
        self._db = db

    # ---------------- NASA SRTM (primary) ----------------

    def _nasa_payload(self, latitude: float, longitude: float) -> Dict[str, Any]:
        raw = self._nasa.compute_terrain(latitude, longitude)
        slope_percent = raw.get("slope_percent")
        elevation_change = raw.get("elevation_change_m")
        return {
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "data_status": "LIVE",
            "data_source": raw.get("data_source"),
            "provider": "nasa",
            "provider_role": "primary",
            "dataset": raw.get("dataset"),
            "elevation_m": raw.get("elevation_m"),
            "slope_percent": slope_percent,
            "slope_degrees": raw.get("slope_degrees"),
            "slope_category": _slope_category(slope_percent),
            "elevation_change_m": elevation_change,
            "slope_window_arcsec": raw.get("slope_window_arcsec"),
            "sample_radius_km": None,
            "sample_count": 9,
            "computed_at": _utc_now(),
        }

    # ---------------- Open-Meteo (fallback / isolated provider) ----------------

    def _fetch_elevation(self, points: List[tuple]) -> List[Optional[float]]:
        if not points:
            return []
        if _provider_in_cooldown(_OPENMETEO_ELEVATION_PROVIDER):
            raise HttpFetchError(
                "Open-Meteo elevation provider is in its rate-limit cooldown window"
            )
        lats = ",".join(f"{p[0]:.6f}" for p in points)
        lngs = ",".join(f"{p[1]:.6f}" for p in points)
        with _PROVIDER_HTTP_SEMAPHORE:
            response = http_get(
                f"{self._base_url}/elevation",
                params={"latitude": lats, "longitude": lngs},
                timeout=config.WEATHER_TIMEOUT_SEC,
            )
        if response.status_code == 429:
            retry_after = _retry_after_seconds(
                getattr(response, "headers", None) or {},
                config.WEATHER_PROVIDER_COOLDOWN_SEC,
            )
            _mark_provider_cooldown(_OPENMETEO_ELEVATION_PROVIDER, retry_after)
            raise HttpFetchError("Open-Meteo elevation throttled the request (HTTP 429)")
        if response.status_code >= 400:
            raise HttpFetchError(f"Open-Meteo elevation rejected ({response.status_code})")
        body = response.json()
        raw = body.get("elevation") or []
        return [v if isinstance(v, (int, float)) else None for v in raw]

    @staticmethod
    def _sample_offsets(latitude: float, longitude: float, km: float) -> List[tuple]:
        """8 compass points at `km` kilometres from the centre."""
        dlat = km / 110.574
        dlng = km / (111.320 * math.cos(math.radians(latitude))) if abs(latitude) < 89.0 else 0.0
        offsets = [
            (dlat, 0.0), (-dlat, 0.0), (0.0, dlng), (0.0, -dlng),
            (dlat, dlng), (dlat, -dlng), (-dlat, dlng), (-dlat, -dlng),
        ]
        return [(_round_and_clamp(latitude + dlat_), _round_and_clamp(longitude + dlng_))
                for dlat_, dlng_ in offsets]

    def _openmeteo_payload(
        self,
        latitude: float,
        longitude: float,
        *,
        fallback: bool = False,
        fallback_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        samples = self._sample_offsets(latitude, longitude, config.TERRAIN_SAMPLE_KM)
        values = self._fetch_elevation([(latitude, longitude)] + samples)
        elevation = values[0] if values else None
        ring = values[1:]

        valid_ring = [v for v in ring if v is not None]
        run_m = config.TERRAIN_SAMPLE_KM * 1000.0
        slope_percent = None
        if elevation is not None and valid_ring:
            rises = [max(0.0, v - elevation) for v in valid_ring]
            slope_percent = (sum(rises) / len(rises)) / run_m * 100.0

        if fallback and elevation is None and not valid_ring:
            raise HttpFetchError("Open-Meteo elevation returned no usable values")

        payload: Dict[str, Any] = {
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "data_status": "LIVE",
            "data_source": "Open-Meteo elevation (SRTM-derived)",
            "provider": "open-meteo",
            "provider_role": "fallback" if fallback else "primary",
            "dataset": "Open-Meteo elevation (SRTM/COP90)",
            "elevation_m": None if elevation is None else round(elevation, 2),
            "slope_percent": None if slope_percent is None else round(slope_percent, 2),
            "slope_degrees": None,
            "slope_category": _slope_category(slope_percent),
            "elevation_change_m": None,
            "slope_window_arcsec": None,
            "sample_radius_km": config.TERRAIN_SAMPLE_KM,
            "sample_count": len(samples),
            "computed_at": _utc_now(),
        }
        if fallback:
            payload["reason"] = fallback_reason or (
                "NASA SRTM unavailable; serving configured Open-Meteo fallback."
            )
        return payload

    # ---------------- DB-backed grid cache (validated NASA samples only) ----------------

    @staticmethod
    def _grid_cell(latitude: float, longitude: float) -> tuple:
        """Roughly ~55 m grid so nearby queries reuse one cached sample."""
        cell = 2000.0
        return (round(latitude * cell) / cell, round(longitude * cell) / cell)

    def _db_get(self, latitude: float, longitude: float) -> Optional[Dict[str, Any]]:
        if config.TERRAIN_DB_CACHE != "on":
            return None
        try:
            from app.database import SessionLocal
            from app.models import TerrainSample

            session = self._db or SessionLocal()
            try:
                cell = 2000.0
                row = (
                    session.query(TerrainSample)
                    .filter(
                        TerrainSample.latitude == round(latitude * cell) / cell,
                        TerrainSample.longitude == round(longitude * cell) / cell,
                        TerrainSample.data_status == "LIVE",
                    )
                    .order_by(TerrainSample.computed_at.desc())
                    .first()
                )
            finally:
                if self._db is None:
                    session.close()
            if row is None:
                return None
            return {
                "latitude": row.latitude,
                "longitude": row.longitude,
                "data_status": row.data_status,
                "data_source": row.data_source,
                "provider": row.provider,
                "provider_role": "primary",
                "dataset": row.dataset,
                "elevation_m": row.elevation_m,
                "slope_percent": row.slope_percent,
                "slope_degrees": row.slope_degrees,
                "slope_category": row.slope_category,
                "elevation_change_m": row.elevation_change_m,
                "slope_window_arcsec": row.slope_window_arcsec,
                "sample_radius_km": None,
                "sample_count": 9,
                "computed_at": row.computed_at.isoformat() if row.computed_at is not None else None,
            }
        except Exception:  # pragma: no cover - cache must never break terrain
            return None

    def _db_set(self, payload: Dict[str, Any]) -> None:
        if config.TERRAIN_DB_CACHE != "on" or payload.get("data_status") != "LIVE":
            return
        try:
            from app.database import SessionLocal
            from app.models import TerrainSample

            session = self._db or SessionLocal()
            try:
                lat_grid, lng_grid = self._grid_cell(payload["latitude"], payload["longitude"])
                session.query(TerrainSample).filter(
                    TerrainSample.latitude == lat_grid,
                    TerrainSample.longitude == lng_grid,
                    TerrainSample.data_source == payload.get("data_source"),
                ).delete()
                session.add(
                    TerrainSample(
                        latitude=lat_grid,
                        longitude=lng_grid,
                        elevation_m=payload.get("elevation_m"),
                        slope_degrees=payload.get("slope_degrees"),
                        slope_percent=payload.get("slope_percent"),
                        slope_category=payload.get("slope_category"),
                        elevation_change_m=payload.get("elevation_change_m"),
                        slope_window_arcsec=payload.get("slope_window_arcsec"),
                        dataset=payload.get("dataset"),
                        data_source=payload.get("data_source"),
                        provider=payload.get("provider"),
                        data_status="LIVE",
                    )
                )
                session.commit()
            finally:
                if self._db is None:
                    session.close()
        except Exception:  # pragma: no cover - cache must never break terrain
            pass

    # ---------------- Public entry point ----------------

    def get_elevation_fast(self, latitude: float, longitude: float) -> Dict[str, Any]:
        """Elevation-only sample back by real NASA SRTM (fast path).

        Used by the Terrain map for progressive loading: /api/elevation serves the
        instant number (single cached-tile bilinear read, no DB round-trip, no
        slope window), and /api/terrain computes the full slope/drainage window
        when the popup actually needs it. Values are real — never fabricated.
        """
        cache_key = f"elevfast:{round(latitude, 4)}:{round(longitude, 4)}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        flight_key = f"elevfast:inflight:{cache_key}"
        slot, is_leader = _inflight_acquire(flight_key)
        if not is_leader:
            value = _inflight_wait(slot)
            if isinstance(value, dict):
                return value
            raise HttpFetchError("terrain single-flight leader produced no elevation payload")

        payload: Optional[Dict[str, Any]] = None
        try:
            payload = self._elevation_fast_compute(latitude, longitude)
            slim = dict(payload)
            if payload.get("data_status") not in ("UNAVAILABLE", "NOT_CONFIGURED"):
                note = "Elevation sample (fast path); slope/drainage available via /api/terrain."
                provider_reason = payload.get("reason")
                slim.update(
                    {
                        "slope_degrees": None,
                        "slope_percent": None,
                        "slope_category": None,
                        "elevation_change_m": None,
                        "reason": f"{provider_reason} {note}".strip() if provider_reason else note,
                    }
                )
            ttl = (
                config.TERRAIN_FAILURE_CACHE_TTL_SEC
                if slim.get("data_status") in ("UNAVAILABLE", "NOT_CONFIGURED")
                else None
            )
            self._cache.set(cache_key, slim, ttl_seconds=ttl)
            return slim
        finally:
            _inflight_done(flight_key, slot, payload)

    def _elevation_fast_compute(self, latitude: float, longitude: float) -> Dict[str, Any]:
        """Elevation-only route for the fast path (cache/single-flight handled by
        the caller). Falls back to the configured Open-Meteo elevation provider
        when NASA Earthdata is not configured rather than failing the shim."""
        if self._openmeteo_only:
            return self._proxy_openmeteo(latitude, longitude, fallback=False)
        if not self._nasa.configured():
            if config.NASA_TERRAIN_FALLBACK_OPENMETEO:
                try:
                    return self._proxy_openmeteo(
                        latitude, longitude, fallback=True,
                        fallback_reason=(
                            "NASA Earthdata token not configured; serving configured "
                            "Open-Meteo elevation fallback."
                        ),
                    )
                except HttpFetchError as exc:
                    return self._elevation_unavailable(
                        latitude, longitude,
                        f"NASA Earthdata token not configured and Open-Meteo elevation fallback failed ({exc}).",
                    )
            return self._unavailable(
                latitude, longitude, "NOT_CONFIGURED",
                "NASA Earthdata token not configured; elevation fast path needs SRTM.",
            )
        return self.get_terrain(latitude, longitude)

    def _elevation_unavailable(self, latitude: float, longitude: float, reason: str) -> Dict[str, Any]:
        return {
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "data_status": "UNAVAILABLE",
            "data_source": "Open-Meteo elevation (SRTM-derived)",
            "provider": "open-meteo",
            "provider_role": "fallback",
            "dataset": "Open-Meteo elevation (SRTM/COP90)",
            "elevation_m": None,
            "slope_percent": None,
            "slope_degrees": None,
            "slope_category": None,
            "elevation_change_m": None,
            "sample_radius_km": config.TERRAIN_SAMPLE_KM,
            "sample_count": 0,
            "computed_at": _utc_now(),
            "reason": reason,
        }

    def get_terrain(self, latitude: float, longitude: float) -> Dict[str, Any]:
        cache_key = f"terrain:{round(latitude, 4)}:{round(longitude, 4)}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        flight_key = f"terrain:full:{cache_key}"
        slot, is_leader = _inflight_acquire(flight_key)
        if not is_leader:
            value = _inflight_wait(slot)
            if isinstance(value, dict):
                return value
            raise HttpFetchError("terrain single-flight leader produced no payload")

        payload: Optional[Dict[str, Any]] = None
        try:
            payload = self._compute_terrain(latitude, longitude)
            ttl = (
                config.TERRAIN_FAILURE_CACHE_TTL_SEC
                if payload.get("data_status") in ("UNAVAILABLE", "NOT_CONFIGURED")
                else None
            )
            self._cache.set(cache_key, payload, ttl_seconds=ttl)
            return payload
        finally:
            _inflight_done(flight_key, slot, payload)

    def _compute_terrain(self, latitude: float, longitude: float) -> Dict[str, Any]:
        """No-cache/no-flight body for get_terrain. The DB cache is consulted
        BEFORE the NASA token gate so a previously validated SRTM sample keeps
        serving elevation even if the operator later removes the token."""
        if self._openmeteo_only:
            return self._proxy_openmeteo(latitude, longitude, fallback=False)

        fallback = config.NASA_TERRAIN_FALLBACK_OPENMETEO

        db_hit = self._db_get(latitude, longitude)
        if db_hit is not None:
            return db_hit

        if self._nasa.configured():
            try:
                payload = self._nasa_payload(latitude, longitude)
                self._db_set(payload)
                return payload
            except NasaAuthError:
                base_reason = (
                    "NASA Earthdata rejected the credentials (401/403). "
                    "Verify the NASA_EARTHDATA_TOKEN / apikeynasa.env token."
                )
                payload = self._unavailable(latitude, longitude, "UNAVAILABLE", base_reason)
            except NasaTileMissingError:
                payload = self._unavailable(
                    latitude, longitude, "UNAVAILABLE",
                    "NASA SRTMGL1 has no tile at this coordinate (out of coverage).",
                )
            except (NasaElevationError, HttpFetchError):
                payload = self._unavailable(
                    latitude, longitude, "UNAVAILABLE",
                    "NASA Earthdata unreachable or failed to serve the SRTM tile.",
                )
            if fallback:
                try:
                    return self._proxy_openmeteo(
                        latitude, longitude, fallback=True,
                        fallback_reason=(
                            "NASA SRTM unavailable; serving configured Open-Meteo fallback: "
                            + (payload.get("reason") or "see upstream status.")
                        ),
                    )
                except HttpFetchError:
                    return payload
            return payload

        # No NASA token configured.
        reason = (
            "NASA Earthdata token not configured. "
            "Set NASA_EARTHDATA_TOKEN in backend/.env or the apikeynasa.env file."
        )
        if fallback:
            try:
                return self._proxy_openmeteo(
                    latitude, longitude, fallback=True,
                    fallback_reason=(
                        "NASA SRTM not configured; serving configured Open-Meteo fallback."
                    ),
                )
            except HttpFetchError:
                reason = "NASA Earthdata token not configured and Open-Meteo fallback failed."
        return self._unavailable(latitude, longitude, "NOT_CONFIGURED", reason)

    def _proxy_openmeteo(
        self,
        latitude: float,
        longitude: float,
        *,
        fallback: bool,
        fallback_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Open-Meteo path for the orchestrated instance (fallback label when used)."""
        try:
            return self._openmeteo_payload(latitude, longitude, fallback=fallback, fallback_reason=fallback_reason)
        except HttpFetchError as exc:
            if fallback:
                raise
            payload = {
                "latitude": round(latitude, 6),
                "longitude": round(longitude, 6),
                "data_status": "UNAVAILABLE",
                "data_source": "Open-Meteo elevation (SRTM-derived)",
                "provider": "open-meteo",
                "provider_role": "primary",
                "dataset": "Open-Meteo elevation (SRTM/COP90)",
                "elevation_m": None,
                "slope_percent": None,
                "slope_degrees": None,
                "slope_category": None,
                "elevation_change_m": None,
                "sample_radius_km": config.TERRAIN_SAMPLE_KM,
                "sample_count": 0,
                "computed_at": _utc_now(),
                "reason": f"Open-Meteo elevation unreachable or rejected the request ({exc}).",
            }
            return payload

    def _unavailable(
        self,
        latitude: float,
        longitude: float,
        status: str,
        reason: str,
    ) -> Dict[str, Any]:
        return {
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "data_status": status,
            "data_source": None,
            "provider": "nasa" if status == "UNAVAILABLE" else None,
            "provider_role": None,
            "dataset": None,
            "elevation_m": None,
            "slope_percent": None,
            "slope_degrees": None,
            "slope_category": None,
            "elevation_change_m": None,
            "sample_radius_km": config.TERRAIN_SAMPLE_KM,
            "sample_count": 0,
            "computed_at": _utc_now(),
            "reason": reason,
        }

    def get_terrain_grid(
        self,
        north: float,
        south: float,
        east: float,
        west: float,
        step: float = 0.05,
        max_points: int = 600,
    ) -> Dict[str, Any]:
        """Terrain layer for the weather & hazard map: real elevation + slope per
        cell via the normal per-point SRTM/fallback chain (cached in DB + TTL,
        so repeated views are cheap). Per-cell statuses and the grid aggregate are
        honest — never fabricated values."""
        n_int = int(round(north / step))
        s_int = int(round(south / step))
        e_int = int(round(east / step))
        w_int = int(round(west / step))
        exported: List[Dict[str, Any]] = []
        statuses: set = set()

        def _outside(target_lat: float, target_lon: float) -> bool:
            return target_lat < 6.0 or target_lat > 37.4 or target_lon < 68.0 or target_lon > 98.5

        # Entire-window guard: short-circuit only when NO cell in the window can
        # be inside the India SRTM domain; otherwise sample the real inside cells.
        north_edge = round(n_int * step, 6)
        south_edge = round(s_int * step, 6)
        east_edge = round(e_int * step, 6)
        west_edge = round(w_int * step, 6)
        if north_edge < 6.0 or south_edge > 37.4 or east_edge < 68.0 or west_edge > 98.5:
            return {
                "points": [
                    {
                        "latitude": south_edge,
                        "longitude": west_edge,
                        "elevation_m": None,
                        "slope_percent": None,
                        "slope_category": None,
                        "data_status": "UNAVAILABLE",
                        "data_source": "SRTM coverage",
                        "provider": None,
                        "reason": "Request bounds fall outside the India SRTM data domain.",
                    }
                ],
                "data_status": "UNAVAILABLE",
                "data_source": "SRTM coverage",
                "reason": "Request bounds fall outside the India SRTM data domain.",
                "valid_time": _utc_now(),
            }

        # Resample rows in case max_points truncates the column list.
        rows_needed = n_int - s_int + 1
        col_step = max(1, int(math.ceil((e_int - w_int + 1) / max(1, max_points // rows_needed))))
        cols = [round(w_int * step, 6) + c * step for c in range(0, e_int - w_int + 1, col_step)]
        cells: List[tuple] = [
            (lat, lng)
            for lat in [round(n_int * step, 6) - i * step for i in range(n_int - s_int + 1)]
            for lng in cols
            if not _outside(lat, lng)
        ][: max_points]

        workers = max(1, min(config.TERRAIN_GRID_WORKERS, len(cells) or 1))

        def _unavailable_cell(lat: float, lng: float, reason: str) -> Dict[str, Any]:
            point = {
                "latitude": lat,
                "longitude": lng,
                "elevation_m": None,
                "slope_percent": None,
                "slope_category": None,
                "data_status": "UNAVAILABLE",
                "data_source": "SRTM coverage",
                "provider": None,
                "reason": reason,
            }
            exported.append(point)
            statuses.add("UNAVAILABLE")
            return point

        timeout_reason = (
            "SRTM provider unreachable — grid fetch timed out; remaining cells "
            "marked UNAVAILABLE (values never invented)."
        )
        deadline = time.monotonic() + config.TERRAIN_GRID_TIMEOUT_SEC

        if workers > 1:
            pool = ThreadPoolExecutor(max_workers=workers)
            try:
                futures = {pool.submit(self.get_terrain, lat, lng): (lat, lng) for lat, lng in cells}
                pending = set(futures)
                try:
                    for future in as_completed(futures, timeout=max(0.0, deadline - time.monotonic())):
                        pending.discard(future)
                        try:
                            p = future.result()
                        except Exception:
                            lat, lng = futures[future]
                            _unavailable_cell(
                                lat, lng,
                                "Provider failed for this cell; marked UNAVAILABLE (values never invented).",
                            )
                            continue
                        statuses.add(p.get("data_status", "UNAVAILABLE"))
                        exported.append(
                            {
                                "latitude": p["latitude"],
                                "longitude": p["longitude"],
                                "elevation_m": p.get("elevation_m"),
                                "slope_percent": p.get("slope_percent"),
                                "slope_category": p.get("slope_category"),
                                "data_status": p.get("data_status", "UNAVAILABLE"),
                                "data_source": p.get("data_source"),
                                "provider": p.get("provider"),
                                "reason": p.get("reason"),
                            }
                        )
                except TimeoutError:
                    for future in pending:
                        lat, lng = futures[future]
                        _unavailable_cell(lat, lng, timeout_reason)
            finally:
                # wait=False so a slow SRTM source cannot hold the grid hostage
                # past the deadline; the worker threads drain on their own.
                pool.shutdown(wait=False)
        else:
            for lat, lng in cells:
                if time.monotonic() >= deadline:
                    _unavailable_cell(lat, lng, timeout_reason)
                    continue
                try:
                    p = self.get_terrain(lat, lng)
                except Exception:
                    _unavailable_cell(
                        lat, lng,
                        "Provider failed for this cell; marked UNAVAILABLE (values never invented).",
                    )
                    continue
                statuses.add(p.get("data_status", "UNAVAILABLE"))
                exported.append(
                    {
                        "latitude": p["latitude"],
                        "longitude": p["longitude"],
                        "elevation_m": p.get("elevation_m"),
                        "slope_percent": p.get("slope_percent"),
                        "slope_category": p.get("slope_category"),
                        "data_status": p.get("data_status", "UNAVAILABLE"),
                        "data_source": p.get("data_source"),
                        "provider": p.get("provider"),
                        "reason": p.get("reason"),
                    }
                )

        if not exported:
            return {
                "points": [],
                "data_status": "UNAVAILABLE",
                "data_source": None,
                "reason": "No terrain cells sampled in the requested window.",
                "valid_time": _utc_now(),
            }

        if "LIVE" in statuses:
            status = "LIVE"
        elif "CACHED" in statuses:
            status = "CACHED"
        elif "NOT_CONFIGURED" in statuses and "UNAVAILABLE" not in statuses:
            status = "NOT_CONFIGURED"
        else:
            status = "UNAVAILABLE"
        return {
            "points": exported,
            "data_status": status,
            "data_source": "NASA SRTMGL1 (1-arc-sec) / Open-Meteo fallback",
            "reason": None if status in ("LIVE", "CACHED") else (exported[0].get("reason") if exported else None),
            "valid_time": _utc_now(),
        }


def _round_and_clamp(value: float, lo: float = -90.0, hi: float = 90.0) -> float:
    return round(max(lo, min(hi, value)), 6)


terrain_service = TerrainService()