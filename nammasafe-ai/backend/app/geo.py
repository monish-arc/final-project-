"""
Pure-Python geospatial helpers for NammaSafe AI evacuation routing.
No external GIS dependencies required (pilot-friendly, PostGIS-compatible patterns).
"""

import math
from typing import List, Tuple

Point = Tuple[float, float]  # (latitude, longitude)
Ring = List[Point]


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres between two lat/lng coordinates."""
    earth_radius_m = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlng / 2.0) ** 2
    )
    return 2.0 * earth_radius_m * math.asin(math.sqrt(a))


def polyline_length(coords: List[Tuple[float, float]]) -> float:
    """Total metres of a [lat, lng] polyline."""
    total = 0.0
    for i in range(1, len(coords)):
        total += haversine(
            coords[i - 1][0], coords[i - 1][1], coords[i][0], coords[i][1]
        )
    return total


def _local_point(lat0: float, lng0: float, lat: float, lng: float) -> Tuple[float, float]:
    """Approximate planar (x, y) in metres relative to a reference coordinate."""
    x = (lng - lng0) * 111320.0 * math.cos(math.radians(lat0))
    y = (lat - lat0) * 110540.0
    return x, y


def distance_point_to_segment(
    lat: float, lng: float, a_lat: float, a_lng: float, b_lat: float, b_lng: float
) -> float:
    """Shortest distance in metres from a point to a segment in local planar space."""
    ref_lat = (lat + a_lat + b_lat) / 3.0
    ref_lng = (lng + a_lng + b_lng) / 3.0
    px, py = _local_point(ref_lat, ref_lng, lat, lng)
    ax, ay = _local_point(ref_lat, ref_lng, a_lat, a_lng)
    bx, by = _local_point(ref_lat, ref_lng, b_lat, b_lng)
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0.0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    proj_x = ax + t * dx
    proj_y = ay + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def extract_rings(zone_geometry: dict) -> List[Ring]:
    """Convert a GeoJSON Polygon/MultiPolygon into lat/lng rings."""
    rings: List[Ring] = []
    coords = zone_geometry.get("coordinates", [])
    geom_type = zone_geometry.get("type", "")
    if geom_type == "Polygon":
        polys = [coords]
    elif geom_type == "MultiPolygon":
        polys = coords
    else:
        return rings
    for poly in polys:
        for ring in poly:
            rings.append([(lat, lng) for lng, lat in ring])
    return rings


def point_in_ring(lat: float, lng: float, ring: Ring) -> bool:
    """Ray-casting point-in-polygon test on a closed lat/lng ring."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        lat_i, lng_i = ring[i]
        lat_j, lng_j = ring[j]
        if (lng_i > lng) != (lng_j > lng):
            cross_lat = lat_i + (lng - lng_i) * (lat_j - lat_i) / (
                lng_j - lng_i
            )
            if cross_lat > lat:
                inside = not inside
        j = i
    return inside


def point_in_any_ring(lat: float, lng: float, rings: List[Ring]) -> bool:
    return any(point_in_ring(lat, lng, ring) for ring in rings)


def segment_intersects_rings(
    a_lat: float, a_lng: float, b_lat: float, b_lng: float, rings: List[Ring]
) -> bool:
    """Coarse segment-versus-polygon test (endpoints + interior samples)."""
    for ring in rings:
        if point_in_ring(a_lat, a_lng, ring) or point_in_ring(b_lat, b_lng, ring):
            return True
        for fraction in (0.25, 0.5, 0.75):
            lat = a_lat + (b_lat - a_lat) * fraction
            lng = a_lng + (b_lng - a_lng) * fraction
            if point_in_ring(lat, lng, ring):
                return True
    return False


def point_in_zone(lat: float, lng: float, red_zone: dict) -> bool:
    rings = extract_rings(red_zone.get("zone_geometry", {}))
    return point_in_any_ring(lat, lng, rings)


def to_geojson_line(coords: List[Tuple[float, float]]) -> dict:
    """Build a GeoJSON LineString from [lat, lng] coordinates."""
    return {
        "type": "LineString",
        "coordinates": [[lng, lat] for lat, lng in coords],
    }