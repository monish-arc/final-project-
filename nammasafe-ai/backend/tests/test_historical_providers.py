"""
Unit tests for the official Historical Data providers (ERA5 / IMD / India-WRIS /
KSDMA) behind app/historical_providers.py.

HTTP is stubbed at the app.http_client boundary so no upstream call ever escapes.

Core contract these tests defend:
  * A provider is only ``LIVE``/``HISTORICAL`` after a real successful call.
  * A missing credential is ``NOT_CONFIGURED`` — never a silent empty success.
  * A failed call (timeout / 4xx / 5xx / non-JSON) is ``ERROR`` with a reason,
    and never raises into the dashboard.
  * A provider with no official machine-readable source (KSDMA) is
    ``UNAVAILABLE`` and is never scraped or fabricated.
"""

import pytest

from app import config
from app.historical_providers import (
    PROVIDER_ERA5,
    PROVIDER_IMD,
    PROVIDER_INDIAWRIS,
    PROVIDER_KSDMA,
    clear_probe_cache,
    fetch_ksdma,
    imd_request,
    indiawris_query,
    provider_status,
    provider_statuses,
)
from app.http_client import HttpFetchError


class _FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload

    @property
    def content(self):
        return b""


@pytest.fixture(autouse=True)
def _reset_probes():
    """Probe results are cached across calls; isolate every test."""
    clear_probe_cache()
    yield
    clear_probe_cache()


@pytest.fixture()
def no_imd_key(monkeypatch):
    monkeypatch.setattr(config, "IMD_API_KEY", "")


def _patch_http(monkeypatch, handler):
    """Replace app.historical_providers.http_get with a recording stub."""
    calls = []

    def _http_get(url, params=None, **kwargs):
        calls.append({"url": url, "params": params, **kwargs})
        return handler(url, params, kwargs)

    monkeypatch.setattr("app.historical_providers.http_get", _http_get)
    return calls


def _err(status) -> str:
    """The provider's error text, asserted on in several tests."""
    assert status.error is not None, "expected an error message on this provider status"
    return status.error


# ---------------------------------------------------------------------------
# ERA5 — existing keyless provider, resolved without any network call
# ---------------------------------------------------------------------------

def test_era5_is_historical_without_network(monkeypatch):
    calls = _patch_http(monkeypatch, lambda *_: pytest.fail("ERA5 probe must not call upstream"))

    status = provider_status(PROVIDER_ERA5)

    assert status.status == "HISTORICAL"
    assert status.available is True
    assert status.error is None
    assert "ERA5" in status.source
    assert calls == []


# ---------------------------------------------------------------------------
# KSDMA — no official machine-readable API, so honestly UNAVAILABLE
# ---------------------------------------------------------------------------

def test_ksdma_unavailable_and_never_calls_upstream(monkeypatch):
    _patch_http(monkeypatch, lambda *_: pytest.fail("KSDMA has no API to call"))

    status = provider_status(PROVIDER_KSDMA)

    assert status.status == "UNAVAILABLE"
    assert status.available is False
    assert "no machine-readable api" in _err(status).lower()


def test_ksdma_payload_is_empty_not_fabricated():
    payload = fetch_ksdma()

    assert payload["data_status"] == "UNAVAILABLE"
    assert payload["available"] is False
    assert payload["records"] == []
    assert payload["error"]


# ---------------------------------------------------------------------------
# IMD — official api.imd.gov.in API, key required
# ---------------------------------------------------------------------------

def test_imd_not_configured_without_key(monkeypatch, no_imd_key):
    calls = _patch_http(monkeypatch, lambda *_: pytest.fail("must not probe without a key"))

    status = provider_status(PROVIDER_IMD)

    assert status.status == "NOT_CONFIGURED"
    assert status.available is False
    assert "IMD_API_KEY" in _err(status)
    assert calls == []


def test_imd_live_on_success(monkeypatch):
    monkeypatch.setattr(config, "IMD_API_KEY", "secret-key")
    _patch_http(monkeypatch, lambda *_: _FakeResp(200, [{"Obj_id": "1"}]))

    status = provider_status(PROVIDER_IMD)

    assert status.status == "LIVE"
    assert status.available is True
    assert status.error is None


def test_imd_reports_auth_failure_distinctly(monkeypatch):
    monkeypatch.setattr(config, "IMD_API_KEY", "bad-key")
    _patch_http(monkeypatch, lambda *_: _FakeResp(401))

    status = provider_status(PROVIDER_IMD)

    assert status.status == "ERROR"
    assert status.available is False
    assert "401" in _err(status)
    assert "credential" in _err(status).lower()


def test_imd_reports_rate_limit(monkeypatch):
    monkeypatch.setattr(config, "IMD_API_KEY", "secret-key")
    _patch_http(monkeypatch, lambda *_: _FakeResp(429))

    status = provider_status(PROVIDER_IMD)

    assert status.status == "ERROR"
    assert "429" in _err(status)


def test_imd_reports_timeout_as_unreachable(monkeypatch):
    monkeypatch.setattr(config, "IMD_API_KEY", "secret-key")

    def _boom(*_):
        raise HttpFetchError("Request failed for imd: timed out")

    _patch_http(monkeypatch, _boom)

    status = provider_status(PROVIDER_IMD)

    assert status.status == "ERROR"
    assert "unreachable" in _err(status).lower()


def test_imd_reports_server_error(monkeypatch):
    monkeypatch.setattr(config, "IMD_API_KEY", "secret-key")
    _patch_http(monkeypatch, lambda *_: _FakeResp(503))

    status = provider_status(PROVIDER_IMD)

    assert status.status == "ERROR"
    assert "503" in _err(status)


def test_imd_sends_key_as_header_by_default(monkeypatch):
    monkeypatch.setattr(config, "IMD_API_KEY", "secret-key")
    monkeypatch.setattr(config, "IMD_API_KEY_IN", "header")
    calls = _patch_http(monkeypatch, lambda *_: _FakeResp(200, []))

    provider_status(PROVIDER_IMD)

    assert calls[0]["headers"]["api-key"] == "secret-key"


def test_imd_can_send_key_as_query_param(monkeypatch):
    monkeypatch.setattr(config, "IMD_API_KEY", "secret-key")
    monkeypatch.setattr(config, "IMD_API_KEY_IN", "query")
    calls = _patch_http(monkeypatch, lambda *_: _FakeResp(200, []))

    provider_status(PROVIDER_IMD)

    assert calls[0]["params"]["api_key"] == "secret-key"


def test_imd_result_is_cached_between_probes(monkeypatch):
    monkeypatch.setattr(config, "IMD_API_KEY", "secret-key")
    calls = _patch_http(monkeypatch, lambda *_: _FakeResp(200, []))

    first = provider_status(PROVIDER_IMD)
    second = provider_status(PROVIDER_IMD)

    assert len(calls) == 1, "second probe must be served from cache"
    assert first.status == "LIVE" and first.cached is False
    # A cached live reading is reported as CACHED, never re-asserted as LIVE.
    assert second.status == "CACHED"
    assert second.cached is True


def test_imd_request_returns_decoded_payload(monkeypatch):
    monkeypatch.setattr(config, "IMD_API_KEY", "secret-key")
    _patch_http(monkeypatch, lambda *_: _FakeResp(200, [{"District": "THIRUVANANTHAPURAM"}]))

    assert imd_request("/districtrainfall") == [{"District": "THIRUVANANTHAPURAM"}]


def test_imd_request_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(config, "IMD_API_KEY", "secret-key")
    _patch_http(monkeypatch, lambda *_: _FakeResp(400))

    with pytest.raises(HttpFetchError):
        imd_request("/districtrainfall")


# ---------------------------------------------------------------------------
# India-WRIS — official ArcGIS REST services
# ---------------------------------------------------------------------------

def test_indiawris_live_when_service_serves_data(monkeypatch):
    _patch_http(monkeypatch, lambda *_: _FakeResp(200, {"layers": [{"id": 0}]}))

    status = provider_status(PROVIDER_INDIAWRIS)

    assert status.status == "LIVE"
    assert status.available is True


def test_indiawris_reports_http_400_from_official_services(monkeypatch):
    """The real observed upstream behaviour: the catalogue lists the service but
    the endpoint rejects requests. Must surface as ERROR, never as LIVE."""
    def _handler(url, params, _kwargs):
        # Catalogue root answers; the data service rejects.
        if url.rstrip("/").endswith("/services"):
            return _FakeResp(200, {"folders": ["NWIC"], "services": []})
        return _FakeResp(400)

    _patch_http(monkeypatch, _handler)

    status = provider_status(PROVIDER_INDIAWRIS)

    assert status.status == "ERROR"
    assert status.available is False
    assert "400" in _err(status)
    assert "no fallback or synthetic data" in _err(status).lower()


def test_indiawris_reports_unreachable_host(monkeypatch):
    def _boom(*_):
        raise HttpFetchError("Request failed for indiawris: unreachable")

    _patch_http(monkeypatch, _boom)

    status = provider_status(PROVIDER_INDIAWRIS)

    assert status.status == "ERROR"
    assert "unreachable" in _err(status).lower()


def test_indiawris_not_configured_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "INDIAWRIS_ENABLED", False)
    _patch_http(monkeypatch, lambda *_: pytest.fail("disabled provider must not call upstream"))

    status = provider_status(PROVIDER_INDIAWRIS)

    assert status.status == "NOT_CONFIGURED"
    assert "INDIAWRIS_ENABLED" in _err(status)


def test_indiawris_query_builds_official_request(monkeypatch):
    calls = _patch_http(monkeypatch, lambda *_: _FakeResp(200, {"features": []}))

    indiawris_query("NWIC/rf_station:MapServer", 0, where="1=1", out_fields="STATION")

    assert calls[0]["url"].endswith("/NWIC/rf_station:MapServer/0/query")
    assert calls[0]["params"]["where"] == "1=1"
    assert calls[0]["params"]["outFields"] == "STATION"


def test_indiawris_query_raises_on_http_error(monkeypatch):
    _patch_http(monkeypatch, lambda *_: _FakeResp(400))

    with pytest.raises(HttpFetchError):
        indiawris_query("NWIC/rf_station:MapServer", 0)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def test_provider_statuses_covers_all_providers_in_order():
    statuses = provider_statuses()

    assert [s.provider for s in statuses] == [
        PROVIDER_ERA5,
        PROVIDER_IMD,
        PROVIDER_INDIAWRIS,
        PROVIDER_KSDMA,
    ]


def test_provider_statuses_never_raises_on_probe_failure(monkeypatch):
    # A key is set so the probe actually reaches HTTP and fails, rather than
    # short-circuiting at the NOT_CONFIGURED credential check.
    monkeypatch.setattr(config, "IMD_API_KEY", "secret-key")

    def _boom(*_):
        raise RuntimeError("probe exploded")

    _patch_http(monkeypatch, _boom)

    statuses = {s.provider: s for s in provider_statuses()}

    # IMD/India-WRIS degrade to ERROR; ERA5/KSDMA are unaffected.
    assert statuses[PROVIDER_IMD].status == "ERROR"
    assert statuses[PROVIDER_INDIAWRIS].status == "ERROR"
    assert statuses[PROVIDER_ERA5].status == "HISTORICAL"
    assert statuses[PROVIDER_KSDMA].status == "UNAVAILABLE"


def test_unknown_provider_is_reported_not_raised():
    status = provider_status("does-not-exist")

    assert status.status == "UNAVAILABLE"
    assert "does-not-exist" in _err(status)


def test_status_serialises_the_documented_fields():
    payload = provider_status(PROVIDER_ERA5).to_dict()

    assert set(payload) == {
        "provider",
        "status",
        "source",
        "available",
        "cached",
        "last_updated",
        "period",
        "error",
        "coverage",
    }


# ---------------------------------------------------------------------------
# /api/data-status wire contract
# ---------------------------------------------------------------------------

def test_data_status_route_reports_layers_and_providers(db_ctx, auth_headers):
    res = db_ctx["client"].get("/api/data-status", headers=auth_headers)

    assert res.status_code == 200
    body = res.json()

    # Existing layer contract must be untouched.
    assert body["layers"]
    assert "checked_at" in body
    assert "era5" in {layer["layer"] for layer in body["layers"]}

    # Additive per-provider breakdown.
    providers = body["providers"]
    assert {p["provider"] for p in providers} == {
        PROVIDER_ERA5,
        PROVIDER_IMD,
        PROVIDER_INDIAWRIS,
        PROVIDER_KSDMA,
    }
    for entry in providers:
        assert entry["status"] in {
            "LIVE", "HISTORICAL", "CACHED", "NOT_CONFIGURED", "UNAVAILABLE", "ERROR",
        }
        assert "source" in entry


def test_data_status_route_requires_auth():
    from fastapi.testclient import TestClient

    from app.main import app

    res = TestClient(app).get("/api/data-status")

    assert res.status_code in (401, 403)


def test_data_status_route_survives_a_probe_blowup(monkeypatch, db_ctx, auth_headers):
    """A broken probe must never take the whole status panel down."""
    def _boom():
        raise RuntimeError("probe registry exploded")

    monkeypatch.setattr(
        "app.main.historical_provider_statuses", _boom, raising=True
    )

    res = db_ctx["client"].get("/api/data-status", headers=auth_headers)

    assert res.status_code == 200
    assert res.json()["providers"] == []
    assert res.json()["layers"]