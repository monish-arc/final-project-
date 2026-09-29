"""
NammaSafe AI - Risk Engine & Decision Support Formulas
Chamoli District, Uttarakhand Pilot
"""

from typing import Dict, Any, List, Optional, Tuple

def calculate_hazard_score(
    landslide_risk: float,
    flood_risk: float,
    extreme_rainfall_risk: float,
    past_disaster_frequency: float,
) -> float:
    """
    1. Hazard Score Formula:
    40% landslide risk +
    30% flood or flash-flood risk +
    20% extreme rainfall risk +
    10% past disaster frequency
    """
    score = (
        0.40 * landslide_risk
        + 0.30 * flood_risk
        + 0.20 * extreme_rainfall_risk
        + 0.10 * past_disaster_frequency
    )
    return round(max(0.0, min(100.0, score)), 2)


def calculate_vulnerability_score(
    population: int,
    households: int,
    children_count: int,
    elderly_count: int,
    hospital_distance_km: float,
    road_access_score: float, # 0 (no road) to 100 (all-weather highway)
) -> float:
    """
    2. Vulnerability Score Formula:
    35% population density +
    25% children and elderly ratio +
    20% poor road access +
    20% hospital distance
    """
    # Normalize population density factor: typical Himalayan habitation scale 200 - 15000
    pop_density_factor = min(100.0, (population / 150.0))
    
    # Children and elderly ratio
    vulnerable_dependents = children_count + elderly_count
    ratio = (vulnerable_dependents / max(1, population)) * 100.0
    ratio_factor = min(100.0, ratio * 2.0) # scaled so 50% ratio maps to 100

    # Poor road access (inverse of road_access_score)
    poor_road_access = max(0.0, 100.0 - road_access_score)

    # Hospital distance: 0km is 0 vulnerability, >= 40km is 100 vulnerability
    hospital_distance_factor = min(100.0, (hospital_distance_km / 40.0) * 100.0)

    score = (
        0.35 * pop_density_factor
        + 0.25 * ratio_factor
        + 0.20 * poor_road_access
        + 0.20 * hospital_distance_factor
    )
    return round(max(0.0, min(100.0, score)), 2)


def calculate_relocation_priority(
    hazard_score: float,
    vulnerability_score: float,
    disaster_history_score: float,
) -> Tuple[float, str]:
    """
    3. Relocation Priority Formula:
    50% hazard score +
    30% vulnerability score +
    20% disaster-history score

    Priority rules:
    - Score 75 to 100: Immediate Relocation
    - Score 50 to 74: Short-Term Relocation
    - Score 30 to 49: Medium-Term Relocation
    - Score below 30: Monitor Only
    """
    final_score = (
        0.50 * hazard_score
        + 0.30 * vulnerability_score
        + 0.20 * disaster_history_score
    )
    final_score = round(max(0.0, min(100.0, final_score)), 2)

    if final_score >= 75.0:
        priority_level = "Immediate Relocation"
    elif final_score >= 50.0:
        priority_level = "Short-Term Relocation"
    elif final_score >= 30.0:
        priority_level = "Medium-Term Relocation"
    else:
        priority_level = "Monitor Only"

    return final_score, priority_level


def calculate_site_suitability(
    low_hazard_score: float,
    flat_land_score: float,
    road_score: float,
    water_score: float,
    school_score: float,
    hospital_score: float,
) -> float:
    """
    4. Site Suitability Formula:
    30% low hazard risk +
    20% flat land / low slope +
    15% road access +
    15% water availability +
    10% school access +
    10% hospital access
    """
    score = (
        0.30 * low_hazard_score
        + 0.20 * flat_land_score
        + 0.15 * road_score
        + 0.15 * water_score
        + 0.10 * school_score
        + 0.10 * hospital_score
    )
    return round(max(0.0, min(100.0, score)), 2)


def calculate_carrying_capacity(
    land_capacity: int,
    water_capacity: int,
    school_capacity: int,
    health_capacity: int,
    road_capacity: int,
) -> int:
    """
    5. Carrying Capacity Formula:
    Final site capacity must be the minimum of:
    - land-based housing capacity
    - water capacity
    - school capacity
    - health-service capacity
    - road-access capacity
    """
    return min(
        land_capacity,
        water_capacity,
        school_capacity,
        health_capacity,
        road_capacity,
    )


def simulate_safeshift(
    habitation: Dict[str, Any],
    target_site: Dict[str, Any],
    families_to_relocate: int,
    available_sites: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    SafeShift Simulator Engine:
    - Validates family count > 0 and <= site capacity
    - Evaluates resource stress (water, school, hospital, road)
    - Computes risk reduction percentage
    - Recommends alternative site if capacity is exceeded
    """
    if families_to_relocate <= 0:
        raise ValueError("Number of families to relocate must be a positive integer.")

    available_capacity = target_site.get("available_capacity_families", target_site.get("final_capacity_families", 500))
    water_cap = target_site.get("water_capacity_families", 500)
    school_cap = target_site.get("school_capacity_families", 400)
    health_cap = target_site.get("health_capacity_families", 450)
    road_cap = target_site.get("road_capacity_families", 600)

    is_capacity_sufficient = families_to_relocate <= available_capacity

    # Capacity remaining after shifting
    remaining_capacity = max(0, available_capacity - families_to_relocate)

    # Resource statuses
    def check_status(relocated: int, total_cap: int) -> str:
        ratio = relocated / max(1, total_cap)
        if ratio > 1.0:
            return "Exceeded"
        elif ratio >= 0.80:
            return "Near Limit"
        else:
            return "Adequate"

    water_status = check_status(families_to_relocate, water_cap)
    school_status = check_status(families_to_relocate, school_cap)
    health_status = check_status(families_to_relocate, health_cap)
    road_status = check_status(families_to_relocate, road_cap)

    # Identify bottleneck
    capacities = [
        ("Water Network", water_cap),
        ("School Enrolment", school_cap),
        ("Healthcare Facilities", health_cap),
        ("Road Access Ingress", road_cap),
        ("Land Footprint", target_site.get("land_capacity_families", 500)),
    ]
    bottleneck = min(capacities, key=lambda x: x[1])[0]

    # Risk reduction calculation
    # Habitation priority score represents current risk exposure.
    # Moving to a safe site with high suitability reduces hazard by ~75% - 94%
    hab_priority = habitation.get("priority_score", 85.0)
    site_suitability = target_site.get("suitability_score", 90.0)
    residual_risk = max(5.0, (100.0 - site_suitability) * 0.4)
    risk_reduction_pct = round(
        max(60.0, min(96.0, ((hab_priority - residual_risk) / hab_priority) * 100.0)),
        1,
    )

    explanation = (
        f"Relocating {families_to_relocate} families from {habitation.get('village_name', 'Habitation')} "
        f"to {target_site.get('site_name', 'Safe Site')} yields an estimated {risk_reduction_pct}% risk reduction. "
    )
    if is_capacity_sufficient:
        explanation += (
            f"The site possesses sufficient buffer with {remaining_capacity} family allocations remaining. "
            f"Primary resource bottleneck to monitor: {bottleneck}."
        )
    else:
        explanation += (
            f"CRITICAL OVER-CAPACITY: Requested {families_to_relocate} families exceeds the net carrying "
            f"capacity of {available_capacity} families by {families_to_relocate - available_capacity}. "
            f"Immediate phased allocation or alternative site required."
        )

    # Alternative site search if over capacity
    alternative_site = None
    if not is_capacity_sufficient and available_sites:
        # Filter other sites that can accommodate the families
        candidates = [
            s for s in available_sites 
            if s.get("id") != target_site.get("id") 
            and s.get("available_capacity_families", s.get("final_capacity_families", 0)) >= families_to_relocate
        ]
        if candidates:
            # Pick highest suitability
            alternative_site = max(candidates, key=lambda x: x.get("suitability_score", 0))
        elif available_sites:
            # Pick site with highest available capacity
            alternative_site = max(
                [s for s in available_sites if s.get("id") != target_site.get("id")],
                key=lambda x: x.get("available_capacity_families", 0),
                default=None
            )

    return {
        "habitation_id": habitation.get("id"),
        "habitation_name": habitation.get("village_name"),
        "target_site_id": target_site.get("id"),
        "target_site_name": target_site.get("site_name"),
        "families_relocated": families_to_relocate,
        "is_capacity_sufficient": is_capacity_sufficient,
        "risk_reduction_percent": risk_reduction_pct,
        "initial_site_capacity": available_capacity,
        "remaining_capacity_after": remaining_capacity,
        "water_capacity_status": water_status,
        "school_capacity_status": school_status,
        "hospital_access_status": health_status,
        "road_access_status": road_status,
        "bottleneck_factor": bottleneck,
        "explanation": explanation,
        "alternative_site": alternative_site,
    }
