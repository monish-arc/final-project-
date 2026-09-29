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
import os
import sys
import threading
import time
import zipfile
from array import array

import pytest

from app import config
from app.http_client import HttpFetchError
from app.models import Base
from app.terrain_service import TerrainService
from app.weather_service import _provider_in_cooldown
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
    # A 429 in one test must never gate the open-meteo elevation fetches of the
    # tests that follow it: start every test with a clean cooldown registry.
    monkeypatch.setattr("app.weather_service._PROVIDER_COOLDOWN_UNTIL", {})


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


# ---------------- no-secret Open-Meteo fallback on the elevation fast path ----------------

def test_fallback_flag_defaults_to_on_without_env():
    """Deployment contract: NASA Earthdata is optional. With no token and no
    operator override the Open-Meteo elevation fallback is ON by default, so a
    fresh Render box serves real elevation out of the box."""
    assert os.getenv("NASA_TERRAIN_FALLBACK_OPENMETEO", "on").lower() == "on"


def test_elevation_fast_no_token_with_fallback_serves_live_openmeteo(monkeypatch):
    """The /api/elevation fast path must serve REAL Open-Meteo elevation (labelled
    fallback) when NASA Earthdata is not configured and the fallback is on."""
    monkeypatch.setattr(config, "NASA_EARTHDATA_TOKEN", "")
    monkeypatch.setattr(config, "NASA_TERRAIN_FALLBACK_OPENMETEO", True)
    _patch_openmeteo(monkeypatch, [[300.0, 320.0, 350.0, 290.0, 310.0, 330.0, 300.0, 305.0, 315.0]])
    payload = TerrainService().get_elevation_fast(30.5, 79.5)
    assert payload["data_status"] == "LIVE"
    assert payload["provider"] == "open-meteo"
    assert payload["provider_role"] == "fallback"
    assert payload["elevation_m"] == 300.0
    assert "not configured" in (payload.get("reason") or "").lower()


def test_elevation_fast_no_token_without_fallback_is_not_configured(monkeypatch):
    """Honesty: with the fallback off and no token the fast path stays
    NOT_CONFIGURED (never a fabricated elevation)."""
    monkeypatch.setattr(config, "NASA_EARTHDATA_TOKEN", "")
    payload = TerrainService().get_elevation_fast(30.5, 79.5)
    assert payload["data_status"] == "NOT_CONFIGURED"
    assert payload["elevation_m"] is None
    assert "token not configured" in payload["reason"]


def test_elevation_fast_openmeteo_down_is_unavailable(monkeypatch):
    """An unreachable fallback degrades to an honest UNAVAILABLE, not a value."""
    monkeypatch.setattr(config, "NASA_EARTHDATA_TOKEN", "")
    monkeypatch.setattr(config, "NASA_TERRAIN_FALLBACK_OPENMETEO", True)
    _patch_openmeteo(monkeypatch, [False])
    payload = TerrainService().get_elevation_fast(30.5, 79.5)
    assert payload["data_status"] in ("UNAVAILABLE", "NOT_CONFIGURED")
    assert payload["elevation_m"] is None
    assert payload["reason"]


def test_elevation_fast_with_token_delegates_to_terrain(monkeypatch):
    """With NASA configured the fast path still serves real SRTM elevation
    (via get_terrain) and slims it to an elevation-only payload."""
    def handler(url, timeout=None, headers=None, max_retries=2):
        return FakeBytesResponse(200, flat_tile_zip())

    _patch_nasa(monkeypatch, handler)
    payload = TerrainService().get_elevation_fast(30.5, 79.5)
    assert payload["data_status"] == "LIVE"
    assert payload["provider"] == "nasa"
    assert payload["elevation_m"] == 940.0
    assert "fast path" in payload["reason"]


# ---------------- 429 handling + short failure TTL ----------------

def test_openmeteo_429_marks_cooldown_and_degrades_honest(monkeypatch):
    """A 429 from the fallback provider marks the shared provider cooldown and
    the second user request is served from cache (no repeat upstream)."""
    monkeypatch.setattr("app.weather_service._PROVIDER_COOLDOWN_UNTIL", {})
    monkeypatch.setattr(config, "NASA_EARTHDATA_TOKEN", "")
    monkeypatch.setattr(config, "NASA_TERRAIN_FALLBACK_OPENMETEO", True)
    calls = {"n": 0}

    def handler(url, params=None, timeout=None, headers=None, max_retries=2):
        calls["n"] += 1
        return FakeBytesResponse(429, b"", json_payload=None)

    monkeypatch.setattr("app.terrain_service.http_get", handler)
    payload = TerrainService().get_terrain(30.5, 79.5)
    assert payload["data_status"] in ("UNAVAILABLE", "NOT_CONFIGURED")
    assert payload["elevation_m"] is None
    assert _provider_in_cooldown("Open-Meteo elevation") is True

    again = TerrainService().get_terrain(30.5, 79.5)
    assert again["data_status"] in ("UNAVAILABLE", "NOT_CONFIGURED")
    assert calls["n"] == 1  # second request served from the short-TTL failure cache


def test_failure_payload_cached_with_short_ttl(monkeypatch):
    """Transient failures are cached only for TERRAIN_FAILURE_CACHE_TTL_SEC so a
    wounded provider recovers quickly instead of sticking for 24h."""
    import app.cache as cache_module

    real_monotonic = cache_module.time.monotonic
    ticks = {"now": real_monotonic()}
    monkeypatch.setattr(cache_module.time, "monotonic", lambda: ticks["now"])

    monkeypatch.setattr(config, "NASA_EARTHDATA_TOKEN", "")
    monkeypatch.setattr(config, "NASA_TERRAIN_FALLBACK_OPENMETEO", True)
    calls = {"n": 0}

    def handler(url, params=None, timeout=None, headers=None, max_retries=2):
        calls["n"] += 1
        return FakeBytesResponse(503, b"", json_payload=None)

    monkeypatch.setattr("app.terrain_service.http_get", handler)

    svc = TerrainService()

    monkeypatch.setattr(config, "TERRAIN_FAILURE_CACHE_TTL_SEC", 0)
    svc.get_terrain(30.5, 79.5)
    ticks["now"] += 0.5
    svc.get_terrain(30.5, 79.5)
    assert calls["n"] == 2  # TTL 0 -> the failure never sticks

    monkeypatch.setattr(config, "TERRAIN_FAILURE_CACHE_TTL_SEC", 30)
    calls["n"] = 0
    svc.get_terrain(30.5, 79.5)
    ticks["now"] += 5.0
    svc.get_terrain(30.5, 79.5)
    assert calls["n"] == 1  # within the short window -> cached, no repeat fetch

    ticks["now"] += 31.0
    svc.get_terrain(30.5, 79.5)
    assert calls["n"] == 2  # short window elapsed -> provider probed again


# ---------------- DB cache serves WITHOUT a token (hoisted read) ----------------

def test_db_cache_serves_without_token(monkeypatch):
    """A warm terrain_samples row (validated NASA data) must be served even when
    the token is later removed — real stored values, no NASA call needed."""
    monkeypatch.setattr(config, "TERRAIN_DB_CACHE", "on")
    calls = {"n": 0}

    def nasa_handler(url, timeout=None, headers=None, max_retries=2):
        calls["n"] += 1
        return FakeBytesResponse(200, flat_tile_zip())

    _patch_nasa(monkeypatch, nasa_handler)

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    first = TerrainService(db=session).get_terrain(30.5, 79.5)
    assert first["data_status"] == "LIVE"
    assert calls["n"] == 1

    monkeypatch.setattr(config, "NASA_EARTHDATA_TOKEN", "")
    monkeypatch.setattr(config, "NASA_TERRAIN_FALLBACK_OPENMETEO", False)

    def no_nasa(*args, **kwargs):
        raise AssertionError("NASA must not be called when the DB cache serves")

    _patch_nasa(monkeypatch, no_nasa)
    second = TerrainService(db=session).get_terrain(30.5001, 79.5001)  # same ~55m cell
    assert second["data_status"] == "LIVE"
    assert second["provider"] == "nasa"
    assert second["elevation_m"] == 940.0
    assert calls["n"] == 1
    session.close()


# ---------------- single-flight dedupe ----------------

def test_terrain_single_flight_dedups_concurrent_requests(monkeypatch):
    """N concurrent identical requests share ONE upstream fetch instead of
    hammering the provider (mirrors the live weather chain's in-flight dedupe)."""
    monkeypatch.setattr("app.weather_service._INFLIGHT", {})
    monkeypatch.setattr(config, "NASA_EARTHDATA_TOKEN", "")
    monkeypatch.setattr(config, "NASA_TERRAIN_FALLBACK_OPENMETEO", True)
    calls = {"n": 0}

    def handler(url, params=None, timeout=None, headers=None, max_retries=2):
        calls["n"] += 1
        time.sleep(0.15)  # widen the race so waiters overlap the leader
        return FakeBytesResponse(200, json_payload={"elevation": [300.0] * 9})

    monkeypatch.setattr("app.terrain_service.http_get", handler)

    svc = TerrainService()
    barrier = threading.Barrier(8)
    results: list = []
    errors: list = []

    def worker():
        barrier.wait()
        try:
            results.append(svc.get_elevation_fast(30.5, 79.5))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(results) == 8
    assert calls["n"] == 1
    assert all(r["data_status"] == "LIVE" for r in results)


# ---------------- grid resilience ----------------

def test_terrain_grid_point_raise_marks_cell_unavailable(monkeypatch):
    """A per-cell provider exception must settle that cell to honest
    UNAVAILABLE (never crash the whole grid request)."""
    from app.terrain_service import terrain_service as global_service

    def boom(lat, lng):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(global_service, "get_terrain", boom)
    monkeypatch.setattr(config, "TERRAIN_GRID_TIMEOUT_SEC", 2.0)
    grid = global_service.get_terrain_grid(30.2, 30.0, 78.5, 78.4, step=0.02, max_points=50)
    assert grid["data_status"] == "UNAVAILABLE"
    assert grid["points"]
    assert all(p["data_status"] == "UNAVAILABLE" for p in grid["points"])