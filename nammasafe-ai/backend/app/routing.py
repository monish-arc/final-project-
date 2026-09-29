"""
Risk-aware routing engine for NammaSafe AI evacuation planning.

Implements a weighted A* search over the curated pilot road graph. The default
provider (`LocalGraphRouter`) runs fully offline and never relies on a public
routing server; it is interchangeable through RoutingProvider if OSRM support is
added later.
"""

from heapq import heappop, heappush
from typing import Any, Dict, List, Optional, Tuple

from app.config import EVACUATION_WALK_SPEED_KMH
from app.geo import haversine, to_geojson_line


class RouteUnreachable(Exception):
    """Raised when no connected, open road path exists between locations."""


def _heuristic(
    a_lat: float, a_lng: float, b_lat: float, b_lng: float, max_speed_ms: float
) -> float:
    return haversine(a_lat, a_lng, b_lat, b_lng) / max_speed_ms


def find_path(
    graph: Any,
    origin_node: str,
    dest_node: str,
    risk_aware: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    Weighted A* over the graph's open edges.
    Returns {"nodes": [...], "edge_ids": [...]} or None when unreachable.
    """
    origin_coords = graph.node_coords(origin_node)
    dest_coords = graph.node_coords(dest_node)
    if not origin_coords or not dest_coords:
        return None

    max_speed_ms = max(graph.edge_speed_ms(edge) for edge in graph.edges) or 1.0

    g_cost: Dict[str, float] = {origin_node: 0.0}
    came_from: Dict[str, Optional[str]] = {origin_node: None}
    edge_used: Dict[str, str] = {}
    closed: set = set()
    start_heuristic = _heuristic(origin_coords[0], origin_coords[1], dest_coords[0], dest_coords[1], max_speed_ms)
    heap = [(start_heuristic, 0.0, origin_node)]

    while heap:
        _, cost, node = heappop(heap)
        if node in closed:
            continue
        closed.add(node)
        if node == dest_node:
            break
        node_coords = graph.node_coords(node)
        for neighbor in graph.adj.get(node, []):
            nxt = neighbor["to"]
            if nxt in closed:
                continue
            edge = neighbor["edge"]
            if not graph.is_open(edge["id"]):
                continue
            nxt_coords = graph.node_coords(nxt)
            if not nxt_coords:
                continue
            new_cost = cost + graph.edge_cost(edge, risk_aware)
            if new_cost < g_cost.get(nxt, float("inf")):
                g_cost[nxt] = new_cost
                came_from[nxt] = node
                edge_used[nxt] = edge["id"]
                dest_coords_non_null = dest_coords
                h = _heuristic(nxt_coords[0], nxt_coords[1], dest_coords_non_null[0], dest_coords_non_null[1], max_speed_ms)
                heappush(heap, (new_cost + h, new_cost, nxt))

    if dest_node not in g_cost:
        return None

    nodes: List[str] = []
    node: Optional[str] = dest_node
    while node is not None:
        nodes.append(node)
        node = came_from.get(node)
    nodes.reverse()

    edge_ids = [edge_used[nodes[i]] for i in range(1, len(nodes))]
    return {"nodes": nodes, "edge_ids": edge_ids}


def _access_distance(
    lat: float, lng: float, node_coords: Optional[Tuple[float, float]]
) -> float:
    if not node_coords:
        return 0.0
    return haversine(lat, lng, node_coords[0], node_coords[1])


def build_route_detail(
    graph: Any,
    origin_node: str,
    dest_node: str,
    origin_coords: Tuple[float, float],
    dest_coords: Tuple[float, float],
    risk_aware: bool = True,
    walk_speed_kmh: float = EVACUATION_WALK_SPEED_KMH,
) -> Optional[Dict[str, Any]]:
    """Compute full route metrics for a snapped origin/destination pair."""
    path = find_path(graph, origin_node, dest_node, risk_aware=risk_aware)
    if path is None:
        return None

    nodes = path["nodes"]
    edge_ids = path["edge_ids"]
    snap_origin = graph.node_coords(origin_node)
    snap_dest = graph.node_coords(dest_node)

    geometry_points: List[Tuple[float, float]] = [(origin_coords[0], origin_coords[1])]
    for nid in nodes:
        coords = graph.node_coords(nid)
        if coords:
            geometry_points.append((coords[0], coords[1]))
    geometry_points.append((dest_coords[0], dest_coords[1]))

    distance_m = _access_distance(*origin_coords, snap_origin) + _access_distance(*dest_coords, snap_dest)
    drive_seconds = 0.0
    edge_ledger: List[Dict[str, Any]] = []
    risky_edges: List[Dict[str, Any]] = []

    for i in range(1, len(nodes)):
        a_coords = graph.node_coords(nodes[i - 1])
        b_coords = graph.node_coords(nodes[i])
        distance_m += haversine(a_coords[0], a_coords[1], b_coords[0], b_coords[1])

    for edge_id in edge_ids:
        edge = graph.edges_by_id[edge_id]
        length_m = edge["length_m"]
        speed_ms = graph.edge_speed_ms(edge)
        drive_seconds += length_m / speed_ms
        multiplier = graph.edge_multiplier.get(edge_id, 1.0)
        status = graph.edge_status.get(edge_id, {}).get("status", "OPEN")
        hazards = graph.edge_hazards.get(edge_id, [])
        entry = {
            "edge_id": edge_id,
            "name": edge["name"],
            "from": graph.nodes[edge["from"]]["name"],
            "to": graph.nodes[edge["to"]]["name"],
            "length_m": length_m,
            "bridge": edge.get("bridge", False),
            "slope_class": edge.get("slope_class", "flat"),
            "multiplier": round(multiplier, 2),
            "status": status,
            "hazards": hazards,
        }
        edge_ledger.append(entry)
        if entry["hazards"] or multiplier >= 2.0:
            risky_edges.append(entry)

    distance_km = distance_m / 1000.0
    drive_min = drive_seconds / 60.0
    walk_seconds = (
        _access_distance(*origin_coords, snap_origin)
        + _access_distance(*dest_coords, snap_dest)
    ) / (walk_speed_kmh / 3.6)
    travel_min = drive_min + walk_seconds / 60.0

    # Safety scoring: share of risky edges and risky length over the route.
    risky_len = sum(e["length_m"] for e in risky_edges)
    edge_share = len(risky_edges) / max(1, len(edge_ledger))
    length_share = risky_len / max(1.0, distance_m)
    risk_points = min(85, round(20 * edge_share + 40 * length_share))
    safety_score = 100 - risk_points

    hazards_encountered: List[Dict[str, Any]] = []
    seen = set()
    for entry in edge_ledger:
        if not entry["hazards"]:
            continue
        edge = graph.edges_by_id.get(entry["edge_id"])
        anchor = graph.node_coords(edge["from"]) if edge else None
        for hazard in entry["hazards"]:
            key = (entry["edge_id"], hazard.get("zone_name") or hazard.get("hazard_type"))
            if key in seen:
                continue
            seen.add(key)
            hazards_encountered.append({
                **hazard,
                "edge_id": entry["edge_id"],
                "road": entry["name"],
                "status": entry["status"],
                "latitude": anchor[0] if anchor else None,
                "longitude": anchor[1] if anchor else None,
            })

    return {
        "nodes": nodes,
        "edge_ids": edge_ids,
        "geometry": to_geojson_line(geometry_points),
        "distance_km": round(distance_km, 3),
        "travel_time_min": round(travel_min, 1),
        "drive_time_min": round(drive_min, 1),
        "walk_time_min": round(walk_seconds / 60.0, 1),
        "safety_score": int(safety_score),
        "risk_score": int(risk_points),
        "risky_edge_ids": [e["edge_id"] for e in risky_edges],
        "hazards_encountered": hazards_encountered,
        "edge_ledger": edge_ledger,
    }


class RoutingProvider:
    """Interface contract for routing backends."""

    def plan(
        self,
        graph: Any,
        origin_node: str,
        dest_node: str,
        origin_coords: Tuple[float, float],
        dest_coords: Tuple[float, float],
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def shortest(
        self,
        graph: Any,
        origin_node: str,
        dest_node: str,
        origin_coords: Tuple[float, float],
        dest_coords: Tuple[float, float],
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError


class LocalGraphRouter(RoutingProvider):
    """Offline, risk-aware router over the curated pilot graph."""

    def plan(
        self,
        graph: Any,
        origin_node: str,
        dest_node: str,
        origin_coords: Tuple[float, float],
        dest_coords: Tuple[float, float],
    ) -> Optional[Dict[str, Any]]:
        return build_route_detail(graph, origin_node, dest_node, origin_coords, dest_coords, risk_aware=True)

    def shortest(
        self,
        graph: Any,
        origin_node: str,
        dest_node: str,
        origin_coords: Tuple[float, float],
        dest_coords: Tuple[float, float],
    ) -> Optional[Dict[str, Any]]:
        return build_route_detail(graph, origin_node, dest_node, origin_coords, dest_coords, risk_aware=False)


def get_router() -> RoutingProvider:
    """Config-driven provider selection (local pilot router for now)."""
    return LocalGraphRouter()