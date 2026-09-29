from app.access_control import ROLE_PERMISSIONS, can_manage_role, has_permissions, scope_contains


def test_every_role_has_read_only_weather_history_permission():
    """The Historical Weather Map is visible on every portal — all roles hold
    the read-only weather.history.read permission."""
    for role in ROLE_PERMISSIONS:
        assert "weather.history.read" in ROLE_PERMISSIONS[role], role


def test_citizen_permissions_are_limited_to_public_information():
    assert has_permissions("normal_citizen", ["map.read_public", "alert.read"])
    assert not has_permissions("normal_citizen", ["alert.raise"])
    assert not has_permissions("normal_citizen", ["accommodation.manage"])


def test_gis_analyst_has_analysis_but_no_operational_mutation_permissions():
    assert has_permissions("gis_analysis_officer", ["hazard-history.read", "analytics.read"])
    assert not has_permissions("gis_analysis_officer", ["alert.raise"])
    assert not has_permissions("gis_analysis_officer", ["assignment.manage"])


def test_scope_containment_respects_the_administrative_hierarchy():
    district_scope = {
        "state_id": "uk",
        "district_id": "chamoli",
        "sub_district_id": "*",
        "area_id": "*",
    }
    requested_area = {
        "state_id": "uk",
        "district_id": "chamoli",
        "sub_district_id": "joshimath",
        "area_id": "joshimath-central",
    }
    other_district = {**requested_area, "district_id": "rudraprayag"}

    assert scope_contains(district_scope, requested_area)
    assert not scope_contains(district_scope, other_district)


def test_officer_assignment_hierarchy_prevents_peer_or_higher_management():
    assert can_manage_role("sub_district_officer", "field_officer")
    assert can_manage_role("district_officer", "sub_district_officer")
    assert not can_manage_role("sub_district_officer", "district_officer")
    assert not can_manage_role("gis_analysis_officer", "field_officer")
