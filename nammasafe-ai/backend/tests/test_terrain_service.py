"""
Behavioural tests for the terrain provider orchestration.

Three layers are exercised with stubbed transports:
  * NASA-first — stubs app.nasa_elevation_client.http_get_bytes with a valid
    SRTM tile; expects LIVE, provider "nasa", role "primary".
  * opt-in fallback — stubs the Open-Meteo http_get; expects fallback labels and
    honest NOT_CONFIGURED/UNAVAILABLE payloads when fallback is off.
  * DB grid cache — in-memory SQLite; a second nearby query must not re-fetch
    from NASA.
"""

import io
import sys
import zipfile
from array import array

import pytest

from app import config
from app.http_client import HttpFetchError
from app.models import Base
from app.terrain_service import TerrainService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class FakeBytesResponse:
    def __init__(self, status_code=200, content=b"", json_payload=None):
        self.status_code = status_code
        self.content = content
        self._json = json_payload

    def json(self):
        return self._json


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


def flat_tile_zip():
    return make_tile_zip(make_hgt(101, lambda r, c: 940))


def _patch_nasa(monkeypatch, handler):
    monkeypatch.setattr("app.nasa_elevation_client.http_get_bytes", handler)


def _patch_openmeteo(monkeypatch, per_call_values):
    """per_call_values: list of elevation lists, one per http_get call (or False to fail)."""
    calls = {"n": 0}

    def handler(url, params=None, timeout=None, headers=None):
        call = calls["n"]
        calls["n"] += 1
        if call >= len(per_call_values):
            raise AssertionError("more Open-Meteo calls than stubbed")
        values = per_call_values[call]
        if values is False:
            raise HttpFetchError("network down")
        return FakeBytesResponse(200, json_payload={"elevation": values})

    monkeypatch.setattr("app.terrain_service.http_get", handler)
    return calls


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch):
    monkeypatch.setattr(config, "NASA_EARTHDATA_TOKEN", "fake-token")
    monkeypatch.setattr(config, "NASA_TERRAIN_FALLBACK_OPENMETEO", False)
    monkeypatch.setattr(config, "TERRAIN_DB_CACHE", "off")
    monkeypatch.setattr(config, "NASA_TERRAIN_SAMPLE_ARCSEC", 3)
    monkeypatch.setattr(config, "NASA_SRTM_MAX_TILES", 3)


# ---------------- NASA primary ----------------

def test_nasa_primary_live(monkeypatch):
    def handler(url, timeout=None, headers=None, max_retries=2):
        return FakeBytesResponse(200, flat_tile_zip())

    _patch_nasa(monkeypatch, handler)
    payload = TerrainService().get_terrain(30.5, 79.5)

    assert payload["data_status"] == "LIVE"
    assert payload["provider"] == "nasa"
    assert payload["provider_role"] == "primary"
    assert payload["elevation_m"] == 940.0
    assert payload["slope_degrees"] == 0.0
    assert payload["dataset"].startswith("NASA SRTMGL1.003")
    assert "reason" not in payload


def test_nasa_auth_error_without_fallback(monkeypatch):
    openmeteo_calls = _patch_openmeteo(monkeypatch, [])  # no stubs: fallback must not fire

    def handler(url, timeout=None, headers=None, max_retries=2):
        return FakeBytesResponse(401, b"")

    _patch_nasa(monkeypatch, handler)
    payload = TerrainService().get_terrain(30.5, 79.5)

    assert payload["data_status"] == "UNAVAILABLE"
    assert payload["provider"] == "nasa"
    assert payload["elevation_m"] is None
    assert "credentials" in (payload.get("reason") or "").lower()
    assert openmeteo_calls["n"] == 0  # fallback not consulted when off


def test_nasa_unreachable_without_fallback(monkeypatch):
    def handler(url, timeout=None, headers=None, max_retries=2):
        return FakeBytesResponse(503, b"")

    _patch_nasa(monkeypatch, handler)
    payload = TerrainService().get_terrain(30.5, 79.5)
    assert payload["data_status"] == "UNAVAILABLE"
    assert payload["elevation_m"] is None


# ---------------- opt-in fallback ----------------

def test_fallback_engaged_and_labelled(monkeypatch):
    _patch_openmeteo(monkeypatch, [[300.0, 320.0, 350.0, 290.0, 310.0, 330.0, 300.0, 305.0, 315.0]])

    def handler(url, timeout=None, headers=None, max_retries=2):
        return FakeBytesResponse(401, b"")

    _patch_nasa(monkeypatch, handler)
    monkeypatch.setattr(config, "NASA_TERRAIN_FALLBACK_OPENMETEO", True)
    payload = TerrainService().get_terrain(30.5, 79.5)

    assert payload["data_status"] == "LIVE"
    assert payload["provider"] == "open-meteo"
    assert payload["provider_role"] == "fallback"
    assert "fallback" in (payload.get("reason") or "").lower()
    assert payload["elevation_m"] == 300.0


def test_no_token_without_fallback(monkeypatch):
    monkeypatch.setattr(config, "NASA_EARTHDATA_TOKEN", "")
    payload = TerrainService().get_terrain(30.5, 79.5)
    assert payload["data_status"] == "NOT_CONFIGURED"
    assert payload["elevation_m"] is None
    assert "token" in (payload.get("reason") or "").lower()


def test_no_token_with_fallback(monkeypatch):
    monkeypatch.setattr(config, "NASA_EARTHDATA_TOKEN", "")
    monkeypatch.setattr(config, "NASA_TERRAIN_FALLBACK_OPENMETEO", True)
    _patch_openmeteo(monkeypatch, [[250.0, 260.0, 255.0, 258.0, 252.0, 251.0, 259.0, 254.0, 253.0]])
    payload = TerrainService().get_terrain(30.5, 79.5)

    assert payload["data_status"] == "LIVE"
    assert payload["provider_role"] == "fallback"
    assert payload["elevation_m"] == 250.0


# ---------------- DB grid cache ----------------

def test_db_cache_avoids_repeat_nasa_fetch(monkeypatch):
    monkeypatch.setattr(config, "TERRAIN_DB_CACHE", "on")
    calls = {"n": 0}

    def handler(url, timeout=None, headers=None, max_retries=2):
        calls["n"] += 1
        return FakeBytesResponse(200, flat_tile_zip())

    _patch_nasa(monkeypatch, handler)

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    svc = TerrainService(db=session)
    first = svc.get_terrain(30.5, 79.5)
    second = svc.get_terrain(30.5001, 79.5001)  # same ~55 m grid cell
    third = svc.get_terrain(31.0, 79.5)         # different cell -> new fetch

    assert first["data_status"] == "LIVE"
    assert second["data_status"] == "LIVE"
    assert calls["n"] == 2  # not 3: second hit the DB cache
    assert third["data_status"] == "LIVE"
    session.close()


# ---------------- open-met only instance (test/ops isolation) ----------------

def test_terrain_grid_deadlines_to_honest_unavailable_when_srtm_slow(monkeypatch):
    """A slow or unreachable SRTM source must settle the grid to an honest
    UNAVAILABLE within the budget — never hang the layer for minutes."""
    import time

    from app.terrain_service import terrain_service as global_service

    def slow_terrain(lat, lng):
        time.sleep(0.2)
        return {
            "latitude": lat,
            "longitude": lng,
            "elevation_m": None,
            "slope_percent": None,
            "slope_category": None,
            "data_status": "UNAVAILABLE",
            "data_source": "SRTM coverage",
            "provider": None,
            "reason": "provider slow",
        }

    monkeypatch.setattr(global_service, "get_terrain", slow_terrain)
    monkeypatch.setattr(config, "TERRAIN_GRID_TIMEOUT_SEC", 0.05)
    monkeypatch.setattr(config, "TERRAIN_GRID_WORKERS", 4)

    started = time.monotonic()
    grid = global_service.get_terrain_grid(30.2, 30.0, 78.5, 78.4, step=0.02, max_points=100)
    elapsed = time.monotonic() - started

    assert elapsed < 1.0, f"grid took {elapsed:.2f}s — budget not enforced"
    assert grid["data_status"] == "UNAVAILABLE"
    assert grid["points"]
    assert all(p["data_status"] == "UNAVAILABLE" for p in grid["points"])
    assert any("timed out" in (p.get("reason") or "") for p in grid["points"])
    assert "never invented" in grid["points"][0]["reason"]


def test_openmeteo_only_instance_unavailable(monkeypatch):
    _patch_openmeteo(monkeypatch, [False])  # transport down
    payload = TerrainService(base_url="https://test", db=None).get_terrain(30.5, 79.5)
    assert payload["data_status"] == "UNAVAILABLE"
    assert "reason" in payload


def test_openmeteo_only_instance_live(monkeypatch):
    _patch_openmeteo(monkeypatch, [[310.0, 315.0, 312.0, 308.0, 305.0, 318.0, 314.0, 316.0, 311.0]])
    payload = TerrainService(base_url="https://test", db=None).get_terrain(30.5, 79.5)
    assert payload["data_status"] == "LIVE"
    assert payload["provider"] == "open-meteo"
    assert payload["provider_role"] == "primary"
    assert payload["elevation_m"] == 310.0
    assert payload["slope_percent"] is not None