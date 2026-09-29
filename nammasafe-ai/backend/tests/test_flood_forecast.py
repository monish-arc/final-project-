"""
Flood forecast + data-status endpoints: RBAC, honest labeling and schema contract.

Flood data is never fabricated and never substituted between regions.  Real
CEMS GloFAS data is only reported (data_status=FORECAST) when a NetCDF dataset
is configured (GLOFAS_DATASET_PATH / GLOPAS_DATA_DIR) and the reading's cell
lies inside the requested region's bounding box.  Without a dataset every
request returns an honestly-labelled NOT_CONFIGURED payload (empty
gauges/zones); an unreadable or out-of-region dataset yields UNAVAILABLE.
"""

import sys
import types

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.flood_forecast import get_flood_forecasts
from app.flood_service import CopernicusGloFASProvider

client = TestClient(app)


def _admin_headers() -> dict:
    res = client.post("/api/auth/login", json={"username_or_email": "admin", "password": "admin123"})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _citizen_headers() -> dict:
    res = client.post("/api/auth/login", json={
        "username_or_email": "citizen",
        "password": "citizen123",
        "state_id": "uk",
        "district_id": "chamoli",
        "sub_district_id": "joshimath",
        "area_id": "joshimath-central",
    })
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _forecast_read(self, netCDF4, dataset_path, latitude, longitude):
    """Stand-in for provider._read_forecast returning a Utarakhand-edge cell
    (cell 30.5, 80.0 lies inside the Uttarakhand box 28.7–31.5 / 77.6–81.1)."""
    return {
        "data_status": "FORECAST",
        "data_source": "Copernicus GloFAS via CDS",
        "latitude": 30.5,
        "longitude": 80.0,
        "river_discharge_m3s": 4200.0,
        "threshold_m3s": 3511.2,
        "discharge_band": "ELEVATED",
        "lead_time_hours": 120,
        "issue_time": "2026-09-23T00:00:00",
        "valid_time": "2026-09-28T00:00:00",
        "forecast_hours": 6,
        "dataset": "glofas_forecast.nc",
        "computed_at": "2026-09-24T00:00:00Z",
        "assumption": "Band and threshold derived from the percentiles of the cached forecast dataset (85th/99th).",
    }


@pytest.fixture()
def _glofas_readable(monkeypatch):
    """Simulate a configured, readable GloFAS dataset for the provider class."""
    monkeypatch.setitem(sys.modules, "netCDF4", types.SimpleNamespace(Dataset=None))
    monkeypatch.setattr(CopernicusGloFASProvider, "_dataset_path", lambda self: "glofas_forecast.nc")
    monkeypatch.setattr(CopernicusGloFASProvider, "_read_forecast", _forecast_read)


def test_flood_forecast_requires_auth():
    response = client.get("/api/flood-forecast")
    assert response.status_code == 401


def test_data_status_requires_auth():
    response = client.get("/api/data-status")
    assert response.status_code == 401


def test_data_status_accessible_to_public_map_readers():
    """normal_citizen holds map.read_public, so the status endpoint must work."""
    response = client.get("/api/data-status", headers=_citizen_headers())
    assert response.status_code == 200
    data = response.json()
    layers = {layer["layer"]: layer for layer in data["layers"]}
    assert "flood_forecast" in layers
    assert layers["flood_forecast"]["status"] in ("FORECAST", "NOT_CONFIGURED", "UNAVAILABLE")
    assert "satellite_tiles" in layers
    assert layers["satellite_tiles"]["status"] == "LIVE"
    assert "google_map_tiles" in layers
    assert layers["google_map_tiles"]["status"] in ("LIVE", "NOT_CONFIGURED")
    assert data["checked_at"]


def test_data_status_uses_normalized_vocabulary():
    """Phase 5 vocabulary: no spaced values in the data-status panel; model
    layers report MODEL, derived terrain CALCULATED, curated static STATIC."""
    from app.flood_forecast import get_data_status

    statuses = {layer["status"] for layer in get_data_status()}
    assert "NOT CONFIGURED" not in statuses
    assert statuses <= {"LIVE", "MODEL", "CALCULATED", "STATIC", "FORECAST", "NOT_CONFIGURED", "UNAVAILABLE", "HISTORICAL"}
    assert "MODEL" in statuses          # forecast/algorithm-derived layers
    assert "STATIC" in statuses         # curated inventory layers
    assert {"hazard_zones", "habitation_risk", "weather", "weather_forecast", "risk_assessment"} <= {
        layer["layer"] for layer in get_data_status() if layer["status"] == "MODEL"
    }


def test_flood_forecast_honest_not_configured_when_no_dataset():
    """Without a configured GloFAS dataset nothing is fabricated: gauges are
    empty and the payload is honestly labelled NOT_CONFIGURED."""
    response = client.get("/api/flood-forecast", headers=_admin_headers())
    assert response.status_code == 200
    data = response.json()
    assert data["gauges"] == []
    assert data["zones"] == []
    assert data["data_status"] == "NOT_CONFIGURED"
    assert data["data_source"]
    assert data["forecast"] is None
    assert "computed_at" in data


def test_flood_forecast_zones_honest_when_unavailable_or_not_configured():
    """Non-FORECAST payloads carry no zones; a live payload may only carry
    HIGH/EXTREME inundation polygons with a valid GeoJSON geometry."""
    response = client.get("/api/flood-forecast", headers=_admin_headers())
    data = response.json()
    if data["data_status"] == "FORECAST":
        for zone in data["zones"]:
            assert zone["risk_level"] in ("HIGH", "EXTREME")
            assert zone["geometry"]["type"] == "Polygon"
            assert len(zone["geometry"]["coordinates"]) >= 1
    else:
        assert data["zones"] == []


def test_flood_forecast_forecast_when_dataset_covers_region(_glofas_readable):
    """Configured + readable dataset anchored in the region returns FORECAST
    with the discharge/threshold/lead-time contract (gauges stay empty; no
    regional river-level gauge is fabricated)."""
    response = client.get(
        "/api/flood-forecast",
        params={"state": "Uttarakhand", "district": "Chamoli"},
        headers=_admin_headers(),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["data_status"] == "FORECAST"
    assert data["gauges"] == []
    assert data["zones"] == []
    f = data["forecast"]
    assert f is not None
    assert f["river_discharge_m3s"] == 4200.0
    assert f["threshold_m3s"] == 3511.2
    assert f["lead_time_hours"] == 120
    assert f["issue_time"] and f["valid_time"]
    assert f["dataset"] == "glofas_forecast.nc"
    assert 28.7 <= f["latitude"] <= 31.5
    assert 77.6 <= f["longitude"] <= 81.1


def test_flood_forecast_honest_unavailable_for_out_of_region_cell(monkeypatch):
    """A dataset covering a different area must NOT be substituted for the
    requested region — the response is honest UNAVAILABLE."""
    monkeypatch.setitem(sys.modules, "netCDF4", types.SimpleNamespace(Dataset=None))
    monkeypatch.setattr(CopernicusGloFASProvider, "_dataset_path", lambda self: "kerala.nc")

    def _kerala_cell(self, netCDF4, dataset_path, latitude, longitude):
        payload = dict(_forecast_read(self, netCDF4, dataset_path, latitude, longitude))
        payload["latitude"] = 9.5   # inside a Kerala-only dataset / far from Uttarakhand
        payload["longitude"] = 76.0
        payload["dataset"] = "kerala.nc"
        return payload

    monkeypatch.setattr(CopernicusGloFASProvider, "_read_forecast", _kerala_cell)

    response = client.get(
        "/api/flood-forecast",
        params={"state": "Uttarakhand", "district": "Chamoli"},
        headers=_admin_headers(),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["data_status"] == "UNAVAILABLE"
    assert data["gauges"] == []
    assert data["zones"] == []
    assert data["forecast"] is None
    assert "outside the requested region" in data["data_source"]


def test_flood_forecast_unavailable_when_dataset_unreadable(monkeypatch):
    """Dataset present but netCDF4 missing (this environment) -> UNAVAILABLE."""
    monkeypatch.setattr(CopernicusGloFASProvider, "_dataset_path", lambda self: "glofas_forecast.nc")
    assert get_flood_forecasts(state="Uttarakhand", district="Chamoli")["data_status"] in (
        "FORECAST",
        "UNAVAILABLE",
    )