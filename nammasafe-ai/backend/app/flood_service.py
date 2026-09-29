"""Flood / hydrological risk service with a Copernicus GloFAS provider.

GloFAS (Copernicus Emergency Management Service) is served through the CDS as a
*job-based* API: you request a dataset for a region, wait for the job, then
download the resulting NetCDF. There is no simple point lookup endpoint, so this
provider:

  1. Looks for a downloaded forecast dataset in config.GLOPAS_DATA_DIR
     (see backend/scripts/fetch_glofas_data.py for the CDS fetch helper).
  2. Lazy-imports netCDF4 to extract river discharge near a coordinate.
  3. Returns a clearly-labelled payload.

Status contract:
  NOT_CONFIGURED -> no cached dataset / credentials absent (operator action needed)
  FORECAST       -> real CEMS GloFAS forecast discharge extracted for the point
  UNAVAILABLE    -> dataset present but unreadable (e.g. netCDF4 missing)
"""

from __future__ import annotations

import glob
import math
import os
import time
from typing import Any, Dict, List, Optional

from app import config
from app.cache import TTLCache


def _estimate_grid_step(lats: Any, lons: Any) -> float:
    try:
        if len(lats) > 1 and len(lons) > 1:
            dlat = abs(float(lats[1]) - float(lats[0]))
            dlng = abs(float(lons[1]) - float(lons[0]))
            return max(dlat, dlng)
    except (TypeError, IndexError, ValueError):
        pass
    return 0.1


def find_nearest_cell(lats: Any, lons: Any, latitude: float, longitude: float) -> tuple:
    """Return (row, col) of the grid cell nearest a lat/lng point."""
    step = _estimate_grid_step(lats, lons)
    if step <= 0.0:
        return 0, 0
    row = min(range(max(0, len(lats) - 1)), key=lambda i: abs(float(lats[i]) - latitude))
    col = min(range(max(0, len(lons) - 1)), key=lambda i: abs(float(lons[i]) - longitude))
    return row, col


def _discharge_band(discharge: float, low: Optional[float], high: Optional[float]) -> str:
    if low is None or high is None or high <= low:
        return "UNKNOWN"
    if discharge >= high:
        return "EXTREME"
    if discharge >= low:
        return "ELEVATED"
    return "NORMAL"


class CopernicusGloFASProvider:
    name = "Copernicus GloFAS via CDS"

    def _dataset_path(self) -> Optional[str]:
        explicit = (config.GLOFAS_DATASET_PATH or "").strip()
        if explicit and os.path.isfile(explicit):
            return explicit
        data_dir = config.GLOPAS_DATA_DIR
        if not data_dir or not os.path.isdir(data_dir):
            return None
        matches = sorted(glob.glob(os.path.join(data_dir, "*.nc")))
        return matches[0] if matches else None

    def fetch(self, latitude: float, longitude: float) -> Dict[str, Any]:
        dataset_path = self._dataset_path()
        if not dataset_path:
            return {
                "data_status": "NOT_CONFIGURED",
                "data_source": self.name,
                "reason": (
                    "No GloFAS dataset configured. Download a CEMS GloFAS forecast "
                    "with backend/scripts/fetch_glofas_data.py and set GLOFAS_DATASET_PATH "
                    "(or GLOPAS_DATA_DIR) to it."
                ),
            }

        try:
            import netCDF4  # type: ignore  # optional dependency
        except ImportError:
            return {
                "data_status": "UNAVAILABLE",
                "data_source": self.name,
                "reason": "netCDF4 package is not installed in the backend environment.",
            }

        return self._read_forecast(netCDF4, dataset_path, latitude, longitude)

    def _read_forecast(
        self,
        netCDF4: Any,
        dataset_path: str,
        latitude: float,
        longitude: float,
    ) -> Dict[str, Any]:
        """Extract the GloFAS discharge forecast for the nearest grid cell.

        Split from ``fetch`` so tests can exercise the FORECAST envelope without
        a real NetCDF file (netCDF4 is an optional runtime dependency).
        """
        try:
            with netCDF4.Dataset(dataset_path, "r") as nc:
                variables = nc.variables
                lat_name = next((v for v in ("latitude", "lat", "y") if v in variables), None)
                lon_name = next((v for v in ("longitude", "lon", "x") if v in variables), None)
                if lat_name is None or lon_name is None:
                    raise ValueError("GloFAS dataset missing latitude/longitude variables")

                lats = variables[lat_name][:]
                lons = variables[lon_name][:]
                row, col = find_nearest_cell(lats, lons, latitude, longitude)
                cell_lat = float(lats[row])
                cell_lon = float(lons[col])

                dis_var_name = next(
                    (v for v in ("dis24", "dis00", "dis") if v in variables), None
                )
                time_var_name = "time" if "time" in variables else None
                if dis_var_name is None:
                    raise ValueError("GloFAS dataset missing discharge variable")

                times = variables[time_var_name][:] if time_var_name else []
                first_slice = slice(0, 1)
                current = float(variables[dis_var_name][first_slice, row, col])
                forecast_hours = max(1, len(times))

                series = None
                try:
                    series = [float(v) for v in variables[dis_var_name][:, row, col]]
                except Exception:
                    series = None

                low = high = None
                if series:
                    sorted_series = sorted(series)
                    low = _percentile(sorted_series, 85.0)
                    high = _percentile(sorted_series, 99.0)

                issue_time, valid_time, lead_time_hours = None, None, None
                if time_var_name:
                    issue_time, valid_time = _decode_time_horizon(variables[time_var_name])
                    if issue_time and valid_time:
                        try:
                            from datetime import datetime
                            lead_time_hours = (
                                datetime.fromisoformat(valid_time)
                                - datetime.fromisoformat(issue_time)
                            ).total_seconds() // 3600
                        except (TypeError, ValueError):
                            lead_time_hours = None

                return {
                    "data_status": "FORECAST",
                    "data_source": self.name,
                    "latitude": round(cell_lat, 5),
                    "longitude": round(cell_lon, 5),
                    "river_discharge_m3s": round(current, 2),
                    "threshold_m3s": round(low, 2) if low is not None else None,
                    "discharge_band": _discharge_band(current, low, high),
                    "lead_time_hours": lead_time_hours,
                    "issue_time": issue_time,
                    "valid_time": valid_time,
                    "forecast_hours": forecast_hours,
                    "dataset": os.path.basename(dataset_path),
                    "computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "assumption": "Band and threshold derived from the percentiles of the cached forecast dataset (85th/99th).",
                }
        except Exception as exc:  # pragma: no cover - dataset-specific failures
            return {
                "data_status": "UNAVAILABLE",
                "data_source": self.name,
                "reason": f"Could not read GloFAS dataset: {exc}",
            }


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(math.ceil(pct / 100.0 * len(ordered))) - 1)
    return float(ordered[max(0, index)])


def _decode_time_horizon(time_var: Any) -> tuple:
    """Return (issue_time, valid_time) ISO strings for a NetCDF time variable.

    Returns (None, None) when the units cannot be decoded (the runner may
    lack netCDF4/cftime), keeping the forecast result in a FORECAST but the
    horizon deliberately unknown rather than fabricated.
    """
    try:
        try:
            from cftime import num2date  # type: ignore
        except ImportError:
            num2date = None
        if num2date is None:
            try:
                from netCDF4 import num2date  # type: ignore
            except ImportError:
                return None, None
        units = getattr(time_var, "units", None)
        if not units:
            return None, None
        calendar = getattr(time_var, "calendar", "standard")
        dates = num2date(time_var[:], units=units, calendar=calendar)
        if not len(dates):
            return None, None
        return dates[0].isoformat(), dates[-1].isoformat()
    except Exception:
        return None, None


class FloodDataService:
    def __init__(self) -> None:
        self._provider = CopernicusGloFASProvider()
        self._cache = TTLCache(config.FLOOD_CACHE_TTL_SEC)

    def get_flood_risk(self, latitude: float, longitude: float) -> Dict[str, Any]:
        cache_key = f"flood:{round(latitude, 3)}:{round(longitude, 3)}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        payload = self._provider.fetch(latitude, longitude)
        payload.setdefault("latitude", round(float(latitude), 6))
        payload.setdefault("longitude", round(float(longitude), 6))
        self._cache.set(cache_key, payload)
        return payload


flood_service = FloodDataService()