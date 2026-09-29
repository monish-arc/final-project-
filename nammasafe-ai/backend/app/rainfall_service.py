"""Rainfall service backed by NASA GPM IMERG through the GES DISC archive.

IMERG is distributed as *bulk* HDF5/NetCDF tiles, not a point REST endpoint.
GPM_MODE=off (the default) keeps this service in a clearly-labelled
NOT_CONFIGURED state until an IMERG tile is ingested into GPM_DATA_DIR by an
operator (see backend/scripts/fetch_gpm_data.py) and the EARTHDATA credentials
are configured.

Status contract:
  NOT_CONFIGURED -> GPM_MODE=off or no data dir / credentials configured
  LIVE           -> precipitation extracted from an ingested IMERG tile
  UNAVAILABLE    -> tile present but unreadable (e.g. h5py missing / bad file)
"""

from __future__ import annotations

import glob
import math
import os
import time
from typing import Any, Dict, List, Optional

from app import config
from app.cache import TTLCache

_HOUR_NAMES = ("precipitationCal", "precipitation", "precipitationUncal")


class NasaGpmProvider:
    name = "NASA GPM IMERG (GES DISC)"

    def _configured(self) -> bool:
        if config.GPM_MODE != "on":
            return False
        if not config.GPM_DATA_DIR or not os.path.isdir(config.GPM_DATA_DIR):
            return False
        return bool(self._tile_path())

    def _tile_path(self) -> Optional[str]:
        if not config.GPM_DATA_DIR:
            return None
        matches = sorted(
            glob.glob(os.path.join(config.GPM_DATA_DIR, "*.HDF5"))
            + glob.glob(os.path.join(config.GPM_DATA_DIR, "*.h5"))
            + glob.glob(os.path.join(config.GPM_DATA_DIR, "*.nc"))
        )
        return matches[0] if matches else None

    def fetch(self, latitude: float, longitude: float) -> Dict[str, Any]:
        if not self._configured():
            return {
                "data_status": "NOT_CONFIGURED",
                "data_source": self.name,
                "reason": (
                    "GPM_MODE=off or no IMERG tile in GPM_DATA_DIR. "
                    "See backend/scripts/fetch_gpm_data.py to ingest a tile."
                ),
            }

        try:
            import h5py  # type: ignore  # optional dependency
        except ImportError:
            return {
                "data_status": "UNAVAILABLE",
                "data_source": self.name,
                "reason": "h5py package is not installed in the backend environment.",
            }

        tile = self._tile_path()
        try:
            import numpy as np  # type: ignore  # comes with h5py

            with h5py.File(tile, "r") as handle:
                root = handle["Grid"] if "Grid" in handle else handle
                dataset_name = next(
                    (name for name in _HOUR_NAMES if name in root), None
                )
                if dataset_name is None:
                    return {
                        "data_status": "UNAVAILABLE",
                        "data_source": self.name,
                        "reason": "IMERG tile missing a precipitation dataset.",
                    }

                dataset = root[dataset_name]
                value: Optional[float] = None
                if "lat" in root and "lon" in root:
                    lat_array = np.asarray(root["lat"][:], dtype=float)
                    lon_array = np.asarray(root["lon"][:], dtype=float)
                    grid = dataset[0] if dataset.ndim == 3 else dataset[:]
                    if grid.shape[-1] == lat_array.shape[0] and grid.shape[-2] == lon_array.shape[0]:
                        row = int(np.abs(lat_array - float(latitude)).argmin())
                        col = int(np.abs(lon_array - float(longitude)).argmin())
                        value = float(grid[col, row])
                    else:
                        row = int(np.abs(lat_array - float(latitude)).argmin())
                        col = int(np.abs(lon_array - float(longitude)).argmin())
                        value = float(grid[row, col])
                else:
                    attrs = dict(dataset.attrs)

                    def _num(keys: list) -> Optional[float]:
                        for key in keys:
                            values = attrs.get(key)
                            if values is None:
                                continue
                            if isinstance(values, (list, tuple)):
                                return float(values[0])
                            try:
                                return float(values)
                            except (TypeError, ValueError):
                                continue
                        return None

                    lat_mid = _num(["GridLat0", "Latitude"])
                    lon_mid = _num(["GridLon0", "Longitude"])
                    span = _num(["SpanOfGrid"]) or 0.1
                    if lat_mid is None or lon_mid is None:
                        return {
                            "data_status": "UNAVAILABLE",
                            "data_source": self.name,
                            "reason": "IMERG tile missing grid-geometry attributes.",
                        }
                    grid = dataset[0, :, :] if dataset.ndim == 3 else dataset[:, :]
                    rows, cols = grid.shape
                    row = max(0.0, min(rows - 1, (lat_mid - latitude) / span))
                    col = max(0.0, min(cols - 1, (longitude - lon_mid) / span))
                    value = float(grid[int(round(row)), int(round(col))])

                if value is not None and value < -100.0:
                    value = 0.0
        except Exception as exc:  # pragma: no cover - tile-format specific
            return {
                "data_status": "UNAVAILABLE",
                "data_source": self.name,
                "reason": f"Could not read IMERG tile: {exc}",
            }

        return {
            "data_status": "LIVE",
            "data_source": self.name,
            "latitude": round(float(latitude), 6),
            "longitude": round(float(longitude), 6),
            "precipitation_mm_hour": round(float(value), 2),
            "dataset": os.path.basename(tile),
            "tile_time": None,
            "computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "assumption": "IMERG precipitation estimate; value is the nearest grid cell.",
        }

    def sample_grid(
        self,
        north: float,
        south: float,
        east: float,
        west: float,
        step: float,
        max_points: int,
    ) -> Optional[List[Dict[str, Any]]]:
        if not self._configured():
            return None
        try:
            import h5py  # type: ignore
            import numpy as np  # type: ignore
        except ImportError:
            return None

        tile = self._tile_path()
        if tile is None:
            return None

        try:
            with h5py.File(tile, "r") as handle:
                root = handle["Grid"] if "Grid" in handle else handle
                dataset_name = next(
                    (name for name in _HOUR_NAMES if name in root), None
                )
                if dataset_name is None:
                    return None

                dataset = root[dataset_name]
                if "lat" in root and "lon" in root:
                    lat_array = np.asarray(root["lat"][:], dtype=float)
                    lon_array = np.asarray(root["lon"][:], dtype=float)
                    grid = dataset[0] if dataset.ndim == 3 else dataset[:]
                    v07 = (
                        grid.shape[-1] == lat_array.shape[0]
                        and grid.shape[-2] == lon_array.shape[0]
                    )
                else:
                    attrs = dict(dataset.attrs)

                    def _num(keys: list) -> Optional[float]:
                        for key in keys:
                            values = attrs.get(key)
                            if values is None:
                                continue
                            if isinstance(values, (list, tuple)):
                                return float(values[0])
                            try:
                                return float(values)
                            except (TypeError, ValueError):
                                continue
                        return None

                    lat_mid = _num(["GridLat0", "Latitude"])
                    lon_mid = _num(["GridLon0", "Longitude"])
                    span = _num(["SpanOfGrid"]) or 0.1
                    if lat_mid is None or lon_mid is None:
                        return None
                    grid = dataset[0, :, :] if dataset.ndim == 3 else dataset[:, :]
                    v07 = False

                lat = north
                points: List[Dict[str, Any]] = []
                while lat >= south and len(points) < max_points:
                    lng = west
                    while lng <= east and len(points) < max_points:
                        if v07:
                            li = int(np.abs(lon_array - lng).argmin())
                            la = int(np.abs(lat_array - lat).argmin())
                            val = float(grid[li, la])
                        else:
                            row = max(0, min(grid.shape[0] - 1, (lat_mid - lat) / span))
                            col = max(0, min(grid.shape[1] - 1, (lng - lon_mid) / span))
                            val = float(grid[int(round(row)), int(round(col))])
                        if val < -100.0:
                            val = None
                        points.append({
                            "latitude": round(lat, 5),
                            "longitude": round(lng, 5),
                            "precipitation_mm_hour": round(val, 2) if val is not None else None,
                        })
                        lng += step
                    lat -= step
                return points
        except Exception:
            return None


class RainfallDataService:
    def __init__(self) -> None:
        self._provider = NasaGpmProvider()
        self._cache = TTLCache(config.RAINFALL_CACHE_TTL_SEC)

    def get_rainfall(self, latitude: float, longitude: float) -> Dict[str, Any]:
        cache_key = f"rainfall:{round(latitude, 3)}:{round(longitude, 3)}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        payload = self._provider.fetch(latitude, longitude)
        payload.setdefault("latitude", round(float(latitude), 6))
        payload.setdefault("longitude", round(float(longitude), 6))
        self._cache.set(cache_key, payload)
        return payload

    def get_grid_samples(
        self,
        north: float,
        south: float,
        east: float,
        west: float,
        step: float = 0.05,
        max_points: int = 400,
    ) -> Dict[str, Any]:
        bounds_key = f"{round(north, 3)}:{round(south, 3)}:{round(east, 3)}:{round(west, 3)}"
        cache_key = f"rainfall-grid:{bounds_key}:{step}:{max_points}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        points = self._provider.sample_grid(north, south, east, west, step, max_points)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if points is None:
            payload = {
                "data_status": "NOT_CONFIGURED",
                "data_source": self._provider.name,
                "dataset": None,
                "tile_time": None,
                "computed_at": now,
                "bounds": {"north": north, "south": south, "east": east, "west": west},
                "points": [],
                "assumption": "No IMERG tile ingested; enable GPM_MODE and run scripts/fetch_gpm_data.py.",
                "reason": (
                    "GPM_MODE=off or no IMERG tile in GPM_DATA_DIR. "
                    "See backend/scripts/fetch_gpm_data.py to ingest a tile."
                ),
            }
        else:
            payload = {
                "data_status": "LIVE",
                "data_source": self._provider.name,
                "dataset": os.path.basename(self._provider._tile_path() or ""),
                "tile_time": None,
                "computed_at": now,
                "bounds": {"north": north, "south": south, "east": east, "west": west},
                "points": points,
                "assumption": "IMERG precipitation estimate per 0.1° grid cell, sampled on request bounds.",
                "reason": None,
            }
        self._cache.set(cache_key, payload)
        return payload


rainfall_service = RainfallDataService()