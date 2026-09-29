"""Risk assessment engine for SAFE_MOVE_AI.

Combines the core weighted signals (rainfall, water, elevation, historical,
proximity, field_damage) into a single 0-100 hazard-susceptibility score. Two
optional Bhuvan / ISRO signals (lulc, geoid) join only when the operator sets
BHUVAN_RISK_FACTOR=on; otherwise they exist as explicit NOT_AVAILABLE factors.

Crucial honesty rules (per the platform spec):
  * The score is *susceptibility*, not an exact future prediction.
  * Missing signals never deflate the score: the score is
        sum(weight_i * score_i) / sum(weight_i of AVAILABLE signals)
    and missing factors carry impact="NOT AVAILABLE".
  * Weights come from config.RISK_ASSESSMENT_WEIGHTS so operators can tune the
    engine without code changes.
  * The output deliberately uses "AI-Assessed High-Risk Zone" vocabulary, never
    the official "Red Zone" claim, for model-generated zones.

Assessment modes (config.ASSESSMENT_MODE):
  rule_based -> weighted rules only (source of truth)
  hybrid     -> rule score with model score attached when a model is loaded
  ml         -> model score primary, transparent fallback to rules
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app import config
from app.bhuvan_service import STATUS_AVAILABLE, STATUS_CACHED, bhuvan_service
from app.cache import TTLCache
from app.disaster_events import get_disaster_events_near
from app.flood_service import FloodDataService
from app.ml_model import ModelRegistry
from app.rainfall_service import RainfallDataService
from app.terrain_service import TerrainService
from app.weather_service import WeatherService

SYSTEMATICS = {
    "rainfall": "Rainfall intensity",
    "water": "River flood discharge",
    "elevation": "Terrain elevation & slope",
    "historical": "Historical disaster record",
    "proximity": "Proximity to hazard corridors",
    "field_damage": "Field damage reports",
    "lulc": "Land-use / land-cover (LULC)",
    "geoid": "Bhuvan CartoDEM geoid tile",
}


def _status_of(payload: Dict[str, Any]) -> str:
    return (payload.get("data_status") or "UNAVAILABLE").upper()


def _live(payload: Dict[str, Any]) -> bool:
    return _status_of(payload) == "LIVE"


def band_for(score: float) -> Dict[str, str]:
    for band in config.RISK_BANDS:
        if score <= band["max"]:
            return {"band": band["level"], "level": band["level"].title()}
    return {"band": "CRITICAL", "level": "Critical"}


def _rainfall_score(
    weather: Dict[str, Any],
    rainfall: Dict[str, Any],
    historical: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    # Historical (ERA5 archive) month drives the rainfall signal when the caller
    # requests a past period — real reanalysis, labelled HISTORICAL, never a
    # live observation and never fabricated.
    if historical is not None:
        variable = (historical.get("variables") or {}).get("precipitation") or {}
        monthly_mm = variable.get("value")
        year = historical.get("year")
        month = historical.get("month")
        period = f"{int(year):04d}-{int(month):02d}" if year and month else "completed month"
        if monthly_mm is None:
            return {
                "key": "rainfall",
                "label": SYSTEMATICS["rainfall"],
                "score": None,
                "weight": config.RISK_ASSESSMENT_WEIGHTS.get("rainfall", 0.0),
                "impact": "NOT_AVAILABLE",
                "detail": f"Historical ERA5 rainfall unavailable for {period}.",
                "source": {"name": "Open-Meteo ERA5 Archive", "status": "HISTORICAL"},
            }
        score = max(0.0, min(100.0, float(monthly_mm) / 500.0 * 100.0))
        return {
            "key": "rainfall",
            "label": SYSTEMATICS["rainfall"],
            "score": round(score, 1),
            "weight": config.RISK_ASSESSMENT_WEIGHTS.get("rainfall", 0.0),
            "impact": "ATTRIBUTABLE" if score < 70 else "SEVERE",
            "detail": f"ERA5 historical precipitation {monthly_mm} mm for {period} (HISTORICAL).",
            "source": {
                "name": "Open-Meteo ERA5 Archive",
                "status": "HISTORICAL",
                "reference": period,
            },
        }
    source = None
    intensity_mm = None
    if _live(rainfall):
        intensity_mm = rainfall.get("precipitation_mm_hour")
        source = ("NASA GPM IMERG", "LIVE", rainfall.get("dataset"))
    elif _live(weather):
        intensity_mm = weather.get("current", {}).get("precipitation_mm")
        source = ("Open-Meteo", "LIVE", "current precipitation")
    if intensity_mm is None:
        status = "LIVE" if (_live(weather) or _live(rainfall)) else _status_of(
            rainfall if not _live(weather) else weather
        )
        name = "NASA GPM IMERG" if _live(rainfall) else "Open-Meteo"
        return {
            "key": "rainfall",
            "label": SYSTEMATICS["rainfall"],
            "score": None,
            "weight": config.RISK_ASSESSMENT_WEIGHTS.get("rainfall", 0.0),
            "impact": "NOT_AVAILABLE",
            "detail": f"No live rainfall reading from {name}.",
            "source": {"name": name, "status": status},
        }
    score = min(100.0, intensity_mm / 50.0 * 100.0)  # 50 mm/hr ≈ extreme band
    score = max(0.0, score)
    name, status, reference = source
    return {
        "key": "rainfall",
        "label": SYSTEMATICS["rainfall"],
        "score": round(score, 1),
        "weight": config.RISK_ASSESSMENT_WEIGHTS.get("rainfall", 0.0),
        "impact": "ATTRIBUTABLE" if score < 70 else "SEVERE",
        "detail": f"{intensity_mm} mm/hr{' (IMERG)' if reference else ''} observed or forecast.",
        "source": {"name": name, "status": status, "reference": reference},
    }


def _water_score(flood: Dict[str, Any]) -> Dict[str, Any]:
    band = flood.get("discharge_band")
    status = _status_of(flood)
    name = flood.get("data_source", "Copernicus GloFAS")
    if status not in ("LIVE", "FORECAST") or not band:
        return {
            "key": "water",
            "label": SYSTEMATICS["water"],
            "score": None,
            "weight": config.RISK_ASSESSMENT_WEIGHTS.get("water", 0.0),
            "impact": "NOT_AVAILABLE",
            "detail": f"GloFAS data {'not configured' if status == 'NOT_CONFIGURED' else 'unavailable'} for this reach.",
            "source": {"name": name, "status": status},
        }
    mapping = {"NORMAL": 20.0, "ELEVATED": 60.0, "EXTREME": 90.0, "UNKNOWN": None}
    score = mapping.get(band)
    if score is None:
        return {
            "key": "water", "label": SYSTEMATICS["water"], "score": None,
            "weight": config.RISK_ASSESSMENT_WEIGHTS.get("water", 0.0),
            "impact": "NOT_AVAILABLE", "detail": "Discharge band unknown.",
            "source": {"name": name, "status": status},
        }
    return {
        "key": "water", "label": SYSTEMATICS["water"], "score": score,
        "weight": config.RISK_ASSESSMENT_WEIGHTS.get("water", 0.0),
        "impact": "NOT_ATTRIBUTABLE" if score < 60 else ("ATTRIBUTABLE" if score < 90 else "SEVERE"),
        "detail": f"Forecast discharge band {band} ({flood.get('river_discharge_m3s')} m3/s) from {flood.get('dataset', 'GloFAS')}.",
        "source": {"name": name, "status": status},
    }


def _elevation_score(terrain: Dict[str, Any]) -> Dict[str, Any]:
    status = _status_of(terrain)
    if status != "LIVE":
        return {
            "key": "elevation", "label": SYSTEMATICS["elevation"],
            "score": None, "weight": config.RISK_ASSESSMENT_WEIGHTS.get("elevation", 0.0),
            "impact": "NOT_AVAILABLE",
            "detail": "SRTM elevation unavailable.",
            "source": {"name": terrain.get("data_source", "NASA Earthdata SRTM"), "status": status},
        }
    slopes = {"NEARLY_LEVEL": 15.0, "GENTLY_SLOPING": 25.0, "MODERATELY_SLOPING": 45.0,
              "STEEP": 65.0, "VERY_STEEP": 85.0}
    slope_score = slopes.get(terrain.get("slope_category"), 0.0)
    elevation = terrain.get("elevation_m")
    low_land_score = 0.0
    if elevation is not None:
        if elevation < 5.0:
            low_land_score = 70.0
        elif elevation < 20.0:
            low_land_score = 45.0
        elif elevation < 50.0:
            low_land_score = 25.0
    score = max(slope_score, low_land_score)
    detail = (
        f"Elevation {elevation} m, slope {terrain.get('slope_percent')}% "
        f"({terrain.get('slope_category')})."
    )
    return {
        "key": "elevation", "label": SYSTEMATICS["elevation"], "score": round(score, 1),
        "weight": config.RISK_ASSESSMENT_WEIGHTS.get("elevation", 0.0),
        "impact": "ATTRIBUTABLE" if score else "NOT_ATTRIBUTABLE", "detail": detail,
        "source": {"name": terrain.get("data_source", "NASA Earthdata SRTM"), "status": status},
    }


def _historical_score(events_payload: Dict[str, Any]) -> Dict[str, Any]:
    events = events_payload.get("events", [])
    if not events:
        return {
            "key": "historical", "label": SYSTEMATICS["historical"], "score": 10.0,
            "weight": config.RISK_ASSESSMENT_WEIGHTS.get("historical", 0.0),
            "impact": "NOT_ATTRIBUTABLE",
            "detail": f"No curated disaster events within {events_payload.get('radius_km')} km.",
            "source": {"name": "Disaster-events provenance table", "status": "HISTORICAL",
                       "updated_at": events_payload.get("data_status")},
        }
    count = len(events)
    severity_bonus = 0.0
    for event in events:
        if event.get("severity_level") in ("EXTREME", "CRITICAL"):
            severity_bonus += 5.0
    base = 40.0 if count == 1 else (60.0 if count <= 3 else 80.0)
    score = min(100.0, base + severity_bonus)
    names = "; ".join(e["name"] for e in events[:3])
    return {
        "key": "historical", "label": SYSTEMATICS["historical"], "score": round(score, 1),
        "weight": config.RISK_ASSESSMENT_WEIGHTS.get("historical", 0.0),
        "impact": "ATTRIBUTABLE" if score >= 45 else "NOT_ATTRIBUTABLE",
        "detail": f"{count} recorded event(s) nearby: {names}.",
        "source": {"name": "Disaster-events provenance table", "status": "HISTORICAL",
                   "updated_at": events_payload.get("data_status")},
    }


def _proximity_score(events_payload: Dict[str, Any]) -> Dict[str, Any]:
    events = events_payload.get("events", [])
    distances = [e.get("distance_km") for e in events if e.get("distance_km") is not None]
    radius = events_payload.get("radius_km", config.HISTORICAL_EVENT_RADIUS_KM)
    if not distances:
        return {
            "key": "proximity", "label": SYSTEMATICS["proximity"], "score": 5.0,
            "weight": config.RISK_ASSESSMENT_WEIGHTS.get("proximity", 0.0),
            "impact": "NOT_ATTRIBUTABLE",
            "detail": f"No recorded hazard corridor within {radius} km of the point.",
            "source": {"name": "Disaster-events provenance table", "status": "HISTORICAL"},
        }
    nearest = min(distances)
    if nearest < 10.0:
        score = 80.0
    elif nearest < 25.0:
        score = 60.0
    elif nearest < 50.0:
        score = 35.0
    elif nearest < 100.0:
        score = 15.0
    else:
        score = 5.0
    return {
        "key": "proximity", "label": SYSTEMATICS["proximity"], "score": round(score, 1),
        "weight": config.RISK_ASSESSMENT_WEIGHTS.get("proximity", 0.0),
        "impact": "ATTRIBUTABLE" if score >= 40 else "NOT_ATTRIBUTABLE",
        "detail": f"Nearest recorded event corridor is {round(nearest, 1)} km away.",
        "source": {"name": "Disaster-events provenance table", "status": "HISTORICAL"},
    }


def _field_damage_score(field_reports: List[Dict[str, Any]], lat: float, lng: float) -> Dict[str, Any]:
    from app.geo import haversine

    radius_m = config.FIELD_REPORT_RADIUS_KM * 1000.0
    nearby = []
    for report in field_reports or []:
        r_lat = report.get("latitude")
        r_lng = report.get("longitude")
        if r_lat is None or r_lng is None:
            continue
        if haversine(lat, lng, float(r_lat), float(r_lng)) <= radius_m:
            nearby.append(report)
    severity_weight = {"Critical": 30.0, "High": 22.0, "Medium": 12.0, "Low": 5.0}
    score = 0.0
    for report in nearby:
        base = severity_weight.get(report.get("severity"), 10.0)
        if report.get("verified"):
            base *= 1.5
        score = min(100.0, score + base)
    if not nearby:
        return {
            "key": "field_damage", "label": SYSTEMATICS["field_damage"], "score": 5.0,
            "weight": config.RISK_ASSESSMENT_WEIGHTS.get("field_damage", 0.0),
            "impact": "NOT_ATTRIBUTABLE",
            "detail": f"No field damage reports within {config.FIELD_REPORT_RADIUS_KM} km.",
            "source": {"name": "Verified field reports", "status": "LIVE"},
        }
    return {
        "key": "field_damage", "label": SYSTEMATICS["field_damage"], "score": round(score, 1),
        "weight": config.RISK_ASSESSMENT_WEIGHTS.get("field_damage", 0.0),
        "impact": "ATTRIBUTABLE" if score >= 40 else "NOT_ATTRIBUTABLE",
        "detail": f"{len(nearby)} nearby field report(s); score accumulates severity (higher for verified).",
        "source": {"name": "Verified field reports", "status": "LIVE"},
    }


def _bhuvan_enabled() -> bool:
    return str(config.BHUVAN_RISK_FACTOR).strip().lower() in ("on", "true", "1", "yes")


def _lulc_score(latitude: float, longitude: float) -> Dict[str, Any]:
    """Bhuvan ISRO LULC 250K class as a heuristic surface-cover signal.

    Gated behind config.BHUVAN_RISK_FACTOR. Off (default) => NOT_AVAILABLE, so
    the weighted engine never includes it unless the operator opts in.
    """
    weight = config.RISK_ASSESSMENT_WEIGHTS.get("lulc", 0.0)
    if not _bhuvan_enabled():
        return {
            "key": "lulc", "label": SYSTEMATICS["lulc"], "score": None,
            "weight": weight, "impact": "NOT_AVAILABLE",
            "detail": "Bhuvan LULC factor disabled (BHUVAN_RISK_FACTOR is off).",
            "source": {"name": "Bhuvan / ISRO", "status": "NOT_CONFIGURED"},
        }
    payload = bhuvan_service.get_lulc_250k(longitude, latitude, year="all")
    status = payload.get("data_status")
    class_name = payload.get("class")
    if status not in (STATUS_AVAILABLE, STATUS_CACHED) or not class_name:
        return {
            "key": "lulc", "label": SYSTEMATICS["lulc"], "score": None,
            "weight": weight, "impact": "NOT_AVAILABLE",
            "detail": "Bhuvan LULC 250K class unavailable for this point.",
            "source": {"name": "Bhuvan / ISRO", "status": status or "UNAVAILABLE"},
        }
    susceptibility = bhuvan_service.lulc_susceptibility(class_name) or 30.0
    return {
        "key": "lulc", "label": SYSTEMATICS["lulc"], "score": round(susceptibility, 1),
        "weight": weight,
        "impact": "ATTRIBUTABLE" if susceptibility >= 45 else "NOT_ATTRIBUTABLE",
        "detail": f"Bhuvan LULC 250K class '{class_name}' at this point — heuristic surface-cover susceptibility, not a flood model.",
        "source": {"name": "Bhuvan / ISRO", "status": status},
    }


def _geoid_score() -> Dict[str, Any]:
    """Bhuvan CartoDEM geoid tile proxy as an annotation-only factor.

    A geoid offset is a vertical datum correction, NOT a hazard. Gated behind
    BHUVAN_RISK_FACTOR and BHUVAN_API_KEY. It never fabricates a height: the
    elevation factor keeps the verified NASA Earthdata SRTM source.
    """
    weight = config.RISK_ASSESSMENT_WEIGHTS.get("geoid", 0.0)
    if not _bhuvan_enabled():
        return {
            "key": "geoid", "label": SYSTEMATICS["geoid"], "score": None,
            "weight": weight, "impact": "NOT_AVAILABLE",
            "detail": "Bhuvan geoid factor disabled (BHUVAN_RISK_FACTOR is off).",
            "source": {"name": "Bhuvan / ISRO", "status": "NOT_CONFIGURED"},
        }
    if not config.BHUVAN_API_KEY:
        return {
            "key": "geoid", "label": SYSTEMATICS["geoid"], "score": None,
            "weight": weight, "impact": "NOT_AVAILABLE",
            "detail": "BHUVAN_API_KEY not configured — Bhuvan CartoDEM tile proxy unavailable.",
            "source": {"name": "Bhuvan / ISRO", "status": "NOT_CONFIGURED"},
        }
    return {
        "key": "geoid", "label": SYSTEMATICS["geoid"], "score": 5.0,
        "weight": weight, "impact": "NOT_ATTRIBUTABLE",
        "detail": "Bhuvan CartoDEM geoid tile-download proxy available; geoid offsets are vertical datum corrections — elevation keeps the verified SRTM source.",
        "source": {"name": "Bhuvan / ISRO", "status": "AVAILABLE"},
    }


def _infer_disaster_type(factors: List[Dict[str, Any]]) -> str:
    lookup = {f["key"]: f for f in factors}
    water = lookup.get("water", {})
    terrain = lookup.get("elevation", {})
    rainfall = lookup.get("rainfall", {})
    historical = lookup.get("historical", {})

    dramatic_rain = (rainfall.get("score") or 0.0) >= 70
    steep = (terrain.get("score") or 0.0) >= 65
    water_high = (water.get("score") or 0.0) >= 60

    if steep and dramatic_rain:
        return "LANDSLIDE"
    if wr := (lookup.get("water", {}).get("score") or 0.0) >= 90:
        if _low_lying(terrain.get("detail")) is not None and _low_lying(terrain.get("detail")) < 20:
            return "COASTAL_FLOOD"
        return "FLOOD"
    if water_high:
        return "FLOOD"
    # Historical record drives the class when live data is weak.
    hist = historical.get("detail") or ""
    cyclones = [k for k in ("Cyclone", "Tauktae", "Fani", "Phailin", "Amphan") if k in hist]
    if cyclones:
        return "CYCLONE"
    if dramatic_rain:
        return "FLOOD"
    return "FLOOD"


def _low_lying(detail: Optional[str]) -> Optional[float]:
    if not detail:
        return None
    try:
        head = detail.split(",")[0]
        return float(head.replace("Elevation ", "").replace(" m", ""))
    except (ValueError, IndexError):
        return None


def _build_sources(factors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}
    for factor in factors:
        source = factor.get("source") or {}
        name = source.get("name") or factor["label"]
        if name not in seen:
            seen[name] = {"name": name, "status": source.get("status", "UNAVAILABLE")}
        if source.get("reference") and not seen[name].get("reference"):
            seen[name]["reference"] = source["reference"]
        if source.get("updated_at") and not seen[name].get("updated_at"):
            seen[name]["updated_at"] = source["updated_at"]
    return list(seen.values())


class RiskAssessmentService:
    def __init__(self, model_registry: Optional[ModelRegistry] = None) -> None:
        self._weather = WeatherService()
        self._rainfall = RainfallDataService()
        self._flood = FloodDataService()
        self._terrain = TerrainService()
        self._model = model_registry or ModelRegistry()
        self._cache = TTLCache(600)

    def assess(
        self,
        db: Session,
        latitude: float,
        longitude: float,
        *,
        place_label: Optional[str] = None,
        state: Optional[str] = None,
        district: Optional[str] = None,
        village: Optional[str] = None,
        field_reports: Optional[List[Dict[str, Any]]] = None,
        historical_month: Optional[Dict[str, Any]] = None,
        force_recompute: bool = False,
    ) -> Dict[str, Any]:
        cache_key = f"risk:{round(latitude, 2)}:{round(longitude, 2)}"
        if not force_recompute:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        weather = self._weather.get_weather(latitude, longitude)
        rainfall = self._rainfall.get_rainfall(latitude, longitude)
        flood = self._flood.get_flood_risk(latitude, longitude)
        terrain = self._terrain.get_terrain(latitude, longitude)

        events_payload = get_disaster_events_near(
            db, latitude, longitude, radius_km=config.HISTORICAL_EVENT_RADIUS_KM
        )

        factors: List[Dict[str, Any]] = [
            _rainfall_score(weather, rainfall, historical_month),
            _water_score(flood),
            _elevation_score(terrain),
            _historical_score(events_payload),
            _proximity_score(events_payload),
            _field_damage_score(field_reports, latitude, longitude),
            _lulc_score(latitude, longitude),
            _geoid_score(),
        ]

        available = [f for f in factors if f["impact"] != "NOT_AVAILABLE"]
        weight_sum = sum(f["weight"] for f in available)
        score = None
        if available and weight_sum > 0:
            score = sum(f["score"] * f["weight"] for f in available if f["score"] is not None) / weight_sum
        score = (round(max(0.0, min(100.0, score)), 1)) if score is not None else None

        band = band_for(score) if score is not None else {"band": "UNKNOWN", "level": "UNKNOWN"}

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        features = {
            **{f["key"]: (f["score"] or 0.0) for f in factors},
            "lat": latitude, "lon": longitude,
            "_input_timestamp": now,
        }

        model = self._model.predict(features)
        mode = self._model.mode
        model_score = model.get("risk_score")
        final_score = score
        model_status = model.get("model_status") or "RULE_BASED"
        if mode == "ml" and model_score is not None:
            final_score = round(float(model_score), 1)
            band = band_for(final_score)
        elif mode == "hybrid" and model_score is not None:
            model_status = f"{model_status} (attached)"

        payload = {
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "place_label": place_label,
            "state": state,
            "district": district,
            "village": village,
            "risk_score": final_score if final_score is not None else None,
            "risk_band": band["band"],
            "risk_level": band["level"],
            "assessment_mode": mode,
            "model_version": model.get("model_version"),
            "model_status": model_status,
            "prediction_timestamp": model.get("prediction_timestamp"),
            "input_data_timestamp": model.get("input_data_timestamp"),
            "factors": [{
                "key": f["key"], "label": f["label"], "score": f.get("score"),
                "weight": f["weight"], "impact": f["impact"], "detail": f.get("detail"),
                "source": f.get("source"),
            } for f in factors],
            "sources": _build_sources(factors),
            "disaster_type": _infer_disaster_type(factors) if score is not None else None,
            "computed_at": now,
            "caveat": (
                "Predictive scores are model-based susceptibility estimates for "
                "decision support and are never official notifications."
            ),
        }
        self._cache.set(cache_key, payload)
        return payload


risk_assessment_service = RiskAssessmentService()