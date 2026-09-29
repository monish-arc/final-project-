"""
Unit Tests for NammaSafe AI Risk Engine & SafeShift Simulator
"""

import pytest
from app.risk_engine import (
    calculate_hazard_score,
    calculate_vulnerability_score,
    calculate_relocation_priority,
    calculate_site_suitability,
    calculate_carrying_capacity,
    simulate_safeshift,
)

def test_hazard_score_formula():
    # 40% landslide + 30% flood + 20% rainfall + 10% past disaster
    # E.g. landslide=80, flood=70, rainfall=60, past=50
    # Expected = 0.4*80 + 0.3*70 + 0.2*60 + 0.1*50 = 32 + 21 + 12 + 5 = 70.0
    score = calculate_hazard_score(80, 70, 60, 50)
    assert score == 70.0

def test_relocation_priority_rules():
    # 50% hazard + 30% vulnerability + 20% history
    # Test Immediate Relocation (>= 75)
    score, level = calculate_relocation_priority(90, 80, 70)
    # 0.5*90 + 0.3*80 + 0.2*70 = 45 + 24 + 14 = 83.0
    assert score == 83.0
    assert level == "Immediate Relocation"

    # Test Short-Term Relocation (50-74)
    score, level = calculate_relocation_priority(60, 60, 60)
    assert score == 60.0
    assert level == "Short-Term Relocation"

    # Test Medium-Term Relocation (30-49)
    score, level = calculate_relocation_priority(40, 40, 40)
    assert score == 40.0
    assert level == "Medium-Term Relocation"

    # Test Monitor Only (< 30)
    score, level = calculate_relocation_priority(20, 20, 20)
    assert score == 20.0
    assert level == "Monitor Only"

def test_site_suitability_formula():
    # 30% low hazard + 20% flat land + 15% road + 15% water + 10% school + 10% hospital
    # All 100 -> 100.0
    score = calculate_site_suitability(100, 100, 100, 100, 100, 100)
    assert score == 100.0

    score2 = calculate_site_suitability(80, 70, 90, 85, 60, 50)
    # 0.30*80 + 0.20*70 + 0.15*90 + 0.15*85 + 0.10*60 + 0.10*50
    # = 24 + 14 + 13.5 + 12.75 + 6 + 5 = 75.25
    assert score2 == 75.25

def test_carrying_capacity_bottleneck():
    # Final site capacity must be the minimum of the 5 capacities
    cap = calculate_carrying_capacity(
        land_capacity=1000,
        water_capacity=450,
        school_capacity=600,
        health_capacity=500,
        road_capacity=800,
    )
    assert cap == 450 # water capacity is the bottleneck

def test_safeshift_simulator():
    hab = {
        "id": "hab-1",
        "village_name": "Joshimath Central",
        "priority_score": 88.5,
    }
    site = {
        "id": "site-1",
        "site_name": "Gauchar Plateau Safe Zone",
        "available_capacity_families": 500,
        "final_capacity_families": 500,
        "suitability_score": 92.0,
        "water_capacity_families": 450,
        "school_capacity_families": 400,
        "health_capacity_families": 450,
        "road_capacity_families": 600,
    }
    alt_site = {
        "id": "site-2",
        "site_name": "Gwaldam Hill Enclave",
        "available_capacity_families": 300,
        "final_capacity_families": 300,
        "suitability_score": 85.0,
    }

    # Scenario 1: Valid relocation within capacity
    result = simulate_safeshift(hab, site, 150, [site, alt_site])
    assert result["is_capacity_sufficient"] is True
    assert result["remaining_capacity_after"] == 350
    assert result["risk_reduction_percent"] > 60.0
    assert result["water_capacity_status"] in ["Adequate", "Near Limit"]

    # Scenario 2: Exceeded capacity triggering alternative site recommendation
    result_over = simulate_safeshift(hab, site, 600, [site, alt_site])
    assert result_over["is_capacity_sufficient"] is False
    assert "CRITICAL OVER-CAPACITY" in result_over["explanation"]

    # Scenario 3: Invalid family count <= 0 raises ValueError
    with pytest.raises(ValueError):
        simulate_safeshift(hab, site, 0)
