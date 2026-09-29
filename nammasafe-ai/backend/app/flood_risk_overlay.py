"""Weather & hazard map flood-risk overlay.

A transparent, rule-based hazard heuristic computed from REAL upstream inputs —
it never fabricates values. Each contributing factor is named on the payload so
operators can audit the derivation weights.

Inputs (per grid cell, same real pipelines the rest of the app uses):
  * weather_service.get_weather(...)      — precipitation / storm code (LIVE)
  * terrain_service.get_terrain(...)      — SRTM elevation + slope (LIVE/CACHED)
  * rainfall_service.get_rainfall(...)    — GPM IMERG (LIVE/CACHED) when configured

Factor weights (documented, single source of truth):
  precipitation_hourly  0.35  min(1, mm/50)            — wet ground from now-hour rain
  storm                 0.25  1.0 if storm weather code — convective flash-flood driver
  elevation_exposure    0.25  flat/low ground favours ponding (1 at <=5 m → 0 at 1500 m)
  slope_drainage        0.15  low slope drains slowly  (1 at <=2% → 0 at 15%)

score = 100 * weighted factors. Risk bands: <25 LOW, <50 MODERATE, <75 HIGH, else EXTREME.
data_status is CALCULATED when real inputs fed the rule (never fabricated), else
UNAVAILABLE with an honest reason.
"""

from __future__ import annotations

import time
from calendar import monthrange
from typing import Any, Dict, List, Optional

from app import historical_weather
from app import terrain_service
from app.weather_service import weather_service as weather_provider

RISK_WEIGHTS = {
    "precipitation_hourly": 0.35,
    "storm": 0.25,
    "elevation_exposure": 0.25,
    "slope_drainage": 0.15,
}

STORM_CODES = (61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99)


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value if value is not None else 0.0))


def _elevation_exposure(elevation_m: Optional[float]) -> float:
    if elevation_m is None:
        return 0.0
    if elevation_m <= 5.0:
        return 1.0
    if elevation_m >= 1500.0:
        return 0.0
    return 1.0 - (elevation_m - 5.0) / (1500.0 - 5.0)


def _slope_drainage(slope_percent: Optional[float]) -> float:
    if slope_percent is None:
        return 0.0
    if slope_percent <= 2.0:
        return 1.0
    if slope_percent >= 15.0:
        return 0.0
    return 1.0 - (slope_percent - 2.0) / (15.0 - 2.0)


def _risk_level(score: float) -> str:
    if score < 25.0:
        return "LOW"
    if score < 50.0:
        return "MODERATE"
    if score < 75.0:
        return "HIGH"
    return "EXTREME"


def _cell_factors(latitude: float, longitude: float) -> Dict[str, Any]:
    factors: Dict[str, Any] = {"used": [], "reasons": []}

    weather = weather_provider.get_weather(latitude, longitude, days=1)
    weather_status = weather.get("data_status")
    current = weather.get("current") or {}
    precip_mm = current.get("precipitation_mm")
    code = current.get("weather_code")
    if weather_status in ("LIVE", "FORECAST") and isinstance(precip_mm, (int, float)):
        factors["precipitation_hourly"] = _clamp01(precip_mm / 50.0)
        factors["used"].append(f"precipitation_hourly ({precip_mm} mm/h)")
    else:
        factors["precipitation_hourly"] = 0.0

    is_storm = isinstance(code, (int, float)) and int(code) in STORM_CODES
    storm_status = weather_status if is_storm else None
    if is_storm:
        factors["storm"] = 1.0
        factors["used"].append("storm (weather code)")
    else:
        factors["storm"] = 0.0

    terrain = terrain_service.terrain_service.get_terrain(latitude, longitude)
    terrain_status = terrain.get("data_status")
    elev = terrain.get("elevation_m")
    slope = terrain.get("slope_percent")
    if terrain_status in ("LIVE", "CACHED") and isinstance(elev, (int, float)):
        factors["elevation_exposure"] = _elevation_exposure(elev)
        factors["used"].append(f"elevation ({elev} m)")
    else:
        factors["elevation_exposure"] = 0.0
    if terrain_status in ("LIVE", "CACHED") and isinstance(slope, (int, float)):
        factors["slope_drainage"] = _slope_drainage(slope)
        factors["used"].append(f"slope ({slope}%)")
    else:
        factors["slope_drainage"] = 0.0

    if not factors["used"]:
        reasons = [
            str(r) for r in [weather.get("reason"), terrain.get("reason")]
            if r
        ]
        factors["reasons"] = reasons or ["No live upstream inputs available for this cell."]
    factors["_statuses"] = {
        "weather": weather_status or "UNAVAILABLE",
        "terrain": terrain_status or "UNAVAILABLE",
        "precip_mm": precip_mm,
        "weather_code": code,
    }
    return factors


def get_flood_risk_grid(
    north: float,
    south: float,
    east: float,
    west: float,
    step: float = 0.05,
    max_points: int = 300,
    *,
    year: Optional[int] = None,
    month: Optional[int] = None,
    db: Optional[Any] = None,
) -> Dict[str, Any]:
    if year is not None:
        return _historical_flood_grid(north, south, east, west, step, max_points, year, month or 0, db)
    n_int = int(round(north / step))
    s_int = int(round(south / step))
    e_int = int(round(east / step))
    w_int = int(round(west / step))
    exported: List[Dict[str, Any]] = []
    any_input = False
    any_unavailable = False
    valid_time: Optional[str] = None

    rows_needed = n_int - s_int + 1
    col_step = max(1, int((e_int - w_int + 1) / max(1, max_points // rows_needed)))
    cols = [round(w_int * step, 6) + c * step for c in range(0, e_int - w_int + 1, col_step)]

    for i, lat in enumerate([round(n_int * step, 6) - i * step for i in range(n_int - s_int + 1)]):
        if len(exported) >= max_points:
            break
        for lng in cols:
            if len(exported) >= max_points:
                break
            f = _cell_factors(lat, lng)
            score = round(100.0 * sum(
                RISK_WEIGHTS[k] * f.get(k, 0.0) for k in RISK_WEIGHTS
            ), 1)
            if f["reasons"]:
                any_unavailable = True
                exported.append(
                    {
                        "latitude": round(lat, 6),
                        "longitude": round(lng, 6),
                        "risk_score": None,
                        "risk_level": None,
                        "contributing_factors": f["used"],
                        "data_status": "UNAVAILABLE",
                        "reason": f["reasons"][0],
                    }
                )
                continue
            any_input = True
            if f["_statuses"]["weather"] in ("LIVE", "FORECAST"):
                valid_time = _utc_now()
            exported.append(
                {
                    "latitude": round(lat, 6),
                    "longitude": round(lng, 6),
                    "risk_score": score,
                    "risk_level": _risk_level(score),
                    "contributing_factors": f["used"],
                    "data_status": "CALCULATED",
                    "reason": None,
                }
            )

    if not exported:
        return {
            "points": [],
            "data_status": "UNAVAILABLE",
            "data_source": "Transparent rule-based overlay (weather + SRTM terrain)",
            "reason": "No cells could be sampled in the requested window.",
            "valid_time": valid_time,
        }

    status = "CALCULATED" if any_input else ("UNAVAILABLE" if any_unavailable else "UNAVAILABLE")
    return {
        "points": exported,
        "data_status": status,
        "data_source": "Transparent rule-based overlay (weather + SRTM terrain)",
        "weights": RISK_WEIGHTS,
        "reason": None if any_input else (exported[0].get("reason") if exported else None),
        "valid_time": valid_time,
    }


def _historical_flood_grid(
    north: float,
    south: float,
    east: float,
    west: float,
    step: float,
    max_points: int,
    year: int,
    month: int,
    db: Optional[Any],
) -> Dict[str, Any]:
    """Historical flood-susceptibility overlay for a completed month:
      * precipitation  = ERA5 monthly total (mm) for the month     (HISTORICAL)
      * storm          = ERA5 thunderstorm-day count for the month (HISTORICAL)
      * terrain        = real SRTM elevation + slope                (LIVE/CACHED)

    The rule language stays susceptibility ("elevated risk"), never a claim that
    flooding *will* occur, and every outcome is labelled from HISTORICAL sources
    with the year/period in the contributing-factors text.
    """
    now = _utc_now()
    period_label = f"{int(year):04d}-{int(month):02d}"
    month_days = monthrange(int(year), int(month))[1]

    terrain_grid = terrain_service.terrain_service.get_terrain_grid(
        north, south, east, west, step=step, max_points=max_points
    )
    terrain_by_cell = {
        (round(p["latitude"], 5), round(p["longitude"], 5)): p
        for p in terrain_grid.get("points", [])
    }
    precip_grid = historical_weather.historical_weather.fetch_grid(
        north, south, east, west, step=step, max_points=max_points,
        variable="precipitation", year=int(year), month=int(month), session=db,
    )
    storm_grid = historical_weather.historical_weather.fetch_grid(
        north, south, east, west, step=step, max_points=max_points,
        variable="storm_indicator", year=int(year), month=int(month), session=db,
    )
    precip_by_cell = {
        (round(p["latitude"], 5), round(p["longitude"], 5)): p.get("value")
        for p in precip_grid.get("points", [])
    }
    storm_by_cell = {
        (round(p["latitude"], 5), round(p["longitude"], 5)): p.get("value")
        for p in storm_grid.get("points", [])
    }

    exported: List[Dict[str, Any]] = []
    any_input = False
    any_unavailable = False
    for (lat, lng), precip_mm in precip_by_cell.items():
        if len(exported) >= int(max_points):
            break
        factors: Dict[str, Any] = {"used": [], "reasons": []}
        terrain = terrain_by_cell.get((lat, lng), {})

        if precip_mm is not None:
            factors["precipitation_hourly"] = _clamp01(float(precip_mm) / 500.0)
            factors["used"].append(f"historical_precipitation ({precip_mm} mm / {period_label}) [ERA5]")
        else:
            factors["precipitation_hourly"] = 0.0
        storm_days = storm_by_cell.get((lat, lng))
        if storm_days is not None and month_days:
            # >=5 thunderstorm days in the month saturates the storm driver.
            factors["storm"] = _clamp01(float(storm_days) / 5.0)
            factors["used"].append(
                f"historical_storm_days ({storm_days}/{month_days}) [ERA5]"
            )
        else:
            factors["storm"] = 0.0

        elev = terrain.get("elevation_m")
        slope = terrain.get("slope_percent")
        if isinstance(elev, (int, float)):
            factors["elevation_exposure"] = _elevation_exposure(elev)
            factors["used"].append(f"elevation ({elev} m) [SRTM]")
        else:
            factors["elevation_exposure"] = 0.0
        if isinstance(slope, (int, float)):
            factors["slope_drainage"] = _slope_drainage(slope)
            factors["used"].append(f"slope ({slope}%) [SRTM]")
        else:
            factors["slope_drainage"] = 0.0

        if not factors["used"]:
            any_unavailable = True
            exported.append(
                {
                    "latitude": lat,
                    "longitude": lng,
                    "risk_score": None,
                    "risk_level": None,
                    "contributing_factors": [],
                    "data_status": "UNAVAILABLE",
                    "reason": f"No historical precipitation (ERA5) or SRTM terrain input for {period_label}.",
                }
            )
            continue

        score = round(100.0 * sum(
            RISK_WEIGHTS[k] * factors.get(k, 0.0) for k in RISK_WEIGHTS
        ), 1)
        any_input = True
        exported.append(
            {
                "latitude": lat,
                "longitude": lng,
                "risk_score": score,
                "risk_level": _risk_level(score),
                "contributing_factors": factors["used"],
                "data_status": "CALCULATED",
                "reason": None,
            }
        )

    if not exported:
        return {
            "points": [],
            "data_status": "UNAVAILABLE",
            "data_source": "Historical rule-based overlay (ERA5 + SRTM terrain)",
            "reason": "No cells could be sampled for the requested historical period.",
            "valid_time": now,
        }
    return {
        "points": exported,
        "data_status": "CALCULATED" if any_input else "UNAVAILABLE",
        "data_source": "Historical rule-based overlay (ERA5 + SRTM terrain)",
        "weights": RISK_WEIGHTS,
        "reason": None if any_input else (exported[0].get("reason") if exported else None),
        "valid_time": f"{period_label} (completed month, HISTORICAL)",
    }