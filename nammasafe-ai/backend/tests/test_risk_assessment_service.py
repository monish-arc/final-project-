"""
Risk-assessment engine tests: weighting, normalisation (missing signals never
deflate), band mapping, disaster-type inference, and ML fallback semantics.
"""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, DisasterEvent
from app.ml_model import ModelRegistry
from app.risk_assessment_service import RiskAssessmentService, band_for

LAT, LNG = 30.43, 79.56


class FakeWeather:
    def get_weather(self, lat, lng):
        if getattr(self, "fail", False):
            return {"data_status": "UNAVAILABLE", "current": None}
        return {
            "data_status": "LIVE",
            "current": {"precipitation_mm": 18.0, "weather_code": 63},
        }


class FakeRainfall:
    def get_rainfall(self, lat, lng):
        if getattr(self, "fail", False):
            return {"data_status": "NOT_CONFIGURED"}
        return {"data_status": "LIVE", "precipitation_mm_hour": 10.0, "dataset": "3B-HHR..."}


class FakeFlood:
    def get_flood_risk(self, lat, lng):
        if getattr(self, "fail", False):
            return {"data_status": "NOT_CONFIGURED"}
        return {"data_status": "LIVE", "discharge_band": "ELEVATED", "river_discharge_m3s": 4200.0, "dataset": "glofas.nc", "data_source": "Copernicus GloFAS"}


class FakeTerrain:
    def get_terrain(self, lat, lng):
        if getattr(self, "fail", False):
            return {"data_status": "UNAVAILABLE"}
        return {"data_status": "LIVE", "elevation_m": 1950.0, "slope_percent": 12.0,
                "slope_category": "MODERATELY_SLOPING",
                "data_source": "NASA SRTMGL1.003 (LP DAAC Earthdata Cloud)",
                "provider": "nasa", "dataset": "NASA SRTMGL1.003"}


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(DisasterEvent(
        name="Chamoli glacier burst", hazard_type="LANDSLIDE",
        event_date=date(2021, 2, 7), state="Uttarakhand", district="Chamoli",
        latitude=30.4340, longitude=79.7250, severity_level="EXTREME",
        affected_population=10000, source="NDMA", source_reference="https://ndma.gov.in",
        data_status="HISTORICAL",
    ))
    session.commit()
    yield session
    session.close()


def _service(db, mode="rule_based", model_path=""):
    svc = RiskAssessmentService(model_registry=ModelRegistry(mode=mode, model_path=model_path))
    svc._weather = FakeWeather()
    svc._rainfall = FakeRainfall()
    svc._flood = FakeFlood()
    svc._terrain = FakeTerrain()
    return svc


def test_band_mapping():
    assert band_for(0)["band"] == "LOW"
    assert band_for(30.0)["band"] == "LOW"
    assert band_for(31.0)["band"] == "MEDIUM"
    assert band_for(60.0)["band"] == "MEDIUM"
    assert band_for(61.0)["band"] == "HIGH"
    assert band_for(80.0)["band"] == "HIGH"
    assert band_for(81.0)["band"] == "CRITICAL"
    assert band_for(100.0)["band"] == "CRITICAL"


def test_full_assessment_rule_based(db):
    svc = _service(db)
    result = svc.assess(db, LAT, LNG, place_label="Test Village", state="Uttarakhand", district="Chamoli")

    assert result["risk_score"] is not None
    assert 0 <= result["risk_score"] <= 100
    assert result["risk_band"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert result["assessment_mode"] == "rule_based"
    assert result["factors"], "must include factor breakdown"
    keys = {f["key"] for f in result["factors"]}
    assert keys == {"rainfall", "water", "elevation", "historical", "proximity", "field_damage", "lulc", "geoid"}
    assert any(f["impact"] == "ATTRIBUTABLE" for f in result["factors"])
    assert result["model_status"] == "RULE_BASED"
    assert result["disaster_type"] in ("FLOOD", "LANDSLIDE", "CYCLONE", "COASTAL_FLOOD", "FLASH_FLOOD")
    assert result["caveat"]  # honesty contract
    assert result["sources"]


def test_elevation_factor_carries_nasa_provenance(db):
    result = _service(db).assess(db, LAT, LNG, place_label="Test Village", state="Uttarakhand", district="Chamoli")
    elevation = next(f for f in result["factors"] if f["key"] == "elevation")
    assert elevation["impact"] == "ATTRIBUTABLE"
    assert elevation["source"]["name"] == "NASA SRTMGL1.003 (LP DAAC Earthdata Cloud)"
    assert elevation["source"]["status"] == "LIVE"


def test_missing_signals_never_deflate(db):
    svc = _service(db)
    svc._weather.fail = True
    svc._rainfall.fail = True
    svc._flood.fail = True
    svc._terrain.fail = True

    result = svc.assess(db, LAT, LNG, field_reports=[])

    unavailable = [f for f in result["factors"] if f["impact"] == "NOT_AVAILABLE"]
    assert len(unavailable) == 5  # rainfall, water, elevation + lulc, geoid (Bhuvan gated off)
    # The remaining signals (historical, proximity, field_damage) still yield a score.
    assert result["risk_score"] is not None


def test_no_available_signals_yields_unknown(db):
    svc = _service(db)
    for backend in (svc._weather, svc._rainfall, svc._flood, svc._terrain):
        backend.fail = True

    # With no historical events *and* no live layers a score cannot be computed.
    result = svc.assess(db, 19.07, 72.87, field_reports=[])
    assert result["risk_band"] in ("LOW", "MEDIUM", "UNKNOWN")

    result2 = svc.assess(db, 19.07, 72.87, field_reports=[])
    assert result2["risk_band"] in ("LOW", "MEDIUM", "UNKNOWN")


def test_ml_mode_falls_back_transparently(db):
    svc = _service(db, mode="ml", model_path="")
    result = svc.assess(db, LAT, LNG)

    assert result["assessment_mode"] == "ml"
    # No model configured -> rule score still produced, status NOT_CONFIGURED.
    assert result["model_status"] == "NOT_CONFIGURED"
    assert result["risk_score"] is not None


class FakeMlRegistry(ModelRegistry):
    model_status = "LOADED"
    model_version = "onnx@model.onnx"

    def predict(self, features):
        return {
            "risk_score": 88.0,
            "model_status": self.model_status,
            "model_version": self.model_version,
            "prediction_timestamp": "2025-09-18T00:00:00Z",
            "input_data_timestamp": features.get("_input_timestamp", "2025-09-18T00:00:00Z"),
        }


def test_ml_primary_when_model_loaded(db):
    svc = RiskAssessmentService(model_registry=FakeMlRegistry(mode="ml"))
    svc._weather = FakeWeather()
    svc._rainfall = FakeRainfall()
    svc._flood = FakeFlood()
    svc._terrain = FakeTerrain()

    result = svc.assess(db, LAT, LNG)
    assert result["assessment_mode"] == "ml"
    assert result["risk_score"] == 88.0
    assert result["risk_band"] == "CRITICAL"
    assert result["model_version"] == "onnx@model.onnx"


def test_field_damage_raises_score(db):
    baseline = _service(db).assess(db, LAT, LNG, field_reports=[])
    reports = [
        {"latitude": LAT, "longitude": LNG, "severity": "Critical", "verified": True},
        {"latitude": LAT, "longitude": LNG, "severity": "High", "verified": True},
    ]
    with_damage = _service(db).assess(db, LAT, LNG, field_reports=reports)
    assert with_damage["risk_score"] > baseline["risk_score"]