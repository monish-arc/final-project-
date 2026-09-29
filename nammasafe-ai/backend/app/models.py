"""
SQLAlchemy ORM Models for NammaSafe AI (PostgreSQL / PostGIS Compatible)
"""

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
    JSON,
    Date,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="normal_citizen", nullable=False)
    full_name = Column(String, nullable=False)
    designation = Column(String, nullable=True)
    department = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    field_reports = relationship("FieldReport", back_populates="officer")


class Habitation(Base):
    __tablename__ = "habitations"

    id = Column(String, primary_key=True, index=True)
    village_code = Column(String, unique=True, index=True, nullable=False)
    village_name = Column(String, nullable=False)
    district = Column(String, default="Chamoli", nullable=False)
    state = Column(String, default="Uttarakhand", nullable=False)
    population = Column(Integer, nullable=False)
    households = Column(Integer, nullable=False)
    children_count = Column(Integer, default=0)
    elderly_count = Column(Integer, default=0)
    hospital_distance_km = Column(Float, nullable=False)
    road_access_score = Column(Float, default=50.0) # 0-100
    vulnerability_score = Column(Float, default=50.0) # 0-100
    hazard_score = Column(Float, default=50.0) # 0-100
    priority_score = Column(Float, default=50.0) # 0-100
    priority_level = Column(String, default="Medium-Term Relocation")
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    # GeoJSON or WKT location representation
    location_geojson = Column(JSON, nullable=True)
    landslide_risk = Column(Float, default=50.0)
    flood_risk = Column(Float, default=50.0)
    extreme_rainfall_risk = Column(Float, default=50.0)
    past_disaster_frequency = Column(Float, default=50.0)
    disaster_history_count = Column(Integer, default=0)
    notes = Column(Text, nullable=True)

    hazard_events = relationship("HazardEvent", back_populates="habitation")
    recommendations = relationship("RelocationRecommendation", back_populates="habitation")
    field_reports = relationship("FieldReport", back_populates="habitation")


class HazardEvent(Base):
    __tablename__ = "hazard_events"

    id = Column(String, primary_key=True, index=True)
    habitation_id = Column(String, ForeignKey("habitations.id"), nullable=False)
    hazard_type = Column(String, nullable=False) # Landslide, Flash Flood, Subsidence, etc.
    event_date = Column(String, nullable=False)
    intensity = Column(String, nullable=False)
    severity_level = Column(String, default="High")
    affected_people = Column(Integer, default=0)
    houses_damaged = Column(Integer, default=0)
    deaths = Column(Integer, default=0)
    source_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    habitation = relationship("Habitation", back_populates="hazard_events")


class RedZone(Base):
    __tablename__ = "red_zones"

    id = Column(String, primary_key=True, index=True)
    zone_name = Column(String, nullable=False)
    hazard_type = Column(String, nullable=False)
    risk_level = Column(String, default="Critical") # Critical, High, Medium, Low
    hazard_score = Column(Float, default=85.0)
    zone_geometry = Column(JSON, nullable=False) # MultiPolygon GeoJSON
    data_source = Column(String, default="Bhuvan ISRO / State Disaster Management")
    last_updated = Column(String, nullable=False)


class RelocationSite(Base):
    __tablename__ = "relocation_sites"

    id = Column(String, primary_key=True, index=True)
    site_name = Column(String, nullable=False)
    district = Column(String, default="Chamoli", nullable=False)
    land_area_acres = Column(Float, nullable=False)
    estimated_capacity = Column(Integer, nullable=False) # in families
    current_occupancy_families = Column(Integer, default=0)
    water_score = Column(Float, default=80.0)
    road_score = Column(Float, default=80.0)
    school_score = Column(Float, default=80.0)
    hospital_score = Column(Float, default=80.0)
    low_hazard_score = Column(Float, default=90.0)
    flat_land_score = Column(Float, default=85.0)
    suitability_score = Column(Float, default=85.0)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    location_geojson = Column(JSON, nullable=True)
    # Carrying capacity dimensions (families)
    land_capacity_families = Column(Integer, default=500)
    water_capacity_families = Column(Integer, default=500)
    school_capacity_families = Column(Integer, default=400)
    health_capacity_families = Column(Integer, default=450)
    road_capacity_families = Column(Integer, default=600)
    final_capacity_families = Column(Integer, default=400) # min of factors
    available_capacity_families = Column(Integer, default=400)

    recommendations = relationship("RelocationRecommendation", back_populates="relocation_site")


class RelocationRecommendation(Base):
    __tablename__ = "relocation_recommendations"

    id = Column(String, primary_key=True, index=True)
    habitation_id = Column(String, ForeignKey("habitations.id"), nullable=False)
    relocation_site_id = Column(String, ForeignKey("relocation_sites.id"), nullable=False)
    hazard_score = Column(Float, nullable=False)
    vulnerability_score = Column(Float, nullable=False)
    disaster_history_score = Column(Float, nullable=False)
    final_priority_score = Column(Float, nullable=False)
    priority_level = Column(String, nullable=False)
    recommended_families = Column(Integer, default=100)
    risk_reduction_percent = Column(Float, default=80.0)
    explanation = Column(Text, nullable=False)
    status = Column(String, default="Draft") # Draft, Approved, Under Review, In Progress, Completed
    created_at = Column(String, default=lambda: datetime.utcnow().isoformat())

    habitation = relationship("Habitation", back_populates="recommendations")
    relocation_site = relationship("RelocationSite", back_populates="recommendations")


class FieldReport(Base):
    __tablename__ = "field_reports"

    id = Column(String, primary_key=True, index=True)
    habitation_id = Column(String, ForeignKey("habitations.id"), nullable=False)
    officer_id = Column(String, ForeignKey("users.id"), nullable=False)
    report_type = Column(String, nullable=False) # Crack Formation, Landslide, Flash Flood, etc.
    description = Column(Text, nullable=False)
    image_url = Column(String, nullable=True)
    reported_at = Column(String, default=lambda: datetime.utcnow().isoformat())
    verified = Column(Boolean, default=False)
    severity = Column(String, default="High")
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)

    habitation = relationship("Habitation", back_populates="field_reports")
    officer = relationship("User", back_populates="field_reports")


class HistoricalHazardObservation(Base):
    """
    Imported previous-year hazard/rainfall observations (Kerala pilot).

    Every row is historical provenance data — never real-time.  The import
    process is idempotent thanks to the composite unique constraint on
    (district_id, observation_date, data_year, source_reference).

    hazard_type is intentionally free-form to support future hazard kinds
    (flood, landslide, extreme rainfall, cyclone, ...) without a schema change;
    rainfall observations default to 'rainfall'.
    """

    __tablename__ = "historical_hazard_observations"
    __table_args__ = (
        UniqueConstraint(
            "district_id",
            "observation_date",
            "data_year",
            "source_reference",
            name="uq_historical_obs_district_date_year_source",
        ),
        Index("ix_historical_obs_district_id", "district_id"),
        Index("ix_historical_obs_observation_date", "observation_date"),
        Index("ix_historical_obs_hazard_type", "hazard_type"),
        Index("ix_historical_obs_data_year", "data_year"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    district_id = Column(Integer, nullable=False)  # LGD code (554-567 for Kerala)
    district = Column(String, nullable=False)  # denormalized display name
    observation_date = Column(Date, nullable=False)
    hazard_type = Column(String, nullable=False, default="rainfall")
    rainfall_mm = Column(Float, nullable=False)
    source = Column(String, nullable=False)
    source_reference = Column(String, nullable=False, default="")
    data_year = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class TerrainSample(Base):
    """
    Persistent cache of validated NASA Earthdata SRTM elevation samples.

    Only LIVE NASA SRTM payloads are stored (never fallback or unavailable
    states), keyed on a ~55 m grid so nearby queries reuse one sample instead
    of downloading the same ~26 MB tile again. `geometry` mirrors the PostGIS
    point so production can index spatially; SQLite ignores the column value
    (the migration adds it only on PostgreSQL/PostGIS).
    """

    __tablename__ = "terrain_samples"
    __table_args__ = (
        UniqueConstraint(
            "latitude",
            "longitude",
            "data_source",
            name="uq_terrain_sample_grid_source",
        ),
        Index("ix_terrain_samples_lat_lng", "latitude", "longitude"),
        Index("ix_terrain_samples_source", "data_source"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    # PostGIS POINT(4326); populated only on PostgreSQL/PostGIS (see migration 004).
    geometry = Column(JSON, nullable=True)
    elevation_m = Column(Float, nullable=True)
    slope_degrees = Column(Float, nullable=True)
    slope_percent = Column(Float, nullable=True)
    slope_category = Column(String, nullable=True)
    elevation_change_m = Column(Float, nullable=True)
    slope_window_arcsec = Column(Integer, nullable=True)
    dataset = Column(String, nullable=True)
    data_source = Column(String, nullable=False)
    provider = Column(String, nullable=True)
    data_status = Column(String, nullable=False, default="LIVE")
    computed_at = Column(DateTime, default=datetime.utcnow)


class HistoricalWeatherSample(Base):
    """
    Persistent cache of validated historical weather samples (ERA5 archive).

    Only real reanalysis values are stored (data_status HISTORICAL), keyed on
    the rounded cell / year / month / day / variable / aggregation so repeated
    completed-month and per-day views reuse one archive fetch instead of
    hammering the upstream. data_day == 0 means the whole-month aggregate;
    data_day in 1..N means that single day of the month. Aggregation labels the
    summarisation (monthly_total, monthly_mean, daily_total, ...) so a value is
    never confused for a live observation.
    """

    __tablename__ = "historical_weather_samples"
    __table_args__ = (
        UniqueConstraint(
            "latitude",
            "longitude",
            "data_year",
            "data_month",
            "data_day",
            "variable",
            "aggregation",
            "data_source",
            name="uq_hist_weather_cell_period_variable_agg_source",
        ),
        Index(
            "ix_hist_weather_cell_period",
            "latitude",
            "longitude",
            "data_year",
            "data_month",
            "data_day",
        ),
        Index("ix_hist_weather_year_month", "data_year", "data_month"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    data_year = Column(Integer, nullable=False)
    data_month = Column(Integer, nullable=False)
    data_day = Column(Integer, nullable=False, default=0)  # 0 = whole month, 1..N = that day
    variable = Column(String, nullable=False)  # ERA5 variable key (temperature_2m, precipitation, ...)
    aggregation = Column(String, nullable=False)
    value = Column(Float, nullable=True)
    data_source = Column(String, nullable=False)  # e.g. "Open-Meteo ERA5 Archive"
    dataset = Column(String, nullable=True)
    provider = Column(String, nullable=True)
    data_status = Column(String, nullable=False, default="HISTORICAL")
    computed_at = Column(DateTime, default=datetime.utcnow)


class AdminBoundary(Base):
    """
    Official administrative boundaries (state / district / block) imported from
    real shapefiles via scripts/import_admin_boundaries.py.

    Rows are idempotent on (level, name, state); every row records the official
    source reference so geometry can be traced to the supplied file.
    """

    __tablename__ = "admin_boundaries"
    __table_args__ = (
        UniqueConstraint("level", "name", "state", name="uq_admin_boundary_level_name_state"),
        Index("ix_admin_boundaries_code", "code"),
        Index("ix_admin_boundaries_level", "level"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    level = Column(Integer, nullable=False)  # 4 = state, 5 = district, 6 = block/sub-district
    name = Column(String, nullable=False)
    state = Column(String, nullable=True)
    district = Column(String, nullable=True)
    code = Column(String, nullable=True)  # LGD / census code when present in the source
    geometry_geojson = Column(JSON, nullable=True)
    centroid_lat = Column(Float, nullable=True)
    centroid_lng = Column(Float, nullable=True)
    data_source = Column(String, nullable=False)
    source_reference = Column(String, nullable=False, default="")
    data_status = Column(String, nullable=False, default="OFFICIAL")
    imported_at = Column(DateTime, default=datetime.utcnow)


class CensusVillage(Base):
    """
    Census 2011 village-level population & household figures imported from real
    Census of India CSV files via scripts/import_census_2011.py.

    Rows are idempotent on (village_code, data_year).
    """

    __tablename__ = "census_villages"
    __table_args__ = (
        UniqueConstraint("village_code", "data_year", name="uq_census_village_code_year"),
        Index("ix_census_villages_district", "district"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    village_code = Column(String, nullable=False, index=True)
    village_name = Column(String, nullable=False)
    district = Column(String, nullable=True)
    state = Column(String, nullable=True)
    total_population = Column(Integer, nullable=True)
    total_households = Column(Integer, nullable=True)
    male_population = Column(Integer, nullable=True)
    female_population = Column(Integer, nullable=True)
    child_population = Column(Integer, nullable=True)
    area_km2 = Column(Float, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    data_year = Column(Integer, nullable=False, default=2011)
    data_source = Column(String, nullable=False, default="Census of India 2011")
    source_reference = Column(String, nullable=False, default="")
    imported_at = Column(DateTime, default=datetime.utcnow)


class DisasterEvent(Base):
    """
    Real, well-documented past disaster events across India (curated seed).

    This is provenance data for the historical risk signal and for the "Red
    Zone / hazard susceptibility" reasoning — every row must carry a public
    source reference. Rows are inserted idempotently via
    backend/scripts/seed_disaster_events.py (--dry-run supported).
    """

    __tablename__ = "disaster_events"
    __table_args__ = (
        UniqueConstraint(
            "name",
            "event_date",
            "source_reference",
            name="uq_disaster_event_name_date_source",
        ),
        Index("ix_disaster_events_event_date", "event_date"),
        Index("ix_disaster_events_hazard_type", "hazard_type"),
        Index("ix_disaster_events_state", "state"),
        Index("ix_disaster_events_district", "district"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    hazard_type = Column(String, nullable=False)  # FLOOD, LANDSLIDE, CYCLONE, ...
    event_date = Column(Date, nullable=False)
    state = Column(String, nullable=False)
    district = Column(String, nullable=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    severity_level = Column(String, nullable=True)
    affected_population = Column(Integer, nullable=True)
    fatalities = Column(Integer, nullable=True)
    damage_estimate_inr_crore = Column(Float, nullable=True)
    description = Column(Text, nullable=True)
    source = Column(String, nullable=False)
    source_reference = Column(String, nullable=False, default="")
    data_status = Column(String, nullable=False, default="HISTORICAL")
    created_at = Column(DateTime, default=datetime.utcnow)
