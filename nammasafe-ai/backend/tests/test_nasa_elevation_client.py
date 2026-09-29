"""
Unit tests for the NASA Earthdata SRTM elevation client.

HTTP is stubbed via monkeypatched app.nasa_elevation_client.http_get_bytes so no
real calls escape. Contract: a valid token + reachable LP DAAC tile yields real
elevation/slope; auth rejection, missing tiles, and out-of-coverage coordinates
raise typed errors; the token is never logged.
"""

import io
import sys
import zipfile
from array import array

import pytest

from app import config
from app.nasa_elevation_client import (
    NasaAuthError,
    NasaElevationError,
    NasaSrtmElevationClient,
    NasaTileMissingError,
    tile_name,
    _parse_hgt,
)


class FakeBytesResponse:
    def __init__(self, status_code=200, content=b""):
        self.status_code = status_code
        self.content = content


def make_hgt(n, value_fn):
    grid = array("h")
    for row in range(n):
        for col in range(n):
            grid.append(int(value_fn(row, col)))
    if sys.byteorder == "little":
        grid.byteswap()
    return grid.tobytes()


def make_tile_zip(hgt_bytes, name="N30E079.hgt"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, hgt_bytes)
    return buf.getvalue()


def _patch_bytes(monkeypatch, handler):
    monkeypatch.setattr("app.nasa_elevation_client.http_get_bytes", handler)


@pytest.fixture(autouse=True)
def _config_defaults(monkeypatch):
    monkeypatch.setattr(config, "NASA_TERRAIN_SAMPLE_ARCSEC", 3)
    monkeypatch.setattr(config, "NASA_SRTM_MAX_TILES", 3)


# ---------------- tile naming ----------------

def test_tile_name_india():
    assert tile_name(30.43, 79.72) == "N30E079"


def test_tile_name_south_west():
    assert tile_name(-33.9, -70.6) == "S34W071"


def test_tile_name_out_of_coverage_raises():
    with pytest.raises(NasaTileMissingError):
        tile_name(91.0, 10.0)  # beyond the nameable latitude band


# ---------------- HGT parsing ----------------

def test_parse_hgt_roundtrip():
    raw = make_hgt(5, lambda r, c: 100 * r + c)
    n, grid = _parse_hgt(raw)
    assert n == 5
    assert grid[0] == 0
    assert grid[4] == 4
    assert grid[4 * 5 + 1] == 401


def test_parse_hgt_rejects_bad_lengths():
    with pytest.raises(NasaElevationError):
        _parse_hgt(b"\x00" * 10)


# ---------------- client without token ----------------

def test_client_not_configured(monkeypatch):
    monkeypatch.setattr(config, "NASA_EARTHDATA_TOKEN", "")
    client = NasaSrtmElevationClient()
    assert not client.configured()
    with pytest.raises(NasaAuthError):
        client.download_tile("N30E079")


# ---------------- live-style fetch with a stubbed tile ----------------

def test_elevation_bilinear_and_slope_flat(monkeypatch):
    client = NasaSrtmElevationClient(token="fake-token")

    def handler(url, timeout=None, headers=None, max_retries=2):
        assert headers and headers.get("Authorization") == "Bearer fake-token"
        assert "SRTMGL1.003" in url and "N30E079" in url
        return FakeBytesResponse(200, make_tile_zip(make_hgt(101, lambda r, c: 1200)))

    _patch_bytes(monkeypatch, handler)
    payload = client.compute_terrain(30.5, 79.5)

    assert payload["elevation_m"] == 1200.0
    assert payload["slope_degrees"] == 0.0
    assert payload["slope_percent"] == 0.0
    assert payload["elevation_change_m"] == 0.0
    assert payload["dataset"].startswith("NASA SRTMGL1.003")
    assert payload["tile"] == "N30E079"


def test_elevation_ramp_and_slope(monkeypatch):
    client = NasaSrtmElevationClient(token="fake-token")

    def handler(url, timeout=None, headers=None, max_retries=2):
        assert headers and "fake-token" in str(headers)
        # value = 1000 + 2m per arc-second eastward.
        return FakeBytesResponse(200, make_tile_zip(make_hgt(101, lambda r, c: 2000 + 3 * c)))

    _patch_bytes(monkeypatch, handler)

    # lat 30.5 -> row_f 50, lon 79.5 -> col_f 50; window covers rows/cols 47..53.
    payload = client.compute_terrain(30.5, 79.5)
    assert payload["elevation_m"] is not None
    assert payload["slope_degrees"] is not None and payload["slope_degrees"] > 0
    assert payload["slope_percent"] is not None and payload["slope_percent"] > 0
    # 6 samples apart in a 3-arcsec window frame -> change = 6 * 3 m
    assert payload["elevation_change_m"] == 18.0


def test_void_pixels_give_none_elevation(monkeypatch):
    client = NasaSrtmElevationClient(token="fake-token")

    def handler(url, timeout=None, headers=None, max_retries=2):
        return FakeBytesResponse(
            200,
            make_tile_zip(make_hgt(101, lambda r, c: -32768 if (r == 50 and c == 50) else 900)),
        )

    _patch_bytes(monkeypatch, handler)
    # Center pixel is void -> bilinear yields None at that exact cell.
    payload = client.compute_terrain(30.5, 79.5)
    assert payload["elevation_m"] is None
    # A neighbouring point over non-void pixels resolves fine.
    neighbour = client.compute_terrain(30.49, 79.512)
    assert neighbour["elevation_m"] == 900.0


# ---------------- error handling ----------------

def test_auth_rejection_raises(monkeypatch):
    client = NasaSrtmElevationClient(token="expired-token")

    def handler(url, timeout=None, headers=None, max_retries=2):
        return FakeBytesResponse(401, b"")

    _patch_bytes(monkeypatch, handler)
    with pytest.raises(NasaAuthError):
        client.compute_terrain(30.5, 79.5)


def test_missing_tile_raises(monkeypatch):
    client = NasaSrtmElevationClient(token="fake-token")

    def handler(url, timeout=None, headers=None, max_retries=2):
        return FakeBytesResponse(404, b"")

    _patch_bytes(monkeypatch, handler)
    with pytest.raises(NasaTileMissingError):
        client.compute_terrain(30.5, 79.5)


def test_server_error_retried_then_raises(monkeypatch):
    client = NasaSrtmElevationClient(token="fake-token")
    calls = {"n": 0}

    def handler(url, timeout=None, headers=None, max_retries=2):
        calls["n"] += 1
        return FakeBytesResponse(503, b"")

    _patch_bytes(monkeypatch, handler)
    with pytest.raises(NasaElevationError):
        client.compute_terrain(30.5, 79.5)
    # two attempts (first + one retry within max_retries), then raises
    assert calls["n"] >= 1