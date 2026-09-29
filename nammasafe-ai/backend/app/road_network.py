"""
Road-graph loading, hazard overlay and navigability model for NammaSafe AI.

The pilot graph is a curated representation of the principal Chamoli corridors
(NH-07 Alaknanda valley, Dhauliganga/Rishiganga access, Nandakini valley, Pindar
valley and the Karnaprayag-Gwaldam southern egress). It is labelled
`curated_demo` and must never be presented as live network data.
"""

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from app.geo import (
    distance_point_to_segment,
    extract_rings,
    segment_intersects_rings,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
ROAD_NETWORK_FILE = os.path.join(DATA_DIR, "road_network.json")

ROAD_SPEED_KMH = {
    "primary": 40.0,
    "secondary": 30.0,
    "rural": 20.0,
    "footpath": 10.0,
}

SLOPE_MULTIPLIER = {
    "flat": 1.0,
    "moderate": 1.3,
    "steep": 1.8,
}

CLOSED_CRITICAL_HAZARDS = {
    "Land Subsidence",
    "Flash Flood",
    "Flood",
    "Cloudburst",
    "Avalanche",
    "Glacial Lake Outburst Flood",
    "Earthquake",
}

HIGH_HAZARD_MULTIPLIER = {
    "Landslide": 5.0,
    "Rockfall": 5.0,
    "Land Subsidence": 5.0,
    "Flash Flood": 6.0,
    "Flood": 6.0,
    "Cloudburst": 6.0,
    "Avalanche": 5.0,
    "Wildfire": 4.0,
    "Earthquake": 6.0,
}

BRIDGE_CROSSING_MULTIPLIER = 1.5

ROAD_DAMAGE_KEYWORDS = ("road", "bridge", "culvert", "nh-07", "barrier", "slope", "cave", "cutoff")


def load_road_network() -> Dict[str, Any]:
    """Load the curated pilot road graph."""
    with open(ROAD_NETWORK_FILE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def seed_road_conditions() -> List[Dict[str, Any]]:
    """
    Pilot road/bridge status seeds derived from demo field reports and events.
    Each entry maps to a graph edge and is traced to its report reference.
    """
    return [
        {
            "id": "rc-002",
            "segment_id": "e-helang-joshimath",
            "status": "RESTRICTED",
            "hazard_type": "landslide",
            "severity": "High",
            "reason": "Active rockfall / shooting stones on NH-07 (Field Report fr-003, Event ev-07/ev-08)",
            "source": "field_report",
            "report_ref": "fr-003",
            "effective_from": "2025-08-27",
            "expires_at": None,
        },
        {
            "id": "rc-001",
            "segment_id": "e-helang-urgam",
            "status": "RESTRICTED",
            "hazard_type": "bridge_damage",
            "severity": "Medium",
            "reason": "Rural culvert collapse on upper-hamlet approach (Field Report fr-005)",
            "source": "field_report",
            "report_ref": "fr-005",
            "effective_from": "2025-08-28",
            "expires_at": None,
        },
    ]


class RoadGraph:
    """
    Navigable graph built from the curated road network plus a hazard overlay
    derived from red zones, habitation risk scores and field reports.

    Closure rule: an edge intersecting a *critical* hazard polygon is closed,
    UNLESS one of its endpoint nodes is the origin or the destination snapped
    node (so evacuees may exit the danger zone but never route through it).
    """

    def __init__(self, road_network: Optional[Dict[str, Any]] = None) -> None:
        net = road_network or load_road_network()
        self.data_class = net.get("data_class", "curated_demo")
        self.nodes: Dict[str, Dict[str, Any]] = net["nodes"]
        self.edges: List[Dict[str, Any]] = net["edges"]
        self.edges_by_id = {e["id"]: e for e in self.edges}
        self.adj: Dict[str, List[Dict[str, Any]]] = {nid: [] for nid in self.nodes}
        self.edge_status: Dict[str, Dict[str, Any]] = {}
        self.edge_multiplier: Dict[str, float] = {}
        self.edge_hazards: Dict[str, List[Dict[str, Any]]] = {}
        self.edge_score_multiplier: Dict[str, float] = {}
        self._build_adjacency()

    def _build_adjacency(self) -> None:
        for edge in self.edges:
            a, b = edge["from"], edge["to"]
            if a not in self.nodes or b not in self.nodes:
                continue
            self.adj.setdefault(a, []).append({"to": b, "edge": edge})
            self.adj.setdefault(b, []).append({"to": a, "edge": edge})

    def node_coords(self, node_id: str) -> Optional[Tuple[float, float]]:
        node = self.nodes.get(node_id)
        if not node:
            return None
        return (float(node["lat"]), float(node["lng"]))

    def snap(self, lat: float, lng: float, max_dist_m: float, fallback_m: Optional[float] = None) -> Optional[str]:
        """Nearest node within max_dist_m, else nearest node within fallback_m."""
        best: Optional[str] = None
        best_dist = max_dist_m
        for nid, node in self.nodes.items():
            dist = distance_point_to_segment(lat, lng, node["lat"], node["lng"], node["lat"], node["lng"])
            if dist <= best_dist:
                best_dist = dist
                best = nid
        if best is not None:
            return best
        if fallback_m is None or fallback_m <= max_dist_m:
            return None
        nearest: Optional[str] = None
        nearest_dist = fallback_m
        for nid, node in self.nodes.items():
            dist = distance_point_to_segment(lat, lng, node["lat"], node["lng"], node["lat"], node["lng"])
            if dist <= nearest_dist:
                nearest_dist = dist
                nearest = nid
        return nearest

    def edge_speed_ms(self, edge: Dict[str, Any]) -> float:
        speed = ROAD_SPEED_KMH.get(edge.get("road_class", "rural"), 20.0)
        return speed / 3.6

    def edge_cost(self, edge: Dict[str, Any], risk_aware: bool = True) -> float:
        """Risk-weighted travel time cost for an edge (length/speed x multiplier)."""
        length_m = float(edge.get("length_m", 1000.0))
        base = length_m / self.edge_speed_ms(edge)
        if not risk_aware:
            return base
        return base * self.edge_multiplier.get(edge["id"], 1.0)

    def build_hazard_overlay(
        self,
        red_zones: List[Dict[str, Any]],
        habitations: List[Dict[str, Any]],
        field_reports: List[Dict[str, Any]],
        road_conditions: List[Dict[str, Any]],
        origin_node: Optional[str],
        dest_node: Optional[str],
    ) -> None:
        """Compute per-edge status, multiplier and hazard ledger."""
        self.edge_status = {}
        self.edge_multiplier = {}
        self.edge_hazards = {}

        critical_zones: List[Dict[str, Any]] = []
        high_zones: List[Dict[str, Any]] = []
        for zone in red_zones:
            rings = extract_rings(zone.get("zone_geometry", {}))
            if not rings:
                continue
            hazard_type = zone.get("hazard_type", "")
            risk_level = zone.get("risk_level", "")
            if risk_level == "Critical" and hazard_type in CLOSED_CRITICAL_HAZARDS:
                critical_zones.append({"zone": zone, "rings": rings})
            elif risk_level == "High" and hazard_type in HIGH_HAZARD_MULTIPLIER:
                high_zones.append({"zone": zone, "rings": rings})

        condition_by_segment = {c["segment_id"]: c for c in road_conditions}
        reports = [r for r in field_reports if r.get("verified", True)]

        for edge in self.edges:
            edge_id = edge["id"]
            a_lat, a_lng = self.nodes[edge["from"]]["lat"], self.nodes[edge["from"]]["lng"]
            b_lat, b_lng = self.nodes[edge["to"]]["lat"], self.nodes[edge["to"]]["lng"]

            status = "OPEN"
            multiplier = 1.0
            init = SLOPE_MULTIPLIER.get(edge.get("slope_class", "flat"), 1.0)
            multiplier *= init
            hazards: List[Dict[str, Any]] = []

            if edge.get("bridge"):
                multiplier *= BRIDGE_CROSSING_MULTIPLIER

            # Critical polygons => closed unless the edge touches the origin/destination
            in_critical = False
            for entry in critical_zones:
                if segment_intersects_rings(a_lat, a_lng, b_lat, b_lng, entry["rings"]):
                    in_critical = True
                    hazards.append({
                        "hazard_type": entry["zone"].get("hazard_type", "Hazard"),
                        "risk_level": "Critical",
                        "zone_id": entry["zone"].get("id"),
                        "zone_name": entry["zone"].get("zone_name", "Critical zone"),
                    })
            if in_critical:
                touches_terminus = edge["from"] in (origin_node, dest_node) or edge["to"] in (origin_node, dest_node)
                if touches_terminus:
                    multiplier *= 4.0
                    status = "HIGH_RISK_EXIT"
                else:
                    status = "CLOSED"

            # High polygons => weight multiplier
            if status == "OPEN":
                for entry in high_zones:
                    if segment_intersects_rings(a_lat, a_lng, b_lat, b_lng, entry["rings"]):
                        hazard_type = entry["zone"].get("hazard_type", "Hazard")
                        multiplier *= HIGH_HAZARD_MULTIPLIER.get(hazard_type, 3.0)
                        hazards.append({
                            "hazard_type": hazard_type,
                            "risk_level": "High",
                            "zone_id": entry["zone"].get("id"),
                            "zone_name": entry["zone"].get("zone_name", "High-risk zone"),
                        })

            # Habitation proximity: elevated hazard score near the corridor
            if status == "OPEN":
                for hab in habitations:
                    lat, lng = hab.get("latitude"), hab.get("longitude")
                    if lat is None or lng is None:
                        continue
                    risk = max(hab.get("landslide_risk", 0.0), hab.get("flood_risk", 0.0))
                    if risk < 80.0:
                        continue
                    dist = distance_point_to_segment(lat, lng, a_lat, a_lng, b_lat, b_lng)
                    if dist <= 1500.0:
                        multiplier *= 1.5
                        hazards.append({
                            "hazard_type": "proximity_risk",
                            "risk_level": "High",
                            "zone_id": hab.get("id"),
                            "zone_name": hab.get("village_name", "Risk-prone habitation"),
                        })

            # Verified field reports describing road/bridge damage
            if status == "OPEN":
                for report in reports:
                    desc = str(report.get("report_type", "")) + " " + str(report.get("description", ""))
                    if not any(kw in desc.lower() for kw in ROAD_DAMAGE_KEYWORDS):
                        continue
                    r_lat, r_lng = report.get("latitude"), report.get("longitude")
                    if r_lat is None or r_lng is None:
                        continue
                    dist = distance_point_to_segment(r_lat, r_lng, a_lat, a_lng, b_lat, b_lng)
                    if dist <= 2000.0:
                        severity = report.get("severity", "High")
                        if severity == "Critical":
                            status = "CLOSED"
                        else:
                            multiplier *= 2.0
                        hazards.append({
                            "hazard_type": "road_damage",
                            "risk_level": severity,
                            "report_ref": report.get("id"),
                            "zone_name": report.get("report_type", "Road damage"),
                        })

            # Explicit condition overrides
            condition = condition_by_segment.get(edge_id)
            if condition:
                if condition["status"] == "CLOSED":
                    status = "CLOSED"
                    multiplier *= 100.0
                elif condition["status"] == "RESTRICTED":
                    multiplier *= 2.5
                    if status == "OPEN":
                        status = "RESTRICTED"
                hazards.append({
                    "hazard_type": condition.get("hazard_type", "road_condition"),
                    "risk_level": condition.get("severity", "High"),
                    "condition_id": condition.get("id"),
                    "zone_name": condition.get("reason", "Road condition"),
                })

            self.edge_status[edge_id] = {"status": status, "reason": hazards}
            self.edge_multiplier[edge_id] = max(1.0, multiplier)
            self.edge_hazards[edge_id] = hazards

    def is_open(self, edge_id: str) -> bool:
        return self.edge_status.get(edge_id, {}).get("status") != "CLOSED"