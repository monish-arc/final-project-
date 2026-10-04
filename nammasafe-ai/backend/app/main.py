"""
NammaSafe AI - FastAPI Backend Server
Decision-Support Platform for Chamoli District, Uttarakhand
"""

from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid
from sqlalchemy.orm import Session

from app.config import PILOT_DISTRICT, PILOT_STATE, HISTORICAL_MAX_RAINFALL_MM
from app.auth import create_access_token, require_roles, require_permissions, get_current_user
from app.access_control import can_manage_role, scope_contains
from app.schemas import (
    LoginRequest,
    TokenResponse,
    HabitationResponse,
    RelocationSiteResponse,
    RelocationRecommendationResponse,
    FieldReportResponse,
    FieldReportCreate,
    SimulationRequest,
    SimulationResponse,
    PriorityCalculateRequest,
    AdminHazardUploadRequest,
    RiskAlertCreate,
    AccommodationUpdate,
    AssignmentCreate,
    EvacuationPlanRequest,
    RoutePlanResponse,
    RouteConfirmRequest,
    FloodForecastResponse,
    DataStatusResponse,
    HistoricalAvailabilityResponse,
    HistoricalBaselineResponse,
    HistoricalDistrictSummaryResponse,
    HistoricalCompareResponse,
)
from app.flood_forecast import get_flood_forecasts, get_data_status
from app.historical_providers import provider_statuses as historical_provider_statuses
from app.risk_engine import (
    calculate_hazard_score,
    calculate_vulnerability_score,
    calculate_relocation_priority,
    calculate_site_suitability,
    calculate_carrying_capacity,
    simulate_safeshift,
)
from app.seed_data import get_processed_seed_data
from app.database import engine, get_db
from app.models import Base
from app.geo import point_in_zone, to_geojson_line
from app.road_network import load_road_network, seed_road_conditions, RoadGraph
from app.route_planner import (
    build_scope_for_area,
    enforce_origin_scope,
    plan_evacuation,
    resolve_origin,
    route_response_from_record,
    select_candidate_sites,
    PlannerInputError,
)
from app.historical_data import availability, all_district_summaries, district_baseline, district_summary
from app.historical_baseline import compare_observation
from app.kerala_districts import district_code, district_name

app = FastAPI(
    title="NammaSafe AI API",
    description="Proactive Red-Zone and Relocation Planning Platform for Disaster-Prone Regions (Chamoli, Uttarakhand Pilot).",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)
@app.get("/health")
async def health():
    return {"status": "ok"}
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store initialized from seed data
DATA = get_processed_seed_data()
DATA["road_network"] = load_road_network()
DATA["road_conditions"] = seed_road_conditions()
DATA.setdefault("route_calculations", [])

# SAFE_MOVE_AI live-intelligence layer (weather, terrain, flood, rainfall,
# nearby places, risk assessment, risk zones, safe locations, safer routes).
from app.integration_routes import build_integration_router

app.include_router(build_integration_router(lambda: DATA))


def _is_pilot_region(state: Optional[str], district: Optional[str]) -> bool:
    """The Chamoli pilot is the only region carrying curated seed data."""
    s = (state or "").lower()
    d = (district or "").lower()
    return (not state or "uttarakhand" in s) and (not district or "chamoli" in d)


def _item_region(item: Dict[str, Any]) -> Dict[str, str]:
    """Items without explicit region fields are the curated Chamoli pilot set."""
    return {
        "state": item.get("state") or PILOT_STATE,
        "district": item.get("district") or PILOT_DISTRICT,
    }


def _region_match(item: Dict[str, Any], state: Optional[str], district: Optional[str]) -> bool:
    if state and _item_region(item)["state"].lower() != state.lower():
        return False
    if district and _item_region(item)["district"].lower() != district.lower():
        return False
    return True


@app.on_event("startup")
def initialise_local_database() -> None:
    """Create the local SQLite schema when the stack runs without Docker."""
    Base.metadata.create_all(bind=engine)


def get_area_scope(area_id: str) -> Dict[str, str]:
    area = next((item for item in DATA["administrative_areas"]["areas"] if item["id"] == area_id), None)
    if not area:
        raise HTTPException(status_code=404, detail="Administrative area not found")
    sub_district = next(
        (item for item in DATA["administrative_areas"]["sub_districts"] if item["id"] == area["sub_district_id"]),
        None,
    )
    if not sub_district:
        raise HTTPException(status_code=404, detail="Sub-district not found")
    district = next(
        (item for item in DATA["administrative_areas"]["districts"] if item["id"] == sub_district["district_id"]),
        None,
    )
    if not district:
        raise HTTPException(status_code=404, detail="District not found")
    return {
        "state_id": district["state_id"],
        "district_id": district["id"],
        "sub_district_id": sub_district["id"],
        "area_id": area["id"],
    }


def require_scope(user: Dict[str, Any], area_id: str) -> Dict[str, str]:
    requested_scope = get_area_scope(area_id)
    if not scope_contains(user.get("assignment", {}), requested_scope):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Area is outside your assigned jurisdiction")
    return requested_scope


def record_audit_event(action: str, user: Dict[str, Any], detail: Dict[str, Any]) -> None:
    DATA["audit_events"].insert(0, {
        "id": f"audit-{uuid.uuid4().hex[:10]}",
        "action": action,
        "actor_id": user.get("sub", user.get("id")),
        "actor_name": user.get("full_name"),
        "detail": detail,
        "recorded_at": datetime.utcnow().isoformat(),
    })

@app.get("/health")
def health():
    """Public liveness probe (used by container healthchecks and uptime tools)."""
    return {"status": "ok", "api_docs": "/docs"}


@app.get("/")
def root():
    return {
        "platform": "NammaSafe AI",
        "tagline": "Proactive Red-Zone and Relocation Planning Platform",
        "pilot": f"{PILOT_DISTRICT}, {PILOT_STATE}",
        "status": "Operational",
        "api_docs": "/docs",
    }

# ==================== AUTHENTICATION ====================
@app.post("/api/auth/login", response_model=TokenResponse)
def login(creds: LoginRequest):
    username_or_email = creds.username_or_email.strip().lower()
    
    user = None
    for u in DATA["users"]:
        if u["username"].lower() == username_or_email or u["email"].lower() == username_or_email:
            user = u
            break
            
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials. Please use demo account credentials.",
        )
        
    # Check the demonstration password for this identity.
    expected_pass = user["hashed_password"].split(":")[-1]
    if creds.password != expected_pass:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password for this user.",
        )
        
    selected_scope = {
        "state_id": creds.state_id,
        "district_id": creds.district_id,
        "sub_district_id": creds.sub_district_id,
        "area_id": creds.area_id,
    }
    if user["role"] != "admin":
        if not all(selected_scope.values()):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="State, district, sub-district and area are required before login")
        if not scope_contains(user["assignment"], selected_scope):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Selected area is outside this user's assignment")
    else:
        selected_scope = user["assignment"]

    token = create_access_token(
        data={
            "sub": user["id"],
            "username": user["username"],
            "email": user["email"],
            "role": user["role"],
            "full_name": user["full_name"],
            "assignment": user["assignment"],
            "selected_scope": selected_scope,
        }
    )
    DATA["user_sessions"].insert(0, {
        "id": f"session-{uuid.uuid4().hex[:10]}",
        "user_id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "selected_scope": selected_scope,
        "logged_in_at": datetime.utcnow().isoformat(),
    })
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "role": user["role"],
            "full_name": user["full_name"],
            "designation": user.get("designation", ""),
            "department": user.get("department", ""),
            "assignment": user["assignment"],
            "selected_scope": selected_scope,
        },
    }


# ==================== GEOGRAPHY AND SCOPED OPERATIONS ====================
@app.get("/api/geography/states")
def list_states():
    return DATA["administrative_areas"]["states"]


@app.get("/api/geography/districts")
def list_districts(state_id: str = Query(...)):
    return [item for item in DATA["administrative_areas"]["districts"] if item["state_id"] == state_id]


@app.get("/api/geography/sub-districts")
def list_sub_districts(district_id: str = Query(...)):
    return [item for item in DATA["administrative_areas"]["sub_districts"] if item["district_id"] == district_id]


@app.get("/api/geography/areas")
def list_areas(sub_district_id: str = Query(...)):
    return [item for item in DATA["administrative_areas"]["areas"] if item["sub_district_id"] == sub_district_id]


@app.get("/api/risk-alerts")
def list_risk_alerts(area_id: Optional[str] = None):
    alerts = DATA["risk_alerts"]
    if area_id:
        alerts = [alert for alert in alerts if alert["area_id"] == area_id]
    return [alert for alert in alerts if alert["status"] == "published"]


@app.post("/api/risk-alerts")
def create_risk_alert(
    payload: RiskAlertCreate,
    user: dict = Depends(require_permissions("alert.raise")),
):
    require_scope(user, payload.area_id)
    alert = {
        "id": f"alert-{uuid.uuid4().hex[:8]}",
        **payload.model_dump(),
        "status": "pending_review",
        "reported_by": user["sub"],
        "reported_by_name": user["full_name"],
        "reported_at": datetime.utcnow().isoformat(),
    }
    DATA["risk_alerts"].insert(0, alert)
    record_audit_event("risk_alert.created", user, {"alert_id": alert["id"], "area_id": payload.area_id})
    return alert


@app.post("/api/risk-alerts/{alert_id}/publish")
def publish_risk_alert(
    alert_id: str,
    user: dict = Depends(require_permissions("accommodation.manage")),
):
    alert = next((item for item in DATA["risk_alerts"] if item["id"] == alert_id), None)
    if not alert:
        raise HTTPException(status_code=404, detail="Risk alert not found")
    require_scope(user, alert["area_id"])
    alert["status"] = "published"
    alert["published_by"] = user["sub"]
    alert["published_at"] = datetime.utcnow().isoformat()
    record_audit_event("risk_alert.published", user, {"alert_id": alert_id})
    return alert


@app.post("/api/accommodations")
def create_accommodation(
    payload: AccommodationUpdate,
    user: dict = Depends(require_permissions("accommodation.manage")),
):
    require_scope(user, payload.area_id)
    if payload.current_occupancy_families > payload.estimated_capacity:
        raise HTTPException(status_code=422, detail="Occupancy cannot exceed total capacity")
    accommodation = {
        "id": f"site-{uuid.uuid4().hex[:8]}",
        "site_name": payload.site_name,
        "district": PILOT_DISTRICT,
        "area_id": payload.area_id,
        "land_area_acres": payload.land_area_acres,
        "estimated_capacity": payload.estimated_capacity,
        "current_occupancy_families": payload.current_occupancy_families,
        "available_capacity_families": payload.estimated_capacity - payload.current_occupancy_families,
        "water_score": 80.0,
        "road_score": 80.0,
        "school_score": 80.0,
        "hospital_score": 80.0,
        "low_hazard_score": 80.0,
        "flat_land_score": 80.0,
        "suitability_score": 80.0,
        "land_capacity_families": payload.estimated_capacity,
        "water_capacity_families": payload.estimated_capacity,
        "school_capacity_families": payload.estimated_capacity,
        "health_capacity_families": payload.estimated_capacity,
        "road_capacity_families": payload.estimated_capacity,
        "final_capacity_families": payload.estimated_capacity,
        "latitude": payload.latitude,
        "longitude": payload.longitude,
        "contact_name": None,
        "contact_phone": None,
        "verified": False,
        "last_verified": None,
        "status": "published",
        "updated_at": datetime.utcnow().isoformat(),
    }
    DATA["relocation_sites"].append(accommodation)
    record_audit_event("accommodation.created", user, {"accommodation_id": accommodation["id"], "area_id": payload.area_id})
    return accommodation


@app.get("/api/assignments")
def list_assignments(user: dict = Depends(require_permissions("assignment.read"))):
    return [
        {"user_id": item["id"], "username": item["username"], "role": item["role"], "assignment": item["assignment"]}
        for item in DATA["users"]
        if scope_contains(user["assignment"], item["assignment"])
    ]


@app.post("/api/assignments")
def assign_user(payload: AssignmentCreate, user: dict = Depends(require_permissions("assignment.manage"))):
    target = next((item for item in DATA["users"] if item["id"] == payload.user_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    requested_scope = payload.model_dump(exclude={"user_id", "role"})
    if not can_manage_role(user["role"], payload.role) or not scope_contains(user["assignment"], requested_scope):
        raise HTTPException(status_code=403, detail="You cannot manage this role or jurisdiction")
    target["role"] = payload.role
    target["assignment"] = requested_scope
    record_audit_event("assignment.updated", user, {"target_user_id": target["id"], "role": payload.role, "scope": requested_scope})
    return {"user_id": target["id"], "role": target["role"], "assignment": target["assignment"]}


@app.get("/api/analytics/hazards")
def hazard_analytics(
    state: Optional[str] = None,
    district: Optional[str] = None,
    user: dict = Depends(require_permissions("analytics.read")),
):
    hab_by_id = {h["id"]: h for h in DATA["habitations"]}
    events = [
        e for e in DATA["hazard_events"]
        if not (state or district)
        or _region_match(hab_by_id.get(e.get("habitation_id"), {}), state, district)
    ]
    by_type: Dict[str, int] = {}
    by_year: Dict[str, int] = {}
    for event in events:
        by_type[event["hazard_type"]] = by_type.get(event["hazard_type"], 0) + 1
        year = event["event_date"][:4]
        by_year[year] = by_year.get(year, 0) + 1
    return {"events_by_type": by_type, "events_by_year": by_year, "events": events}


@app.get("/api/admin/sessions")
def list_sessions(user: dict = Depends(require_permissions("session-log.read"))):
    return DATA["user_sessions"]


@app.get("/api/admin/system-health")
def system_health(user: dict = Depends(require_permissions("system-health.read"))):
    return {"status": "operational", "data_mode": "synthetic_demo", "checked_at": datetime.utcnow().isoformat()}

# ==================== DASHBOARD SUMMARY ====================
@app.get("/api/dashboard-summary")
def get_dashboard_summary(
    state: Optional[str] = None,
    district: Optional[str] = None,
):
    habs = [h for h in DATA["habitations"] if _region_match(h, state, district)]
    sites = [s for s in DATA["relocation_sites"] if _region_match(s, state, district)]
    hab_by_id = {h["id"]: h for h in DATA["habitations"]}
    reports = [
        r for r in DATA["field_reports"]
        if not (state or district)
        or _region_match(hab_by_id.get(r.get("habitation_id"), {}), state, district)
    ]
    pilot = _is_pilot_region(state, district)
    has_curated_data = bool(habs)

    total_monitored = len(habs)
    
    # High risk population: population in Immediate or Short-Term relocation
    high_risk_population = sum(
        h["population"] for h in habs 
        if h["priority_level"] in ["Immediate Relocation", "Short-Term Relocation"]
    )

    # Population exposure (Phase 6): the exposed population is the set of
    # habitations under Immediate/Short-Term relocation — disaggregated by
    # households and vulnerable cohorts (age-based estimates).
    exposed_habs = [
        h for h in habs
        if h["priority_level"] in ["Immediate Relocation", "Short-Term Relocation"]
    ]
    population_exposed = sum((h.get("population") or 0) for h in exposed_habs)
    households_exposed = sum((h.get("households") or 0) for h in exposed_habs)
    children_est = sum((h.get("children_count") or 0) for h in exposed_habs)
    elderly_est = sum((h.get("elderly_count") or 0) for h in exposed_habs)
    
    immediate_relocation_count = sum(
        1 for h in habs if h["priority_level"] == "Immediate Relocation"
    )
    
    available_safe_capacity = sum(
        s.get("available_capacity_families", s["final_capacity_families"]) for s in sites
    )
    
    # Hazard distribution (seeded events only exist for the pilot region)
    hazard_counts: Dict[str, Dict[str, Any]] = {}
    for h in DATA["hazard_events"]:
        if state or district:
            hab = next((x for x in DATA["habitations"] if x["id"] == h.get("habitation_id")), None)
            if hab and not _region_match(hab, state, district):
                continue
        ht = h["hazard_type"]
        if ht not in hazard_counts:
            hazard_counts[ht] = {"hazard_type": ht, "count": 0, "affected_population": 0}
        hazard_counts[ht]["count"] += 1
        hazard_counts[ht]["affected_population"] += h["affected_people"]
        
    # Relocation priority distribution
    priority_counts: Dict[str, Dict[str, Any]] = {
        "Immediate Relocation": {"level": "Immediate Relocation", "count": 0, "population": 0},
        "Short-Term Relocation": {"level": "Short-Term Relocation", "count": 0, "population": 0},
        "Medium-Term Relocation": {"level": "Medium-Term Relocation", "count": 0, "population": 0},
        "Monitor Only": {"level": "Monitor Only", "count": 0, "population": 0},
    }
    for h in habs:
        lvl = h["priority_level"]
        if lvl in priority_counts:
            priority_counts[lvl]["count"] += 1
            priority_counts[lvl]["population"] += h["population"]
            
    # Top 5 critical villages
    top_5 = sorted(habs, key=lambda x: x["priority_score"], reverse=True)[:5]
    
    # Recent field reports
    recent_reports = sorted(reports, key=lambda x: x["reported_at"], reverse=True)[:5]

    summary = {
        "total_habitations_monitored": total_monitored,
        "high_risk_population": high_risk_population,
        "population_exposed": population_exposed,
        "households_exposed": households_exposed,
        "children_est": children_est,
        "elderly_est": elderly_est,
        "immediate_relocation_villages_count": immediate_relocation_count,
        "available_safe_site_capacity": available_safe_capacity,
        "total_safe_sites": len(sites),
        "verified_field_reports_count": sum(1 for r in reports if r["verified"]),
        "pending_field_reports_count": sum(1 for r in reports if not r["verified"]),
        "hazard_distribution": list(hazard_counts.values()),
        "relocation_priority_distribution": list(priority_counts.values()),
        "recent_field_reports": recent_reports,
        "top_five_critical_villages": top_5,
        "pilot_district": PILOT_DISTRICT,
        "pilot_state": PILOT_STATE,
        "region": {
            "state": state,
            "district": district,
            "is_pilot": pilot,
            "has_curated_data": has_curated_data,
        },
        "data_status": "UNAVAILABLE" if not has_curated_data else "CURATED",
        "is_synthetic_demo_data": False,
        "data_provenance": "Curated records are served only for the district actually selected; no region receives another location's data.",
    }
    if not has_curated_data:
        summary["message"] = "Data unavailable for this location"
    return summary

# ==================== MAP LAYERS ====================
@app.get("/api/map-layers")
def get_map_layers(
    state: Optional[str] = None,
    district: Optional[str] = None,
):
    red_zones = [z for z in DATA["red_zones"] if _region_match(z, state, district)]
    habitations = [h for h in DATA["habitations"] if _region_match(h, state, district)]
    relocation_sites = [s for s in DATA["relocation_sites"] if _region_match(s, state, district)]
    infrastructure = [i for i in DATA["infrastructure"] if _region_match(i, state, district)]
    pilot = _is_pilot_region(state, district)

    return {
        "red_zones": red_zones,
        "habitations": habitations,
        "relocation_sites": relocation_sites,
        "infrastructure": infrastructure,
        "pilot_center": {"lat": 30.4000, "lng": 79.3300, "zoom": 10} if pilot
        else None,
        "region": {"state": state, "district": district, "is_pilot": pilot},
        "layers_status": {
            "red_zones": "SIMULATED" if red_zones else "UNAVAILABLE",
            "habitations": "SIMULATED" if habitations else "UNAVAILABLE",
            "relocation_sites": "SIMULATED" if relocation_sites else "UNAVAILABLE",
            "infrastructure": "SIMULATED" if infrastructure else "UNAVAILABLE",
        },
        "is_synthetic_demo_data": pilot,
    }

# ==================== HABITATIONS ====================
@app.get("/api/habitations")
def list_habitations(
    priority_level: Optional[str] = None,
    search: Optional[str] = None,
    state: Optional[str] = None,
    district: Optional[str] = None,
):
    habs = [h for h in DATA["habitations"] if _region_match(h, state, district)]
    if priority_level:
        habs = [h for h in habs if h["priority_level"].lower() == priority_level.lower()]
    if search:
        s = search.lower()
        habs = [h for h in habs if s in h["village_name"].lower() or s in h["village_code"].lower()]
    return habs

@app.get("/api/habitations/{id}")
def get_habitation(id: str):
    for h in DATA["habitations"]:
        if h["id"] == id or h["village_code"] == id:
            return h
    raise HTTPException(status_code=404, detail="Habitation not found")

@app.get("/api/habitations/{id}/risk-analysis")
def get_habitation_risk_analysis(id: str):
    hab = None
    for h in DATA["habitations"]:
        if h["id"] == id or h["village_code"] == id:
            hab = h
            break
    if not hab:
        raise HTTPException(status_code=404, detail="Habitation not found")
        
    events = [e for e in DATA["hazard_events"] if e["habitation_id"] == hab["id"]]
    recs = [r for r in DATA["recommendations"] if r["habitation_id"] == hab["id"]]
    reports = [fr for fr in DATA["field_reports"] if fr["habitation_id"] == hab["id"]]
    
    return {
        "habitation": hab,
        "historical_events": events,
        "recommendations": recs,
        "field_reports": reports,
        "risk_breakdown": {
            "hazard_components": {
                "landslide_risk_weighted": round(0.40 * hab["landslide_risk"], 2),
                "flood_risk_weighted": round(0.30 * hab["flood_risk"], 2),
                "rainfall_risk_weighted": round(0.20 * hab["extreme_rainfall_risk"], 2),
                "past_disaster_weighted": round(0.10 * hab["past_disaster_frequency"], 2),
                "total_hazard_score": hab["hazard_score"],
            },
            "vulnerability_components": {
                "vulnerability_score": hab["vulnerability_score"],
                "hospital_distance_km": hab["hospital_distance_km"],
                "road_access_score": hab["road_access_score"],
                "children_ratio_percent": round((hab["children_count"] / hab["population"]) * 100, 1),
                "elderly_ratio_percent": round((hab["elderly_count"] / hab["population"]) * 100, 1),
            },
            "priority_calculation": {
                "hazard_contribution_50pct": round(0.50 * hab["hazard_score"], 2),
                "vulnerability_contribution_30pct": round(0.30 * hab["vulnerability_score"], 2),
                "disaster_history_contribution_20pct": round(0.20 * min(100.0, hab["disaster_history_count"] * 16.0), 2),
                "final_priority_score": hab["priority_score"],
                "priority_level": hab["priority_level"],
            },
        },
    }

# ==================== RELOCATION SITES ====================
@app.get("/api/relocation-sites")
def list_relocation_sites(
    state: Optional[str] = None,
    district: Optional[str] = None,
):
    return [s for s in DATA["relocation_sites"] if _region_match(s, state, district)]

@app.get("/api/relocation-sites/{id}")
def get_relocation_site(id: str):
    for s in DATA["relocation_sites"]:
        if s["id"] == id:
            return s
    raise HTTPException(status_code=404, detail="Relocation site not found")

# ==================== RECOMMENDATIONS ====================
@app.get("/api/relocation-recommendations")
def list_recommendations(status_filter: Optional[str] = None):
    recs = DATA["recommendations"]
    if status_filter:
        recs = [r for r in recs if r["status"].lower() == status_filter.lower()]
    return recs

# ==================== FIELD REPORTS ====================
@app.get("/api/field-reports")
def list_field_reports():
    return DATA["field_reports"]

@app.post("/api/field-reports", response_model=FieldReportResponse)
def submit_field_report(
    report: FieldReportCreate,
    user: dict = Depends(require_roles(["field_officer", "local_office", "sub_district_officer", "district_officer", "state_officer", "admin"])),
):
    # Verify habitation exists
    hab = next((h for h in DATA["habitations"] if h["id"] == report.habitation_id), None)
    if not hab:
        raise HTTPException(status_code=400, detail="Invalid habitation ID")
        
    new_report = {
        "id": f"fr-{uuid.uuid4().hex[:6]}",
        "habitation_id": hab["id"],
        "habitation_name": hab["village_name"],
        "officer_id": user.get("sub", "usr-field-003"),
        "officer_name": user.get("full_name", "Field Officer"),
        "report_type": report.report_type,
        "description": report.description,
        "image_url": report.image_url or "https://images.unsplash.com/photo-1544620347-c4fd4a3d5957?auto=format&fit=crop&w=600&q=80",
        "reported_at": datetime.utcnow().isoformat(),
        "verified": user.get("role") in ["admin", "state_officer", "district_officer", "sub_district_officer", "local_office"],
        "severity": report.severity,
        "latitude": report.latitude,
        "longitude": report.longitude,
    }
    DATA["field_reports"].insert(0, new_report)
    return new_report

# ==================== CALCULATE PRIORITY ====================
@app.post("/api/calculate-priority")
def calculate_priority(
    payload: PriorityCalculateRequest,
    user: dict = Depends(require_roles(["local_office", "sub_district_officer", "district_officer", "state_officer", "admin"])),
):
    hab = next((h for h in DATA["habitations"] if h["id"] == payload.habitation_id), None)
    if not hab:
        raise HTTPException(status_code=404, detail="Habitation not found")
        
    landslide = payload.landslide_risk if payload.landslide_risk is not None else hab["landslide_risk"]
    flood = payload.flood_risk if payload.flood_risk is not None else hab["flood_risk"]
    rainfall = payload.extreme_rainfall_risk if payload.extreme_rainfall_risk is not None else hab["extreme_rainfall_risk"]
    road = payload.road_access_score if payload.road_access_score is not None else hab["road_access_score"]
    
    new_h_score = calculate_hazard_score(landslide, flood, rainfall, hab["past_disaster_frequency"])
    new_v_score = calculate_vulnerability_score(
        hab["population"],
        hab["households"],
        hab["children_count"],
        hab["elderly_count"],
        hab["hospital_distance_km"],
        road,
    )
    disaster_hist_score = min(100.0, hab["disaster_history_count"] * 16.0)
    new_p_score, new_level = calculate_relocation_priority(new_h_score, new_v_score, disaster_hist_score)
    
    # Update habitation in state
    hab["hazard_score"] = new_h_score
    hab["vulnerability_score"] = new_v_score
    hab["priority_score"] = new_p_score
    hab["priority_level"] = new_level
    hab["landslide_risk"] = landslide
    hab["flood_risk"] = flood
    hab["extreme_rainfall_risk"] = rainfall
    hab["road_access_score"] = road
    
    return {
        "habitation_id": hab["id"],
        "village_name": hab["village_name"],
        "hazard_score": new_h_score,
        "vulnerability_score": new_v_score,
        "priority_score": new_p_score,
        "priority_level": new_level,
        "updated": True,
    }

# ==================== SIMULATE RELOCATION ====================
@app.post("/api/simulate-relocation")
def simulate_relocation_api(payload: SimulationRequest):
    hab = next((h for h in DATA["habitations"] if h["id"] == payload.habitation_id), None)
    if not hab:
        raise HTTPException(status_code=404, detail="Habitation not found")
        
    site = next((s for s in DATA["relocation_sites"] if s["id"] == payload.relocation_site_id), None)
    if not site:
        raise HTTPException(status_code=404, detail="Relocation site not found")
        
    if payload.families_count <= 0:
        raise HTTPException(status_code=400, detail="Family count must be greater than zero")
        
    res = simulate_safeshift(hab, site, payload.families_count, DATA["relocation_sites"])
    return res

# ==================== ADMIN DATA MANAGEMENT ====================
@app.post("/api/admin/upload-hazard-data")
def upload_hazard_data(
    payload: AdminHazardUploadRequest,
    user: dict = Depends(require_roles(["admin"])),
):
    # Simulated ingestion and parsing
    return {
        "status": "success",
        "message": f"Successfully ingested {payload.source_name} hazard dataset in {payload.hazard_data_format} format.",
        "features_processed": len(payload.payload.get("features", [])) if "features" in payload.payload else 1,
        "processed_by": user.get("full_name", "Admin"),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ==================== EVACUATION ROUTING ====================
def _handle_planner_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PlannerInputError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=500, detail="Evacuation planning failed unexpectedly")


@app.get("/api/evacuation/candidates")
def evacuation_candidates(
    origin_type: str = Query(...),
    origin_id: Optional[str] = Query(None),
    families_count: int = Query(gt=0, le=50000, description="Families to relocate"),
    user: dict = Depends(require_permissions("evacuation.plan")),
):
    try:
        origin = resolve_origin(DATA, {"type": origin_type, "id": origin_id})
    except Exception as exc:
        raise _handle_planner_error(exc)
    try:
        enforce_origin_scope(user, origin["scope"])
    except PermissionError as exc:
        raise _handle_planner_error(exc)

    candidates = select_candidate_sites(DATA, origin, families_count, limit=5)
    record_audit_event("evacuation.candidates_requested", user, {
        "origin": origin.get("id"), "origin_type": origin["type"], "families": families_count,
    })
    return {
        "origin": {"type": origin["type"], "id": origin.get("id"), "label": origin["label"]},
        "families_count": families_count,
        "candidates": candidates,
    }


@app.post("/api/evacuation/plan", response_model=RoutePlanResponse)
def evacuation_plan(
    payload: EvacuationPlanRequest,
    user: dict = Depends(require_permissions("evacuation.plan")),
):
    try:
        origin = resolve_origin(DATA, payload.origin.model_dump())
    except Exception as exc:
        raise _handle_planner_error(exc)
    try:
        enforce_origin_scope(user, origin["scope"])
    except PermissionError as exc:
        raise _handle_planner_error(exc)

    try:
        result = plan_evacuation(
            DATA,
            payload.origin.model_dump(),
            payload.families_count,
            payload.dest_site_id,
        )
    except Exception as exc:
        raise _handle_planner_error(exc)

    record = next((r for r in DATA["route_calculations"] if r["id"] == result.get("route_id")), None)
    if record:
        record["user_id"] = user.get("sub")
        record["user_name"] = user.get("full_name")

    record_audit_event("evacuation.route_planned", user, {
        "route_id": result.get("route_id"),
        "origin": result.get("origin", {}).get("id"),
        "destination": result.get("destination", {}).get("site_id"),
        "families": result.get("families_count"),
        "route_status": result.get("route_status"),
    })
    return result


@app.get("/api/evacuation/routes/{route_id}")
def get_evacuation_route(
    route_id: str,
    user: dict = Depends(require_permissions("evacuation.read")),
):
    record = next((r for r in DATA["route_calculations"] if r["id"] == route_id), None)
    if not record:
        raise HTTPException(status_code=404, detail="Evacuation route not found")
    try:
        enforce_origin_scope(user, record["origin_scope"])
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return route_response_from_record(record)


@app.post("/api/evacuation/routes/{route_id}/confirm")
def confirm_evacuation_route(
    route_id: str,
    payload: RouteConfirmRequest,
    user: dict = Depends(require_permissions("evacuation.confirm")),
):
    record = next((r for r in DATA["route_calculations"] if r["id"] == route_id), None)
    if not record:
        raise HTTPException(status_code=404, detail="Evacuation route not found")
    try:
        enforce_origin_scope(user, record["origin_scope"])
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    # Re-verify destination safety before confirmation (never confirm into a danger zone)
    site = next((s for s in DATA["relocation_sites"] if s["id"] == record["dest_site_id"]), None)
    if site:
        critical = [z for z in DATA["red_zones"] if z.get("risk_level") == "Critical"]
        if any(point_in_zone(site["latitude"], site["longitude"], zone) for zone in critical):
            return {
                "route_status": "DEST_BECAME_UNSAFE",
                "message": "Destination site now lies inside an active critical hazard zone. Confirmation blocked.",
            }

    record["status"] = "confirmed"
    record["confirmed_at"] = datetime.utcnow().isoformat()
    record["decision"] = payload.decision
    record["notes"] = payload.notes
    record_audit_event("evacuation.route_confirmed", user, {
        "route_id": route_id, "decision": payload.decision, "destination": record["dest_site_id"],
    })
    return route_response_from_record(record)


@app.get("/api/evacuation/road-conditions")
def list_road_conditions(user: dict = Depends(require_permissions("evacuation.read"))):
    graph = RoadGraph()
    graph.build_hazard_overlay(
        red_zones=DATA["red_zones"],
        habitations=DATA["habitations"],
        field_reports=DATA["field_reports"],
        road_conditions=DATA["road_conditions"],
        origin_node=None,
        dest_node=None,
    )
    segments = [
        {
            "segment_id": edge["id"],
            "name": edge["name"],
            "status": graph.edge_status.get(edge["id"], {}).get("status", "OPEN"),
            "data_class": "curated_demo",
            "is_synthetic": True,
            "geometry": to_geojson_line([
                (float(graph.nodes[edge["from"]]["lat"]), float(graph.nodes[edge["from"]]["lng"])),
                (float(graph.nodes[edge["to"]]["lat"]), float(graph.nodes[edge["to"]]["lng"])),
            ]),
        }
        for edge in graph.edges
    ]
    return {
        "road_conditions": DATA["road_conditions"],
        "segments": segments,
        "is_synthetic_demo_data": True,
        "data_sources": [
            {
                "layer": "road_network",
                "status": "curated_demo",
                "detail": "Curated pilot corridor graph (NH-07 + key feeders); not live network data.",
            }
        ],
    }


# ==================== FLOOD FORECAST & DATA STATUS ====================
@app.get("/api/flood-forecast", response_model=FloodForecastResponse)
def flood_forecast(
    state: Optional[str] = None,
    district: Optional[str] = None,
    user: dict = Depends(require_permissions("evacuation.read")),
):
    """
    River-level gauges + inundation zones for the requested region.

    Without a configured GloFAS dataset the response is honestly labelled
    NOT_CONFIGURED (empty gauges/zones); with an unreadable or out-of-region
    dataset it is UNAVAILABLE. Only when a CEMS GloFAS NetCDF is configured
    (GLOFAS_DATASET_PATH / GLOPAS_DATA_DIR) and covers the region does the
    response carry data_status=FORECAST with a downloadable discharge reading.
    """
    return get_flood_forecasts(state=state, district=district)


@app.get("/api/data-status", response_model=DataStatusResponse)
def data_status(user: dict = Depends(require_permissions("map.read_public"))):
    """Provenance + status of every map data layer (consumed by the DataSourcePanel).

    Also returns a per-provider breakdown of the official Historical Data
    sources. The provider probes never raise, and any unexpected failure is
    contained here so the layer status panel keeps working.
    """
    try:
        providers = [p.to_dict() for p in historical_provider_statuses()]
    except Exception:  # pragma: no cover - dashboard must not fail on provider probes
        providers = []

    return {
        "layers": get_data_status(),
        "checked_at": datetime.utcnow().isoformat(),
        "providers": providers,
    }


# ==================== HISTORICAL / PREVIOUS-YEAR DATA ====================
# Kerala previous-year rainfall observations.  Every payload is labelled
# "HISTORICAL" when a verified dataset is imported for the district/year and
# "NOT CONFIGURED" otherwise — never LIVE.  The routes are public (read-only
# provenance) and wired through get_db so tests can override the session.

HISTORICAL_NOT_CONFIGURED = "NOT CONFIGURED"


@app.get("/api/historical/availability", response_model=HistoricalAvailabilityResponse)
def historical_availability(db: Session = Depends(get_db)):
    """Whether any historical Kerala dataset has been imported (no live data it)."""
    return availability(db)


@app.get("/api/historical/kerala", response_model=List[HistoricalDistrictSummaryResponse])
def historical_kerala(
    data_year: Optional[int] = Query(None, description="Dataset year to summarise (defaults to configured year)"),
    db: Session = Depends(get_db),
):
    """Per-district summaries for all 14 Kerala districts for the dataset year."""
    # data_year is intentionally ignored here (availability is year-agnostic);
    # baseline endpoint accepts it. Documented so callers are not misled.
    return all_district_summaries(db)


@app.get(
    "/api/historical/kerala/{district}",
    response_model=HistoricalDistrictSummaryResponse,
)
def historical_district(
    district: str,
    db: Session = Depends(get_db),
):
    """Summaries + latest imported observations for one Kerala district."""
    code = district_code(district)
    if code is None:
        raise HTTPException(status_code=404, detail=_unknown_district_message(district))
    return district_summary(db, code)


@app.get(
    "/api/historical/kerala/{district}/baseline",
    response_model=HistoricalBaselineResponse,
)
def historical_district_baseline(
    district: str,
    data_year: Optional[int] = Query(None, description="Dataset year (defaults to configured previous year)"),
    db: Session = Depends(get_db),
):
    """Statistical baseline for one district + dataset year."""
    code = district_code(district)
    if code is None:
        raise HTTPException(status_code=404, detail=_unknown_district_message(district))
    return district_baseline(db, code, data_year=data_year)


@app.get(
    "/api/historical/kerala/{district}/compare",
    response_model=HistoricalCompareResponse,
)
def historical_compare(
    district: str,
    rainfall_mm: float = Query(..., gt=0, le=HISTORICAL_MAX_RAINFALL_MM,
                               description="Observed rainfall in millimetres"),
    observation_date: str = Query(...,
                                  description="Date of the observation (YYYY-MM-DD), e.g. a live gauge reading date"),
    hazard_type: str = Query("rainfall", description="Hazard class of the observation"),
    source: Optional[str] = Query(None, description="Provenance of the live observation"),
    data_year: Optional[int] = Query(None, description="Baseline dataset year (defaults to configured previous year)"),
    db: Session = Depends(get_db),
):
    """
    Compare a *live* rainfall observation against the historical baseline.

    No live feed is wired yet, so live_data_status stays "NOT CONFIGURED" and
    this endpoint only reports the departure relative to the historical average.
    Never fabricates a current reading.
    """
    code = district_code(district)
    if code is None:
        raise HTTPException(status_code=404, detail=_unknown_district_message(district))

    baseline = district_baseline(db, code, data_year=data_year)
    if baseline.get("observation_count", 0) == 0:
        return {
            "district_id": code,
            "district": district_name(code),
            "observation_date": observation_date,
            "rainfall_mm": rainfall_mm,
            "hazard_type": hazard_type,
            "source": source,
            "baseline_average": None,
            "anomaly_mm": None,
            "percent_difference": None,
            "severity": "NORMAL",
            "baseline_status": HISTORICAL_NOT_CONFIGURED,
            "live_data_status": HISTORICAL_NOT_CONFIGURED,
        }

    result = compare_observation(rainfall_mm, baseline)
    return {
        "district_id": code,
        "district": district_name(code),
        "observation_date": observation_date,
        "rainfall_mm": rainfall_mm,
        "hazard_type": hazard_type,
        "source": source,
        "baseline_average": result.get("baseline_average"),
        "anomaly_mm": result.get("anomaly_mm"),
        "percent_difference": result.get("percent_difference"),
        "severity": result.get("severity"),
        "baseline_status": result.get("baseline_status"),
        "live_data_status": result.get("live_data_status"),
    }


def _unknown_district_message(value) -> str:
    return f"Unknown Kerala district '{value}'. Valid codes are 554-567 (or a district name)."
