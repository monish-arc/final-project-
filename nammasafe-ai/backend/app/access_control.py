"""Role permissions and administrative-scope checks for the pilot platform."""

from typing import Any, Dict, Iterable, Mapping, Optional, Set


ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    "normal_citizen": {"map.read_public", "alert.read", "accommodation.read", "evacuation.read", "weather.history.read"},
    "field_officer": {
        "map.read_public", "alert.read", "alert.raise", "accommodation.read",
        "evacuation.read", "weather.history.read",
    },
    "local_office": {
        "map.read_public", "alert.read", "alert.raise", "accommodation.read",
        "accommodation.manage", "evacuation.read", "evacuation.plan", "weather.history.read",
    },
    "sub_district_officer": {
        "map.read_public", "alert.read", "alert.raise", "accommodation.read",
        "accommodation.manage", "assignment.read", "assignment.manage",
        "evacuation.read", "evacuation.plan", "evacuation.confirm", "weather.history.read",
    },
    "district_officer": {
        "map.read_public", "alert.read", "alert.raise", "accommodation.read",
        "accommodation.manage", "assignment.read", "assignment.manage",
        "evacuation.read", "evacuation.plan", "evacuation.confirm", "weather.history.read",
    },
    "state_officer": {
        "map.read_public", "alert.read", "alert.raise", "accommodation.read",
        "accommodation.manage", "assignment.read", "assignment.manage",
        "evacuation.read", "evacuation.plan", "evacuation.confirm", "weather.history.read",
    },
    "gis_analysis_officer": {
        "map.read_public", "alert.read", "accommodation.read", "hazard-history.read",
        "analytics.read", "evacuation.read", "evacuation.plan", "weather.history.read",
    },
    "admin": {
        "map.read_public", "alert.read", "accommodation.read", "assignment.read",
        "assignment.manage", "hazard-history.read", "analytics.read", "audit-log.read",
        "session-log.read", "system-health.read", "technical-data.repair", "role.manage",
        "evacuation.read", "evacuation.plan", "evacuation.confirm", "weather.history.read",
    },
}


def has_permissions(role: str, permissions: Iterable[str]) -> bool:
    granted = ROLE_PERMISSIONS.get(role, set())
    return all(permission in granted for permission in permissions)


def scope_contains(
    assignment: Mapping[str, Optional[str]], requested: Mapping[str, Optional[str]]
) -> bool:
    """Return whether an assigned jurisdiction contains a requested jurisdiction."""
    for level in ("state_id", "district_id", "sub_district_id", "area_id"):
        assigned_value = assignment.get(level)
        requested_value = requested.get(level)
        if assigned_value and assigned_value != "*" and requested_value != assigned_value:
            return False
    return True


def can_manage_role(actor_role: str, target_role: str) -> bool:
    managed_roles = {
        "sub_district_officer": {"field_officer", "local_office"},
        "district_officer": {"field_officer", "local_office", "sub_district_officer"},
        "state_officer": {
            "field_officer", "local_office", "sub_district_officer", "district_officer",
        },
        "admin": {
            "normal_citizen", "field_officer", "local_office", "sub_district_officer",
            "district_officer", "state_officer", "gis_analysis_officer",
        },
    }
    return target_role in managed_roles.get(actor_role, set())
