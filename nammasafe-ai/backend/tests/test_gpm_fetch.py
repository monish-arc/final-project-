"""Tests for the GPM/GES DISC ingest helper (scripts/fetch_gpm_data.py)."""

from __future__ import annotations

import base64
import importlib.util
from pathlib import Path

import httpx
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
FETCH_PATH = BACKEND_DIR / "scripts" / "fetch_gpm_data.py"


@pytest.fixture(scope="module")
def fetch_mod() -> object:
    spec = importlib.util.spec_from_file_location("fetch_gpm_data", FETCH_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # imports app.config; script bootstraps sys.path
    return module


class _FakeResp:
    def __init__(self, status_code: int = 200, text: str = ""):
        self.status_code = status_code
        self._text = text

    @property
    def text(self) -> str:
        return self._text


LISTING_2024_172 = """
<html><body>
<a href="3B-HHR-E.MS.MRG.3IMERG.20240620-S000000-E002959.0000.V07C.HDF5">..</a>
<a href="3B-HHR-E.MS.MRG.3IMERG.20240620-S053000-E055959.0330.V07C.HDF5">..</a>
<a href="3B-HHR-E.MS.MRG.3IMERG.20240620-S060000-E062959.0360.V07C.HDF5">..</a>
</body></html>
"""


def test_day_listing_url_uses_day_of_year(monkeypatch: pytest.MonkeyPatch, fetch_mod: object) -> None:
    monkeypatch.setattr(fetch_mod, "PRODUCT_BASE_URL", "https://gpm1.example/s4pa/GPM_L3/GPM_3IMERGHHE.07")
    url = fetch_mod._day_listing_url("2024-06-20")  # type: ignore[attr-defined]
    assert url == "https://gpm1.example/s4pa/GPM_L3/GPM_3IMERGHHE.07/2024/172/"


def test_slot_stamp(fetch_mod: object) -> None:
    assert fetch_mod._slot_stamp("2024-06-20", "05:30") == "-S053000"  # type: ignore[attr-defined]


def test_tile_url_resolves_from_listing(monkeypatch: pytest.MonkeyPatch, fetch_mod: object) -> None:
    monkeypatch.setattr(
        fetch_mod,
        "PRODUCT_BASE_URL",
        "https://gpm1.example/s4pa/GPM_L3/GPM_3IMERGHHE.07",
    )

    def fake_get(url, *args, **kwargs):
        assert url.endswith("/2024/172/")
        return _FakeResp(200, LISTING_2024_172)

    monkeypatch.setattr(httpx, "get", fake_get)
    url = fetch_mod._tile_url("2024-06-20", "05:30", {"Authorization": "Bearer x"})  # type: ignore[attr-defined]
    assert url == (
        "https://gpm1.example/s4pa/GPM_L3/GPM_3IMERGHHE.07/2024/172/"
        "3B-HHR-E.MS.MRG.3IMERG.20240620-S053000-E055959.0330.V07C.HDF5"
    )


def test_tile_url_returns_none_for_unpublished_slot(monkeypatch: pytest.MonkeyPatch, fetch_mod: object) -> None:
    monkeypatch.setattr(
        fetch_mod,
        "PRODUCT_BASE_URL",
        "https://gpm1.example/s4pa/GPM_L3/GPM_3IMERGHHE.07",
    )
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResp(200, LISTING_2024_172))
    url = fetch_mod._tile_url("2024-06-20", "23:30", {"Authorization": "Bearer x"})  # type: ignore[attr-defined]
    assert url is None


def test_eula_403_surfaces_actionable_error(monkeypatch: pytest.MonkeyPatch, fetch_mod: object) -> None:
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResp(403, '{"error_description":"EULA Acceptance Failure","resolution_url":"https://urs.example/approve"}'))
    with pytest.raises(RuntimeError) as err:
        fetch_mod._tile_url("2024-06-20", "05:30", {"Authorization": "Bearer x"})  # type: ignore[attr-defined]
    assert "EULA" in str(err.value)
    assert "urs.example/approve" in str(err.value)


def test_bearer_header_for_jwt_token(monkeypatch: pytest.MonkeyPatch, fetch_mod: object) -> None:
    monkeypatch.setattr(fetch_mod, "EARTHDATA_TOKEN", "eyJhbGciOiJSUzI1NiJ9.sig")
    monkeypatch.setattr(fetch_mod, "EARTHDATA_USERNAME", "somedude")
    assert fetch_mod._auth_headers() == {"Authorization": "Bearer eyJhbGciOiJSUzI1NiJ9.sig"}  # type: ignore[attr-defined]


def test_basic_auth_fallback_for_legacy_token(monkeypatch: pytest.MonkeyPatch, fetch_mod: object) -> None:
    monkeypatch.setattr(fetch_mod, "EARTHDATA_TOKEN", "legacy-token-value")
    monkeypatch.setattr(fetch_mod, "EARTHDATA_USERNAME", "johndoe")
    headers = fetch_mod._auth_headers()  # type: ignore[attr-defined]
    expected = base64.b64encode(b"johndoe:legacy-token-value").decode("ascii")
    assert headers == {"Authorization": f"Basic {expected}"}


def test_no_credentials_yields_empty_headers(monkeypatch: pytest.MonkeyPatch, fetch_mod: object) -> None:
    monkeypatch.setattr(fetch_mod, "EARTHDATA_TOKEN", "")
    monkeypatch.setattr(fetch_mod, "EARTHDATA_USERNAME", "")
    assert fetch_mod._auth_headers() == {}  # type: ignore[attr-defined]
    assert fetch_mod._credentials_available() is False  # type: ignore[attr-defined]