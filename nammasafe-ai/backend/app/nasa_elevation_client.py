"""NASA Earthdata SRTM elevation client (primary terrain source).

Downloads the official NASA Shuttle Radar Topography Mission Global 1
arc-second Version 3 DEM (SRTMGL1.003) from the LP DAAC Earthdata Cloud
distribution node (https://doi.org/10.5067/MEASURES/SRTM/SRTMGL1.003).

Each 1-degree tile is a `.HGT` file (raw signed 16-bit big-endian samples,
row-major starting from the northern edge, no header, void = -32768) inside a
`.zip`, authenticated with the operator Earthdata Login bearer token as
`Authorization: Bearer <token>`. All fetching and math is server-side; the
token is never logged, cached in cookies, or exposed through the API.

Elevation is bilinearly interpolated from the native ~30 m grid. Slope uses a
real DEM 3x3 window (config.NASA_TERRAIN_SAMPLE_ARCSEC, default 3 arc-seconds
~ 90 m) via Horn's method so it reflects measured terrain — never a
fabricated estimate.
"""

from __future__ import annotations

import io
import math
import sys
import threading
import time
import zipfile
from array import array
from typing import Any, Dict, Optional, Tuple

from app import config
from app.cache import TTLCache
from app.http_client import HttpFetchError, http_get_bytes

VOID_VALUE = -32768

# Approximate metres per degree at the equator / latitude (WGS84).
_M_PER_DEG_LAT = 110574.0
_M_PER_DEG_LON_EQ = 111320.0

# NASA LP DAAC answers HTTP 429 when a token bursts past its rate limit. Park
# requests for a short module-local cooldown so terrain grids never hammer a
# throttled Earthdata distribution node into a sustained block.
_NASA_COOLDOWN_UNTIL = 0.0
_NASA_COOLDOWN_LOCK = threading.Lock()


def _nasa_in_cooldown() -> bool:
    with _NASA_COOLDOWN_LOCK:
        return time.monotonic() < _NASA_COOLDOWN_UNTIL


def _mark_nasa_cooldown(seconds: float) -> None:
    global _NASA_COOLDOWN_UNTIL
    with _NASA_COOLDOWN_LOCK:
        _NASA_COOLDOWN_UNTIL = time.monotonic() + max(1.0, float(seconds))


class NasaElevationError(HttpFetchError):
    """The NASA SRTM tile could not be downloaded or parsed (non-auth)."""


class NasaAuthError(NasaElevationError):
    """Earthdata bearer token missing or rejected by the provider."""


class NasaTileMissingError(NasaElevationError):
    """No SRTMGL1 tile exists for the requested coordinate (e.g. out of coverage)."""


def tile_name(latitude: float, longitude: float) -> str:
    """1-degree SRTMGL1 tile name for the lower-left corner (e.g. N30E079)."""
    if not (-90.0 <= latitude < 90.0 and -180.0 <= longitude < 180.0):
        raise NasaTileMissingError(f"Coordinate out of SRTM range: {latitude}, {longitude}")
    lat_i = math.floor(latitude)
    lon_i = math.floor(longitude)
    ns = "N" if lat_i >= 0 else "S"
    ew = "E" if lon_i >= 0 else "W"
    return f"{ns}{abs(lat_i):02d}{ew}{abs(lon_i):03d}"


def _parse_hgt(data: bytes) -> Tuple[int, array]:
    """Parse raw HGT bytes into (n, flat signed-short big-endian grid)."""
    sample_count = len(data) // 2
    n = int(math.isqrt(sample_count))
    if n * n != sample_count:
        raise NasaElevationError(f"Unexpected HGT byte length {len(data)} in tile")
    grid = array("h")
    grid.frombytes(data[: n * n * 2])
    if sys.byteorder == "little":
        grid.byteswap()
    return n, grid


class NasaSrtmElevationClient:
    """Server-side client for LP DAAC Earthdata Cloud SRTMGL1.003 tiles."""

    def __init__(
        self,
        token: Optional[str] = None,
        url_template: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self._token = (token if token is not None else config.NASA_EARTHDATA_TOKEN) or ""
        self._url_template = url_template or config.NASA_SRTM_LPDAAC_URL_TEMPLATE
        self._timeout = timeout or config.NASA_SRTM_TIMEOUT_SEC
        self._tiles = TTLCache(config.TERRAIN_CACHE_TTL_SEC, max_entries=config.NASA_SRTM_MAX_TILES)

    def configured(self) -> bool:
        return bool(self._token)

    @staticmethod
    def _tile_url(url_template: str, tile: str) -> str:
        return url_template.format(tile=tile)

    def download_tile(self, tile: str) -> bytes:
        """Fetch + unzip one HGT tile; raises typed errors on auth/missing/5xx."""
        if not self.configured():
            raise NasaAuthError("NASA Earthdata token is not configured")
        if _nasa_in_cooldown():
            raise NasaElevationError("NASA Earthdata is in its rate-limit cooldown window")
        url = self._tile_url(self._url_template, tile)
        response = http_get_bytes(
            url,
            timeout=self._timeout,
            headers={"Authorization": f"Bearer {self._token}"},
        )
        if response.status_code == 429:
            _mark_nasa_cooldown(config.WEATHER_PROVIDER_COOLDOWN_SEC)
            raise NasaElevationError("NASA Earthdata throttled the request (HTTP 429)")
        if response.status_code == 401 or response.status_code == 403:
            raise NasaAuthError(f"NASA Earthdata rejected the credentials ({response.status_code})")
        if response.status_code == 404:
            raise NasaTileMissingError(f"SRTMGL1 tile {tile} not found by the provider")
        if response.status_code >= 400:
            raise NasaElevationError(f"NASA Earthdata rejected the request ({response.status_code})")
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            names = [name for name in zf.namelist() if name.lower().endswith((".hgt", ".dem", ".nc"))]
            if not names:
                raise NasaElevationError(f"No elevation raster inside SRTM tile {tile}")
            return zf.read(names[0])

    def get_grid(self, latitude: float, longitude: float) -> Tuple[int, array, str]:
        """Return (n, grid, tile) for the tile covering lat/lon (cached)."""
        tile = tile_name(latitude, longitude)

        def _load() -> Optional[Tuple[int, array]]:
            raw = self.download_tile(tile)
            n, grid = _parse_hgt(raw)
            return n, grid

        loaded = self._tiles.get_or_set(tile, _load)  # type: ignore[arg-type]
        if loaded is None:  # pragma: no cover - defensive; get_or_set caches only non-None
            raise NasaElevationError(f"Could not load SRTM tile {tile}")
        return loaded[0], loaded[1], tile

    @staticmethod
    def _sample(n: int, grid: array, row: int, col: int) -> Optional[float]:
        if row < 0 or row >= n or col < 0 or col >= n:
            return None
        value = int(grid[row * n + col])
        if value == VOID_VALUE:
            return None
        return float(value)

    @staticmethod
    def _sample_clamped(n: int, grid: array, row: int, col: int) -> Optional[float]:
        """Edge-clamped sample: a window that falls beyond a tile edge reads the
        boundary cell instead of yielding None, so near-edge slope never goes
        missing (only REAL void cells stay None)."""
        row = max(0, min(n - 1, int(row)))
        col = max(0, min(n - 1, int(col)))
        return NasaSrtmElevationClient._sample(n, grid, row, col)

    @staticmethod
    def _bilinear(n: int, grid: array, col_f: float, row_f: float) -> Optional[float]:
        """Bilinear elevation at fractional (col,row), falling back to nearest."""
        x0 = int(math.floor(col_f))
        y0 = int(math.floor(row_f))
        x1 = min(x0 + 1, n - 1)
        y1 = min(y0 + 1, n - 1)
        tx = col_f - x0
        ty = row_f - y0

        z00 = NasaSrtmElevationClient._sample(n, grid, y0, x0)
        z10 = NasaSrtmElevationClient._sample(n, grid, y0, x1)
        z01 = NasaSrtmElevationClient._sample(n, grid, y1, x0)
        z11 = NasaSrtmElevationClient._sample(n, grid, y1, x1)
        if (
            z00 is not None
            and z10 is not None
            and z01 is not None
            and z11 is not None
        ):
            return (
                z00 * (1 - tx) * (1 - ty)
                + z10 * tx * (1 - ty)
                + z01 * (1 - tx) * ty
                + z11 * tx * ty
            )
        nearest = NasaSrtmElevationClient._sample(n, grid, round(row_f), round(col_f))
        return nearest

    def compute_terrain(self, latitude: float, longitude: float) -> Dict[str, Any]:
        """Real elevation + DEM-window slope for one WGS84 point."""
        n, grid, tile = self.get_grid(latitude, longitude)

        top = math.floor(latitude) + 1.0
        left = math.floor(longitude)
        col_f = (longitude - left) * (n - 1)
        row_f = (top - latitude) * (n - 1)

        elevation = self._bilinear(n, grid, col_f, row_f)

        step = max(1, int(config.NASA_TERRAIN_SAMPLE_ARCSEC))
        y0 = int(round(row_f))
        x0 = int(round(col_f))
        window: Dict[Tuple[int, int], Optional[float]] = {}
        for oy in (-step, 0, step):
            for ox in (-step, 0, step):
                window[(ox, oy)] = self._sample_clamped(n, grid, y0 + oy, x0 + ox)

        slope_degrees: Optional[float] = None
        slope_percent: Optional[float] = None
        elevation_change: Optional[float] = None
        valid_values = [v for v in window.values() if v is not None]
        if len(valid_values) == len(window):
            z: Dict[Tuple[int, int], float] = {
                key: float(value) if value is not None else 0.0 for key, value in window.items()
            }
            meters_per_sample_x = _M_PER_DEG_LON_EQ * math.cos(math.radians(latitude)) / (n - 1)
            meters_per_sample_y = _M_PER_DEG_LAT / (n - 1)
            span = float(step)
            dzdx = (
                (z[(step, -step)] + 2 * z[(step, 0)] + z[(step, step)])
                - (z[(-step, -step)] + 2 * z[(-step, 0)] + z[(-step, step)])
            ) / (8 * span * meters_per_sample_x)
            dzdy = (
                (z[(-step, -step)] + 2 * z[(0, -step)] + z[(step, -step)])
                - (z[(-step, step)] + 2 * z[(0, step)] + z[(step, step)])
            ) / (8 * span * meters_per_sample_y)
            slope_degrees = math.degrees(math.atan(math.hypot(dzdx, dzdy)))
            slope_percent = math.tan(math.radians(slope_degrees)) * 100.0
            elevation_change = max(valid_values) - min(valid_values)

        return {
            "elevation_m": None if elevation is None else round(elevation, 2),
            "slope_degrees": None if slope_degrees is None else round(slope_degrees, 2),
            "slope_percent": None if slope_percent is None else round(slope_percent, 2),
            "elevation_change_m": None if elevation_change is None else round(elevation_change, 2),
            "slope_window_arcsec": step,
            "tile": tile,
            "dataset": "NASA SRTMGL1.003 (1 arc-second, LP DAAC)",
            "data_source": "NASA Earthdata SRTM (LP DAAC SRTMGL1 v003)",
        }


nasa_elevation_client = NasaSrtmElevationClient()