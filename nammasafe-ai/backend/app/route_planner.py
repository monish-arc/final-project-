"""
Evacuation route planner: origin resolution, safe-site selection, risk-aware
route computation, explanation and persistence for NammaSafe AI.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import uuid

from app.config import MAX_CANDIDATE_ROUTES, ROUTE_SNAP_FALLBACK_M, ROUTE_SNAP_M
from app.access_control import scope_contains
from app.geo import haversine, point_in_zone, to_geojson_line
from app.road_network import RoadGraph, seed_road_conditions
from app.routing import get_router

DISTRICT_SCOPE = {"state_id": "uk", "district_id": "chamoli", "sub_district_id": "*", "area_id": "*"}

JOSHIMATH_BLOCK_VILLAGES = {
    "hab-joshimath", "hab-raini", "hab-tapovan", "hab-helang",
    "hab-pandukeshwar", "hab-mana", "hab-urgam",
}
JOSHIMATH_CENTRAL_SCOPE = {
    "state_id": "uk", "district_id": "chamoli",
    "sub_district_id": "joshimath", "area_id": "joshimath-central",
}


class PlannerInputError(ValueError):
    """Bad or unresolvable planning request."""


def build_scope_for_area(data: Dict[str, Any], area_id: str) -> Dict[str, str]:
    area = next((a for a in data["administrative_areas"]["areas"] if a["id"] == area_id), None)
    if not area:
        raise PlannerInputError(f"Administrative area {area_id} not found")
    sub = next((s for s in data["administrative_areas"]["sub_districts"] if s["id"] == area["sub_district_id"]), None)
    if not sub:
        raise PlannerInputError(f"Sub-district for {area_id} not found")
    district = next((d for d in data["administrative_areas"]["districts"] if d["id"] == sub["district_id"]), None)
    if not district:
        raise PlannerInputError(f"District for {area_id} not found")
    return {
        "state_id": district["state_id"],
        "district_id": district["id"],
        "sub_district_id": sub["id"],
        "area_id": area["id"],
    }


def enforce_origin_scope(user: Optional[Dict[str, Any]], scope: Dict[str, str]) -> None:
    """Raise for users whose assigned jurisdiction does not contain the origin scope."""
    assignment = (user or {}).get("assignment") or {}
    if not scope_contains(assignment, scope):
        raise PermissionError(f"Origin is outside your assigned jurisdiction: {scope}")


def resolve_origin(data: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve a route request origin into a concrete coordinate + jurisdiction scope."""
    otype = (payload.get("type") or "map_click").lower()
    origin = {"type": otype, "id": None, "label": "Selected location"}

    if otype == "habitation":
        hab = next((h for h in data["habitations"] if h["id"] == payload.get("id")), None)
        if not hab:
            raise PlannerInputError("Habitation not found")
        origin["id"] = hab["id"]
        origin["label"] = hab["village_name"]
        origin["lat"] = hab["latitude"]
        origin["lng"] = hab["longitude"]
        origin["scope"] = (
            JOSHIMATH_CENTRAL_SCOPE
            if hab["id"] in JOSHIMATH_BLOCK_VILLAGES
            else DISTRICT_SCOPE
        )

    elif otype == "alert":
        alert = next((a for a in data["risk_alerts"] if a["id"] == payload.get("id")), None)
        if not alert:
            raise PlannerInputError("Risk alert not found")
        if not alert.get("latitude") or not alert.get("longitude"):
            raise PlannerInputError("Risk alert has no coordinates")
        origin["id"] = alert["id"]
        origin["label"] = alert.get("description", "Active risk alert")
        origin["lat"] = alert["latitude"]
        origin["lng"] = alert["longitude"]
        origin["scope"] = build_scope_for_area(data, alert["area_id"])

    elif otype == "event":
        event = next((e for e in data["hazard_events"] if e["id"] == payload.get("id")), None)
        if not event:
            raise PlannerInputError("Disaster event not found")
        hab = next((h for h in data["habitations"] if h["id"] == event["habitation_id"]), None)
        if not hab:
            raise PlannerInputError("Disaster event has no linked habitation")
        origin["id"] = event["id"]
        origin["label"] = f"{hab['village_name']} ({event['hazard_type']})"
        origin["lat"] = hab["latitude"]
        origin["lng"] = hab["longitude"]
        origin["scope"] = (
            JOSHIMATH_CENTRAL_SCOPE
            if hab["id"] in JOSHIMATH_BLOCK_VILLAGES
            else DISTRICT_SCOPE
        )

    elif otype == "map_click":
        lat = payload.get("latitude") or payload.get("lat")
        lng = payload.get("longitude") or payload.get("lng")
        if lat is None or lng is None:
            raise PlannerInputError("Map-click origin requires coordinates")
        origin["lat"] = float(lat)
        origin["lng"] = float(lng)
        origin["label"] = f"{lat:.4f}, {lng:.4f}"
        origin["scope"] = DISTRICT_SCOPE

    else:
        raise PlannerInputError(f"Unsupported origin type: {otype}")

    if origin.get("lat") is None or origin.get("lng") is None:
        raise PlannerInputError("Origin has no resolvable coordinates")
    return origin


def _origin_households(data: Dict[str, Any], origin: Dict[str, Any]) -> Optional[int]:
    if origin["type"] == "habitation":
        hab = next((h for h in data["habitations"] if h["id"] == origin["id"]), None)
        if hab:
            return int(hab.get("households", 100))
    return None


def _origin_summary(origin: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": origin["type"],
        "id": origin.get("id"),
        "label": origin["label"],
        "latitude": origin["lat"],
        "longitude": origin["lng"],
    }


def _zone_risk(red_zones: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [z for z in red_zones if z.get("risk_level") == "Critical"]


def select_candidate_sites(
    data: Dict[str, Any],
    origin: Dict[str, Any],
    families_count: int,
    limit: int = MAX_CANDIDATE_ROUTES,
) -> List[Dict[str, Any]]:
    """
    Rank relocation sites by safety, capacity, suitability and accessibility.
    Hard filters: sufficient net capacity, and site not inside a critical zone.
    """
    red_zones = _zone_risk(data["red_zones"])
    candidates: List[Dict[str, Any]] = []

    for site in data["relocation_sites"]:
        avail = site.get("available_capacity_families", 0)
        if avail < families_count:
            candidates.append({**site, "excluded": True, "exclusion_reason": "insufficient_capacity",
                               "reason": f"Available capacity {avail} families is below the requested {families_count}."})
            continue

        lat, lng = site["latitude"], site["longitude"]
        inside = any(point_in_zone(lat, lng, zone) for zone in red_zones)
        if inside:
            candidates.append({**site, "excluded": True, "exclusion_reason": "inside_critical_zone",
                               "reason": "Site lies inside an active critical hazard zone."})
            continue

        suitability = site.get("suitability_score", 0.0)
        cap_ratio = min(1.0, avail / max(1, families_count))
        road_score = site.get("road_score", 0.0)
        hospital_score = site.get("hospital_score", 0.0)
        site_score = round(
            (0.45 * suitability + 0.10 * cap_ratio * 100.0 + 0.25 * road_score + 0.20 * hospital_score), 1
        )

        candidates.append({
            **site,
            "excluded": False,
            "site_score": site_score,
            "reason": (
                f"Suitability {suitability:.0f}/100 with {avail} families of net capacity "
                f"(road {road_score:.0f}, healthcare {hospital_score:.0f})."
            ),
        })

    ranked = [c for c in candidates if not c.get("excluded")]
    ranked.sort(key=lambda c: c["site_score"], reverse=True)
    results = ranked[:limit] + [c for c in candidates if c.get("excluded")]
    return results


def _snap_or_none(graph: RoadGraph, lat: float, lng: float) -> Optional[str]:
    if lat is None or lng is None:
        return None
    return graph.snap(lat, lng, ROUTE_SNAP_M, fallback_m=ROUTE_SNAP_FALLBACK_M)


def _closed_segments_near(graph: RoadGraph, route_nodes: List[str], pad: float = 0.045) -> List[Dict[str, Any]]:
    coords = [graph.node_coords(n) for n in route_nodes]
    coords = [c for c in coords if c]
    if not coords:
        return []
    lat_min = min(c[0] for c in coords) - pad
    lat_max = max(c[0] for c in coords) + pad
    lng_min = min(c[1] for c in coords) - pad
    lng_max = max(c[1] for c in coords) + pad

    blocks: List[Dict[str, Any]] = []
    for edge in graph.edges:
        status = graph.edge_status.get(edge["id"], {}).get("status", "OPEN")
        if status != "CLOSED":
            continue
        a = graph.nodes[edge["from"]]
        b = graph.nodes[edge["to"]]
        if not (lat_min <= a["lat"] <= lat_max and lng_min <= a["lng"] <= lng_max) and \
           not (lat_min <= b["lat"] <= lat_max and lng_min <= b["lng"] <= lng_max):
            continue
        hazards = graph.edge_hazards.get(edge["id"], [])
        blocks.append({
            "segment_id": edge["id"],
            "name": edge["name"],
            "status": "closed",
            "hazard_type": hazards[0].get("hazard_type", "hazard") if hazards else "closure",
            "reason": hazards[0].get("zone_name", "Closed") if hazards else "No safe reason logged",
            "geometry": to_geojson_line([
                (float(a["lat"]), float(a["lng"])),
                (float(b["lat"]), float(b["lng"])),
            ]),
        })
    return blocks


def _route_status(route_detail: Optional[Dict[str, Any]]) -> str:
    if route_detail is None:
        return "NO_ROUTE"
    ledger = route_detail.get("edge_ledger", [])
    hazardous_corridor = any(
        entry["status"] in ("HIGH_RISK_EXIT", "RESTRICTED", "CLOSED")
        or any(h.get("risk_level") == "Critical" for h in entry["hazards"])
        for entry in ledger
    )
    if route_detail["safety_score"] >= 70 and not hazardous_corridor:
        return "SAFE"
    return "CAUTION"


def compute_route_for_site(
    data: Dict[str, Any],
    origin: Dict[str, Any],
    site: Dict[str, Any],
    families_count: int,
) -> Optional[Dict[str, Any]]:
    """Compute the safest (and shortest comparison) route for one candidate site."""
    graph = RoadGraph()
    origin_node = _snap_or_none(graph, origin["lat"], origin["lng"])
    dest_node = _snap_or_none(graph, site["latitude"], site["longitude"])

    if origin_node is None:
        return {"route_status": "ORIGIN_UNREACHABLE", "warning": "Origin cannot be reached from the pilot road network."}
    if dest_node is None:
        return {"route_status": "DEST_UNREACHABLE", "warning": "Destination site cannot be reached from the pilot road network."}

    graph.build_hazard_overlay(
        red_zones=data["red_zones"],
        habitations=data["habitations"],
        field_reports=data["field_reports"],
        road_conditions=seed_road_conditions(),
        origin_node=origin_node,
        dest_node=dest_node,
    )

    router = get_router()
    origin_coords = (origin["lat"], origin["lng"])
    dest_coords = (site["latitude"], site["longitude"])

    try:
        route = router.plan(graph, origin_node, dest_node, origin_coords, dest_coords)
        shortest = router.shortest(graph, origin_node, dest_node, origin_coords, dest_coords)
    except Exception:
        return {"route_status": "ROUTING_ENGINE_UNAVAILABLE", "warning": "Routing engine could not complete the request."}

    if route is None:
        return {
            "site_id": site["id"],
            "route_status": "NO_ROUTE",
            "warning": "No safe open-road route connects the affected area to this site.",
        }

    shortest_km = shortest["distance_km"] if shortest else route["distance_km"]
    delta_km = max(0.0, round(route["distance_km"] - shortest_km, 3))

    route_risky_ids = set(route["risky_edge_ids"])
    hazards_avoided: List[Dict[str, Any]] = []
    if shortest:
        for hazard in shortest.get("hazards_encountered", []):
            if hazard.get("edge_id") not in route_risky_ids:
                hazards_avoided.append(hazard)

    blocks = _closed_segments_near(graph, route["nodes"])
    status = _route_status(route)
    waypoint_names = [graph.nodes[n]["name"] for n in route.get("nodes", [])]

    return {
        "site_id": site["id"],
        "route_status": status,
        "distance_km": route["distance_km"],
        "travel_time_min": route["travel_time_min"],
        "safety_score": route["safety_score"],
        "risk_score": route["risk_score"],
        "route_geometry": route["geometry"],
        "hazards_encountered": route["hazards_encountered"],
        "hazards_avoided": hazards_avoided,
        "blocked_segments": blocks,
        "waypoints": waypoint_names,
        "edge_ledger": route["edge_ledger"],
        "shortest": {
            "distance_km": round(shortest_km, 3),
            "delta_km": delta_km,
        },
        "warning": None,
    }


def _route_explanation(route_result: Dict[str, Any], site: Dict[str, Any]) -> str:
    distance_km = route_result.get("distance_km", 0.0)
    travel_min = route_result.get("travel_time_min", 0.0)
    delta_km = (route_result.get("shortest") or {}).get("delta_km", 0.0)

    parts = [
        f"Safest connected route runs {distance_km} km (approx. {travel_min} min) reaching "
        f"{site['site_name']}."
    ]
    encountered = route_result.get("hazards_encountered", [])
    if encountered:
        details = "; ".join(
            f"{h.get('road', 'segment')} ({h.get('zone_name', h.get('hazard_type', 'risk'))})"
            for h in encountered[:4]
        )
        parts.append(f"Encounters {len(encountered)} risk segment(s): {details}.")
    if delta_km > 0.05:
        avoided = route_result.get("hazards_avoided", [])
        avoided_names = ", ".join({h.get("road", h.get("hazard_type", "")) for h in avoided[:3]}) if avoided else ""
        suffix = f" (bypassing {avoided_names})" if avoided_names else ""
        parts.append(f"Adds {delta_km} km over the most direct route{suffix} to avoid unsafe corridors.")
    blocks = route_result.get("blocked_segments", [])
    if blocks:
        names = ", ".join(b["name"] for b in blocks[:3])
        parts.append(f"{len(blocks)} closed road segment(s) near the corridor: {names}.")
    return " ".join(parts)


def build_data_sources() -> List[Dict[str, str]]:
    return [
        {"layer": "road_network", "status": "curated_demo", "detail": "Curated pilot corridor graph (NH-07 + key feeders); not live network data."},
        {"layer": "red_zones", "status": "demo", "detail": "Synthetic pilot hazard polygons."},
        {"layer": "hazard_events", "status": "demo", "detail": "Historical demo events linked to habitations."},
        {"layer": "field_reports", "status": "demo", "detail": "Synthetic verified field reports."},
        {"layer": "habitation_risk_scores", "status": "demo", "detail": "Synthetic per-habitation risk scores."},
    ]


def plan_evacuation(
    data: Dict[str, Any],
    origin_payload: Dict[str, Any],
    families_count: Optional[int],
    dest_site_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Full evacuation planning pipeline returning a RoutePlanResponse-like dict."""
    origin = resolve_origin(data, origin_payload)
    families = families_count if (families_count and families_count > 0) else (_origin_households(data, origin) or 100)

    now_iso = datetime.now(timezone.utc).isoformat()
    sites = select_candidate_sites(data, origin, families)
    eligible = [s for s in sites if not s.get("excluded")]

    if dest_site_id:
        chosen = next((s for s in eligible if s["id"] == dest_site_id), None)
        if not chosen:
            excluded = next((s for s in sites if s["id"] == dest_site_id and s.get("excluded")), None)
            reason = (excluded or {}).get("reason", "Site is not eligible for this population size.")
            return {
                "route_status": "NO_SAFE_SITE",
                "origin": _origin_summary(origin),
                "families_count": families,
                "all_candidates": sites,
                "warnings": [f"Requested destination excluded: {reason}"],
                "selected_site_reason": reason,
                "computed_at": now_iso,
                "data_sources": build_data_sources(),
                "is_synthetic_route": True,
                "payload_version": "v1",
            }

    computed: List[Dict[str, Any]] = []
    for site in eligible[:MAX_CANDIDATE_ROUTES]:
        route_result = compute_route_for_site(data, origin, site, families)
        if not route_result or route_result.get("route_status") in ("NO_ROUTE", "ROUTING_ENGINE_UNAVAILABLE", "ORIGIN_UNREACHABLE", "DEST_UNREACHABLE"):
            computed.append({"site": site, "route_result": route_result or {"route_status": "NO_ROUTE"}, "final_score": 0.0})
            continue
        final_score = round(0.6 * site.get("site_score", 0.0) + 0.4 * route_result.get("safety_score", 0.0), 1)
        computed.append({"site": site, "route_result": route_result, "final_score": final_score})

    routed = [c for c in computed if c["route_result"].get("distance_km") is not None]
    routed.sort(key=lambda c: c["final_score"], reverse=True)

    if not routed:
        warnings: List[str] = []
        for c in computed:
            status = c["route_result"].get("route_status")
            warn = c["route_result"].get("warning")
            if warn:
                warnings.append(warn)
            elif status:
                warnings.append(f"No open road route to {c['site']['site_name']}.")
        return {
            "route_status": "NO_ROUTE",
            "origin": _origin_summary(origin),
            "families_count": families,
            "all_candidates": [c["site"] for c in computed if not c["site"].get("excluded")],
            "warnings": warnings or ["No safe route could be computed to any eligible site."],
            "selected_site_reason": "No site is reachable by a safe, open road route.",
            "computed_at": now_iso,
            "data_sources": build_data_sources(),
            "is_synthetic_route": True,
            "payload_version": "v1",
        }

    best = routed[0]
    site = best["site"]
    route_result = best["route_result"]

    response = {
        "route_status": route_result["route_status"],
        "origin": _origin_summary(origin),
        "destination": {
            "site_id": site["id"],
            "site_name": site["site_name"],
            "latitude": site["latitude"],
            "longitude": site["longitude"],
            "available_capacity_families": site["available_capacity_families"],
            "final_capacity_families": site["final_capacity_families"],
            "suitability_score": site["suitability_score"],
        },
        "families_count": families,
        "selected_site_reason": (
            f"{site['site_name']} ranks top with site score {site['site_score']}/100 and a route "
            f"safety of {route_result['safety_score']}/100. {site['reason']}"
        ),
        "route_geometry": route_result["route_geometry"],
        "distance_km": route_result["distance_km"],
        "travel_time_min": route_result["travel_time_min"],
        "safety_score": route_result["safety_score"],
        "risk_score": route_result["risk_score"],
        "hazards_encountered": route_result["hazards_encountered"],
        "hazards_avoided": route_result["hazards_avoided"],
        "blocked_segments": route_result["blocked_segments"],
        "waypoints": route_result["waypoints"],
        "route_reason": _route_explanation(route_result, site),
        "shortest": route_result["shortest"],
        "candidates": [
            {
                "site_id": c["site"]["id"],
                "site_name": c["site"]["site_name"],
                "site_score": c["site"].get("site_score"),
                "route_status": c["route_result"].get("route_status"),
                "distance_km": c["route_result"].get("distance_km"),
                "safety_score": c["route_result"].get("safety_score"),
                "final_score": c["final_score"],
                "reason": c["route_result"].get("warning") or c["site"].get("reason"),
            }
            for c in routed
        ] + [
            {
                "site_id": c["site"]["id"],
                "site_name": c["site"]["site_name"],
                "route_status": c["route_result"].get("route_status"),
                **({"reason": c["route_result"].get("warning")} if c["route_result"].get("warning") else {}),
                **({"exclusion_reason": c["site"].get("exclusion_reason"), "reason": c["site"].get("reason")} if c["site"].get("excluded") else {}),
            }
            for c in computed if c not in routed
        ],
        "warnings": ([w for w in [route_result.get("warning")] if w] + [
            f"Requested {families} families; route network is validated only on the curated pilot graph."
        ]),
        "computed_at": now_iso,
        "verified_at": now_iso,
        "data_sources": build_data_sources(),
        "is_synthetic_route": True,
        "payload_version": "v1",
    }

    # Persist for audit/retrieval
    route_record = {
        "id": f"route-{uuid.uuid4().hex[:10]}",
        "user_id": None,
        "user_name": None,
        "origin": response["origin"],
        "origin_scope": origin["scope"],
        "dest_site_id": site["id"],
        "dest_site_name": site["site_name"],
        "route_status": response["route_status"],
        "families_count": families,
        "route_geometry": route_result["route_geometry"],
        "distance_km": route_result["distance_km"],
        "travel_time_min": route_result["travel_time_min"],
        "safety_score": route_result["safety_score"],
        "risk_score": route_result["risk_score"],
        "hazards_encountered": route_result["hazards_encountered"],
        "hazards_avoided": route_result["hazards_avoided"],
        "blocked_segments": route_result["blocked_segments"],
        "selected_site_reason": response["selected_site_reason"],
        "route_reason": response["route_reason"],
        "shortest_distance_km": route_result["shortest"]["distance_km"],
        "shortest_delta_km": route_result["shortest"]["delta_km"],
        "payload_version": "v1",
        "status": "planned",
        "created_at": now_iso,
        "confirmed_at": None,
    }
    data.setdefault("route_calculations", []).insert(0, route_record)
    response["route_id"] = route_record["id"]
    route_record["plan_payload"] = dict(response)
    return response


def route_response_from_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Render a stored route record back into the full RoutePlanResponse contract."""
    payload = record.get("plan_payload")
    if not payload:
        origin = record.get("origin", {})
        payload = {
            "route_id": record["id"],
            "route_status": record.get("route_status", "NO_ROUTE"),
            "origin": origin,
            "destination": {
                "site_id": record.get("dest_site_id"),
                "site_name": record.get("dest_site_name", "Relocation site"),
            } if record.get("dest_site_id") else None,
            "families_count": record.get("families_count", 0),
            "route_geometry": record.get("route_geometry"),
            "distance_km": record.get("distance_km"),
            "travel_time_min": record.get("travel_time_min"),
            "safety_score": record.get("safety_score"),
            "risk_score": record.get("risk_score"),
            "hazards_encountered": record.get("hazards_encountered", []),
            "hazards_avoided": record.get("hazards_avoided", []),
            "blocked_segments": record.get("blocked_segments", []),
            "selected_site_reason": record.get("selected_site_reason", ""),
            "route_reason": record.get("route_reason"),
            "is_synthetic_route": True,
            "payload_version": record.get("payload_version", "v1"),
        }
    out = dict(payload)
    out["status"] = record.get("status", "planned")
    out["confirmed_at"] = record.get("confirmed_at")
    out["decision"] = record.get("decision")
    out["notes"] = record.get("notes")
    return out