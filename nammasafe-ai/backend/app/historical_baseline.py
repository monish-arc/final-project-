"""
Historical baseline calculation for Kerala districts.

Pure functions (mirroring the risk_engine.py style) so the math is directly
unit-testable without a database.  A "baseline" is the statistical summary of
all imported previous-year observations for a district + data_year and is used
as the reference point that a future live rainfall feed will be compared
against.

Quality rules
-------------
- Percentiles (median / p90 / p95) are only published when there are at least
  MIN_PERCENTILE_OBS observations; otherwise they are omitted so that we never
  show misleading statistics.
- The quality grade is derived from how much of the observation calendar is
  covered for the dataset year:
      GOOD          >= 90% of calendar days observed
      LIMITED       >= 60% of calendar days observed
      INSUFFICIENT   otherwise (or zero observations)

No interpolation is ever performed — missing dates are reported, never filled.
"""

import calendar
import statistics
from datetime import date
from typing import Any, Dict, List, Optional

from app.config import HISTORICAL_MIN_PERCENTILE_OBS

DEFAULT_MIN_PERCENTILE_OBS = HISTORICAL_MIN_PERCENTILE_OBS

# Quality thresholds (fraction of calendar days covered by observations).
QUALITY_GOOD_COVERAGE = 0.90
QUALITY_LIMITED_COVERAGE = 0.60

# Compare/severity thresholds are multiples of the baseline average.
SEVERITY_THRESHOLDS: List[tuple] = [
    (2.0, "EXTREME"),
    (1.5, "HIGH"),
    (1.2, "ELEVATED"),
]

CURRENT_YEAR = date.today().year


def _days_in_year(year: int) -> int:
    return 366 if calendar.isleap(year) else 365


def _fmt_date(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def size_bucket(count: int, data_year: Optional[int] = None) -> str:
    """
    Data-coverage grade for `count` observations in a (year-long) dataset.
    Exists as a separate pure helper so tests can check the boundaries.
    """
    if count <= 0:
        return "INSUFFICIENT"
    days = _days_in_year(data_year if data_year else CURRENT_YEAR)
    coverage = count / days
    if coverage >= QUALITY_GOOD_COVERAGE:
        return "GOOD"
    if coverage >= QUALITY_LIMITED_COVERAGE:
        return "LIMITED"
    return "INSUFFICIENT"


def grade_quality(count: int, data_year: Optional[int] = None) -> Dict[str, Any]:
    """
    Quality indicator for a district dataset.

    Returns {grade, coverage_percent, reason}.  The reason explicitly describes
    missing/partial coverage — nothing is silently imputed.
    """
    if count <= 0:
        return {
            "grade": "INSUFFICIENT",
            "coverage_percent": 0.0,
            "reason": "No historical observations available for this district/year.",
        }
    days = _days_in_year(data_year if data_year else CURRENT_YEAR)
    coverage = count / days
    if coverage >= QUALITY_GOOD_COVERAGE:
        return {
            "grade": "GOOD",
            "coverage_percent": round(coverage * 100, 1),
            "reason": "Observations cover at least 90% of the dataset year calendar.",
        }
    if coverage >= QUALITY_LIMITED_COVERAGE:
        return {
            "grade": "LIMITED",
            "coverage_percent": round(coverage * 100, 1),
            "reason": f"Partial-year coverage ({count}/{days} expected days). Missing dates are not interpolated.",
        }
    return {
        "grade": "INSUFFICIENT",
        "coverage_percent": round(coverage * 100, 1),
        "reason": f"Coverage too low ({count}/{days} expected days) for a reliable baseline.",
    }


def compute_baseline(records: List[Dict[str, Any]], data_year: int) -> Dict[str, Any]:
    """
    Build the statistical baseline for a list of observation dicts.

    Each record requires at least: rainfall_mm (float), observation_date
    (date or ISO string).  Returns the baseline portion of the API response;
    district metadata / status labels are attached by the caller.
    """
    if not records:
        quality = grade_quality(0, data_year)
        return {
            "data_year": data_year,
            "total_rainfall_mm": 0.0,
            "average_rainfall_mm": 0.0,
            "max_rainfall_mm": 0.0,
            "min_rainfall_mm": 0.0,
            "observation_count": 0,
            "date_range": {"first": None, "last": None},
            "median_rainfall_mm": None,
            "p90_rainfall_mm": None,
            "p95_rainfall_mm": None,
            "quality": quality,
            "status": "NOT CONFIGURED",
        }

    values = [float(r["rainfall_mm"]) for r in records]
    dates = [_fmt_date(r["observation_date"]) for r in records]
    count = len(values)

    baseline: Dict[str, Any] = {
        "data_year": data_year,
        "total_rainfall_mm": round(sum(values), 2),
        "average_rainfall_mm": round(sum(values) / count, 2),
        "max_rainfall_mm": round(max(values), 2),
        "min_rainfall_mm": round(min(values), 2),
        "observation_count": count,
        "date_range": {"first": min(dates), "last": max(dates)},
        "median_rainfall_mm": None,
        "p90_rainfall_mm": None,
        "p95_rainfall_mm": None,
        "quality": grade_quality(count, data_year),
        "status": "HISTORICAL",
    }

    if count >= DEFAULT_MIN_PERCENTILE_OBS:
        baseline["median_rainfall_mm"] = round(statistics.median(values), 2)
        sorted_values = sorted(values)
        baseline["p90_rainfall_mm"] = round(percentile(sorted_values, 90), 2)
        baseline["p95_rainfall_mm"] = round(percentile(sorted_values, 95), 2)

    return baseline


def percentile(sorted_values: List[float], pct: float) -> float:
    """Linear-interpolation percentile (method R-7, as used by numpy by default)."""
    if not sorted_values:
        return 0.0
    if pct <= 0:
        return sorted_values[0]
    if pct >= 100:
        return sorted_values[-1]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lower = int(rank)
    upper = lower + 1
    frac = rank - lower
    if upper >= len(sorted_values):
        return sorted_values[lower]
    return sorted_values[lower] * (1 - frac) + sorted_values[upper] * frac


def severity_from_ratio(ratio: Optional[float]) -> str:
    """Label the departure of an observation relative to the baseline average."""
    if ratio is None:
        return "NORMAL"
    for threshold, label in SEVERITY_THRESHOLDS:
        if ratio >= threshold:
            return label
    return "NORMAL"


def compare_observation(
    rainfall_mm: float,
    baseline: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Compare a current/live observation against a historical baseline.

    The observation is expected to come from an external live feed — this
    function only *computes*: it never fabricates a current value.  Callers that
    have no live source must instead report live_data_status="NOT CONFIGURED".
    """
    average = float(baseline.get("average_rainfall_mm") or 0.0)
    count = int(baseline.get("observation_count") or 0)

    if count == 0 or average <= 0:
        return {
            "live_configured": False,
            "live_data_status": "NOT CONFIGURED",
            "baseline_average": None,
            "anomaly_mm": None,
            "percent_difference": None,
            "severity": "NORMAL",
            "baseline_status": baseline.get("status", "NOT CONFIGURED"),
        }

    anomaly = rainfall_mm - average
    percent_diff = (anomaly / average) * 100.0
    ratio = rainfall_mm / average

    return {
        "live_configured": False,
        "live_data_status": "NOT CONFIGURED",
        "baseline_average": round(average, 2),
        "anomaly_mm": round(anomaly, 2),
        "percent_difference": round(percent_diff, 2),
        "severity": severity_from_ratio(ratio),
        "baseline_status": "HISTORICAL",
    }