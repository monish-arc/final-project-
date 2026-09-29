"""
Evacuation route planning tests: routing engine, planner logic and API contract.

The pilot router is fully offline over the curated road graph; these tests assert
risk-aware behaviour (closed corridors, hazard-weighted cost, safe-site ranking)
and the RBAC-guarded /api/evacuation/* surface.
"""

from fastapi.testclient import TestClient

from app.main import app
from app.road_network import RoadGraph
from app.routing import find_path

client = TestClient(app)


def _admin_headers() -> dict:
    res = client.post("/api/auth/login", json={"username_or_email": "admin", "password": "admin123"})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _officer_headers() -> dict:
    res = client.post("/api/auth/login", json={
        "username_or_email": "officer",
        "password": "officer123",
        "state_id": "uk",
        "district_id": "chamoli",
        "sub_district_id": "joshimath",
        "area_id": "joshimath-central",
    })
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _field_headers() -> dict:
    res = client.post("/api/auth/login", json={
        "username_or_email": "field",
        "password": "field123",
        "state_id": "uk",
        "district_id": "chamoli",
        "sub_district_id": "joshimath",
        "area_id": "joshimath-central",
    })
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_evacuation_endpoints_require_auth():
    unauthenticated_calls = [
        ("GET", "/api/evacuation/candidates?origin_type=habitation&origin_id=hab-joshimath&families_count=10", None),
        ("POST", "/api/evacuation/plan", {"origin": {"type": "habitation", "id": "hab-joshimath"}}),
        ("GET", "/api/evacuation/routes/route-x", None),
        ("POST", "/api/evacuation/routes/route-x/confirm", {"decision": "approved"}),
        ("GET", "/api/evacuation/road-conditions", None),
    ]
    for method, url, body in unauthenticated_calls:
        kwargs = {"json": body} if body is not None else {}
        response = getattr(client, method.lower())(url, **kwargs)
        assert response.status_code == 401, f"{method} {url} should require auth"


def test_plan_joshimath_to_gauchar():
    response = client.post("/api/evacuation/plan", headers=_officer_headers(), json={
        "origin": {"type": "habitation", "id": "hab-joshimath"},
        "families_count": 100,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["route_status"] == "CAUTION"
    assert data["destination"]["site_name"] == "Gauchar Plateau Safe Enclave"
    assert data["distance_km"] > 40
    assert data["safety_score"] >= 40
    assert data["risk_score"] > 0
    assert len(data["hazards_encountered"]) > 0
    assert data["route_geometry"]["type"] == "LineString"
    assert len(data["route_geometry"]["coordinates"]) >= 2
    assert data["is_synthetic_route"] is True
    assert data["payload_version"] == "v1"
    # Every candidate carries a route status and score.
    assert all(c["route_status"] and c["final_score"] for c in data["candidates"])


def test_route_never_uses_closed_corridor_raini():
    """Raini sits inside the critical Rishiganga corridor whose egress is closed."""
    data = client.post("/api/evacuation/plan", headers=_officer_headers(), json={
        "origin": {"type": "habitation", "id": "hab-raini"},
        "families_count": 50,
    }).json()
    assert data["route_status"] == "NO_ROUTE"
    assert data.get("destination") is None
    assert any("warnings" in data for _ in [0])


def test_map_click_origin_requires_coordinates():
    response = client.post("/api/evacuation/plan", headers=_officer_headers(), json={
        "origin": {"type": "map_click", "id": "click", "label": "no coords"},
        "families_count": 20,
    })
    assert response.status_code in (400, 422)


def test_map_click_snaps_to_corridor():
    data = client.post("/api/evacuation/plan", headers=_officer_headers(), json={
        "origin": {"type": "map_click", "lat": 30.56, "lng": 79.565, "label": "joshimath"},
        "families_count": 20,
    }).json()
    assert data["route_status"] in ("SAFE", "CAUTION")
    assert data["destination"] is not None


def test_destination_capacity_check():
    """Requesting more families than a site holds must not silently proceed."""
    data = client.post("/api/evacuation/plan", headers=_officer_headers(), json={
        "origin": {"type": "habitation", "id": "hab-joshimath"},
        "dest_site_id": "site-gauchar-01",
        "families_count": 50000,
    }).json()
    assert data["route_status"] == "NO_SAFE_SITE"


def test_unknown_origin_rejected():
    response = client.post("/api/evacuation/plan", headers=_officer_headers(), json={
        "origin": {"type": "habitation", "id": "hab-nonexistent"},
    })
    assert response.status_code == 400


def test_geographic_scope_enforcement():
    """field officer scope is joshimath-central only; Tharali is out of scope."""
    data = client.post("/api/evacuation/plan", headers=_field_headers(), json={
        "origin": {"type": "habitation", "id": "hab-tharali"},
    })
    assert data.status_code == 403


def test_confirm_route_flow():
    headers = _officer_headers()
    planned = client.post("/api/evacuation/plan", headers=headers, json={
        "origin": {"type": "habitation", "id": "hab-joshimath"},
        "families_count": 50,
    }).json()
    route_id = planned["route_id"]

    fetched = client.get(f"/api/evacuation/routes/{route_id}", headers=headers)
    assert fetched.status_code == 200
    fetched_data = fetched.json()
    assert fetched_data["route_status"] == "CAUTION"
    assert fetched_data["status"] in ("planned", "pending", "confirmed")

    confirmed = client.post(f"/api/evacuation/routes/{route_id}/confirm", headers=headers, json={
        "decision": "approved",
        "notes": "Deploy teams to NH-07 checkpoints",
    })
    assert confirmed.status_code == 200
    confirmed_data = confirmed.json()
    assert confirmed_data["status"] == "confirmed"
    assert confirmed_data["confirmed_at"] is not None


def test_confirm_missing_route_404():
    response = client.post("/api/evacuation/routes/nope/confirm",
                           headers=_officer_headers(), json={"decision": "approved"})
    assert response.status_code == 404


def test_road_conditions_endpoint():
    response = client.get("/api/evacuation/road-conditions", headers=_officer_headers())
    assert response.status_code == 200
    data = response.json()
    assert len(data["segments"]) >= 10
    assert data["is_synthetic_demo_data"] is True
    first = data["segments"][0]
    assert first["data_class"] == "curated_demo"
    assert first["is_synthetic"] is True
    assert first["status"] in ("OPEN", "RESTRICTED", "CLOSED")
    assert len(data["data_sources"]) > 0


def test_closed_edge_in_graph():
    """Without overlay all edges are open; overlay closes only critical-intersecting ones."""
    graph = RoadGraph()
    # Snap within fallback band (pilot graph nodes are sparse); strict 250 m may miss.
    fallback = 6000.0
    origin_node = graph.snap(30.4851, 79.6974, 250, fallback_m=fallback)
    dest_node = graph.snap(30.29, 79.155, 250, fallback_m=fallback)
    assert origin_node is not None
    assert dest_node is not None
    # Raini -> Gauchar must be routed through the graph (synthetic demo rejects straight lines).
    plain_path = find_path(graph, origin_node, dest_node, risk_aware=True)
    assert plain_path is not None
    # Overlay the critical Rishiganga + Joshimath polygons: egress becomes closed.
    from app.main import DATA
    graph.build_hazard_overlay(
        red_zones=DATA["red_zones"],
        habitations=DATA["habitations"],
        field_reports=DATA["field_reports"],
        road_conditions=[],
        origin_node=origin_node,
        dest_node=dest_node,
    )
    # The corridor is only reachable as an exit from the origin; through-traffic is closed.
    assert graph.edge_status["e-tapovan-raini"]["status"] == "HIGH_RISK_EXIT"
    assert graph.is_open("e-tapovan-raini") is True
    assert graph.edge_status["e-joshimath-tapovan"]["status"] == "CLOSED"
    assert graph.is_open("e-joshimath-tapovan") is False
    overlay_path = find_path(graph, origin_node, dest_node, risk_aware=True)
    assert overlay_path is None