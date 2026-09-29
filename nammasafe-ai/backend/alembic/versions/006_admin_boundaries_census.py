"""admin_boundaries + census_villages

Revision ID: 006_admin_boundaries_census
Revises: 005_historical_weather_samples
Create Date: 2026-09-26

Tables for Phase-E real-data ingestion:
  * admin_boundaries  — official boundaries from scripts/import_admin_boundaries.py
  * census_villages   — Census 2011 village statistics from scripts/import_census_2011.py
"""

from alembic import op
import sqlalchemy as sa

revision = "006_admin_boundaries_census"
down_revision = "005_historical_weather_samples"
branch_labels = None
depends_on = None


def _boundaries(op=None):
    return sa.table(
        "admin_boundaries",
        sa.column("id", sa.Integer),
        sa.column("level", sa.Integer),
        sa.column("name", sa.String),
        sa.column("state", sa.String),
        sa.column("district", sa.String),
        sa.column("code", sa.String),
        sa.column("geometry_geojson", sa.JSON),
        sa.column("centroid_lat", sa.Float),
        sa.column("centroid_lng", sa.Float),
        sa.column("data_source", sa.String),
        sa.column("source_reference", sa.String),
        sa.column("data_status", sa.String),
        sa.column("imported_at", sa.DateTime),
    )


def _villages(op=None):
    return sa.table(
        "census_villages",
        sa.column("id", sa.Integer),
        sa.column("village_code", sa.String),
        sa.column("village_name", sa.String),
        sa.column("district", sa.String),
        sa.column("state", sa.String),
        sa.column("total_population", sa.Integer),
        sa.column("total_households", sa.Integer),
        sa.column("male_population", sa.Integer),
        sa.column("female_population", sa.Integer),
        sa.column("child_population", sa.Integer),
        sa.column("area_km2", sa.Float),
        sa.column("latitude", sa.Float),
        sa.column("longitude", sa.Float),
        sa.column("data_year", sa.Integer),
        sa.column("data_source", sa.String),
        sa.column("source_reference", sa.String),
        sa.column("imported_at", sa.DateTime),
    )


def upgrade() -> None:
    op.create_table(
        "admin_boundaries",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("level", sa.Integer, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("state", sa.String, nullable=True),
        sa.Column("district", sa.String, nullable=True),
        sa.Column("code", sa.String, nullable=True),
        sa.Column("geometry_geojson", sa.JSON, nullable=True),
        sa.Column("centroid_lat", sa.Float, nullable=True),
        sa.Column("centroid_lng", sa.Float, nullable=True),
        sa.Column("data_source", sa.String, nullable=False),
        sa.Column("source_reference", sa.String, nullable=False, server_default=""),
        sa.Column("data_status", sa.String, nullable=False, server_default="OFFICIAL"),
        sa.Column("imported_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("level", "name", "state", name="uq_admin_boundary_level_name_state"),
    )
    op.create_index("ix_admin_boundaries_code", "admin_boundaries", ["code"])
    op.create_index("ix_admin_boundaries_level", "admin_boundaries", ["level"])

    op.create_table(
        "census_villages",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("village_code", sa.String, nullable=False),
        sa.Column("village_name", sa.String, nullable=False),
        sa.Column("district", sa.String, nullable=True),
        sa.Column("state", sa.String, nullable=True),
        sa.Column("total_population", sa.Integer, nullable=True),
        sa.Column("total_households", sa.Integer, nullable=True),
        sa.Column("male_population", sa.Integer, nullable=True),
        sa.Column("female_population", sa.Integer, nullable=True),
        sa.Column("child_population", sa.Integer, nullable=True),
        sa.Column("area_km2", sa.Float, nullable=True),
        sa.Column("latitude", sa.Float, nullable=True),
        sa.Column("longitude", sa.Float, nullable=True),
        sa.Column("data_year", sa.Integer, nullable=False, server_default="2011"),
        sa.Column("data_source", sa.String, nullable=False, server_default="Census of India 2011"),
        sa.Column("source_reference", sa.String, nullable=False, server_default=""),
        sa.Column("imported_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("village_code", "data_year", name="uq_census_village_code_year"),
    )
    op.create_index("ix_census_villages_district", "census_villages", ["district"])


def downgrade() -> None:
    op.drop_index("ix_census_villages_district", table_name="census_villages")
    op.drop_table("census_villages")
    op.drop_index("ix_admin_boundaries_level", table_name="admin_boundaries")
    op.drop_index("ix_admin_boundaries_code", table_name="admin_boundaries")
    op.drop_table("admin_boundaries")