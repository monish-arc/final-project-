"""Routing service exposing safe route options to a destination.

Two backends are offered, selected by config.ROUTING_PROVIDER:
  osrm  -> public OSRM server (real road network; no risk overlay), LIVE/UNREACHABLE
  local -> the curated, risk-aware pilot A* graph router (offline, deterministic)
  auto  -> try OSRM first, fall back to the local graph when the points are not
           reachable on the real network or the provider fails

All payloads carry explicit data_status / data_source so "no route available"
can never be mistaken for an empty success.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app import config
from app.cache import TTLCache
from app.http_client import HttpFetchError, http_get


class OsrmRouter:
    name = "OSRM (open routing service)"

    def route(
        self, origin: Tuple[float, float], destination: Tuple[float, float]
    ) -> Dict[str, Any]:
        origin_lng, origin_lat = origin[1], origin[0]
        dest_lng, dest_lat = destination[1], destination[0]
        coords = f"{origin_lng},{origin_lat};{dest_lng},{dest_lat}"
        url = f"{config.OSRM_BASE_URL}/route/v1/driving/{coords}"
        response = http_get(
            url,
            params={"overview": "full", "geometries": "geojson", "steps": "false"},
            timeout=15.0,
        )
        if response.status_code >= 400:
            raise HttpFetchError(f"OSRM rejected ({response.status_code})")
        body = response.json()
        route = (body.get("routes") or [None])[0]
        if not route:
            raise HttpFetchError("OSRM returned no route")
        return {
            "data_status": "LIVE",
            "data_source": self.name,
            "distance_km": round(route["distance"] / 1000.0, 3),
            "travel_time_min": round(route["duration"] / 60.0, 1),
            "route_geometry": route.get("geometry"),
            "data_status_raw": body.get("code"),
            "assumption": (
                "OSRM is a routing service, not a risk-assessment source; it does "
                "not weight flood/rainfall hazard corridors.",
            ),
        }


class RoutingService:
    def __init__(self) -> None:
        self._cache = TTLCache(config.ROUTER_CACHE_TTL_SEC)
        self._osrm = OsrmRouter()

    @staticmethod
    def _provider_mode() -> str:
        return (config.ROUTING_PROVIDER or "auto").lower()

    # -- local pilot graph fallback -----------------------------------------
    def _local_route(
        self,
        data: Dict[str, Any],
        origin: Tuple[float, float],
        destination: Tuple[float, float],
    ) -> Optional[Dict[str, Any]]:
        try:
            from app.road_network import RoadGraph
            from app.routing import LocalGraphRouter, build_route_detail

            graph = RoadGraph()
            origin_node = graph.snap(origin[0], origin[1], config.ROUTE_SNAP_M, fallback_m=config.ROUTE_SNAP_FALLBACK_M)
            dest_node = graph.snap(destination[0], destination[1], config.ROUTE_SNAP_M, fallback_m=config.ROUTE_SNAP_FALLBACK_M)
            if not origin_node or not dest_node:
                return None
            graph.build_hazard_overlay(
                red_zones=data.get("red_zones", []),
                habitations=data.get("habitations", []),
                field_reports=data.get("field_reports", []),
                road_conditions=data.get("road_conditions", []),
                origin_node=origin_node,
                dest_node=dest_node,
            )
            router = LocalGraphRouter()
            detail = router.plan(graph, origin_node, dest_node, origin, destination)
            if not detail:
                return None
            return {
                "data_status": "LIVE",
                "data_source": "NammaSafe AI pilot road graph (risk-aware A*)",
                "distance_km": detail["distance_km"],
                "travel_time_min": detail["travel_time_min"],
                "safety_score": detail["safety_score"],
                "risk_score": detail["risk_score"],
                "route_geometry": detail["geometry"],
                "hazards_encountered": detail["hazards_encountered"],
                "is_synthetic_route": True,
                "assumption": "Validated only on the curated pilot graph.",
            }
        except Exception:  # pragma: no cover - defensive fallback
            return None

    def safe_routes(
        self,
        data: Dict[str, Any],
        origin: Tuple[float, float],
        destination: Tuple[float, float],
    ) -> Dict[str, Any]:
        cache_key = f"route:{round(origin[0],4)},{round(origin[1],4)}:{round(destination[0],4)},{round(destination[1],4)}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        mode = self._provider_mode()
        result: Optional[Dict[str, Any]] = None
        if mode in ("osrm", "auto"):
            try:
                result = self._osrm.route(origin, destination)
                result_candidates = [result]
            except HttpFetchError:
                result_candidates = []
        else:
            result_candidates = []

        if (mode in ("auto", "local")) and not result_candidates:
            local = self._local_route(data, origin, destination)
            if local:
                result_candidates = [local]
            result = local

        if not result_candidates:
            payload = {
                "data_status": "NO_ROUTE",
                "data_source": "OSRM / pilot road graph",
                "origin": origin,
                "destination": destination,
                "options": [],
                "reason": "No connected road route could be computed for the requested points.",
            }
        else:
            payload = {
                "data_status": result_candidates[0]["data_status"],
                "data_source": result_candidates[0]["data_source"],
                "origin": origin,
                "destination": destination,
                "routing_provider": mode,
                "options": result_candidates,
            }

        self._cache.set(cache_key, payload)
        return payload


routing_service = RoutingService()