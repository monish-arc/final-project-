"""historical_weather_samples cache table (ERA5 archive persistent cache)

Revision ID: 005_historical_weather_samples
Revises: 004_terrain_samples
Create Date: 2026-09-26 00:00:00.000000

The Open-Meteo ERA5 archive provider caches validated HISTORICAL reanalysis
samples to this table on a per cell / year / month / variable / aggregation
key, so completed-month views reuse one archive fetch. Values are real ERA5
reanalysis only — data_status is always HISTORICAL, never live.
"""
from alembic import op
import sqlalchemy as sa

revision = "005_historical_weather_samples"
down_revision = "004_terrain_samples"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "historical_weather_samples",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("data_year", sa.Integer(), nullable=False),
        sa.Column("data_month", sa.Integer(), nullable=False),
        sa.Column("variable", sa.String(), nullable=False),
        sa.Column("aggregation", sa.String(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("data_source", sa.String(), nullable=False),
        sa.Column("dataset", sa.String(), nullable=True),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("data_status", sa.String(), nullable=False, server_default="HISTORICAL"),
        sa.Column("computed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "latitude",
            "longitude",
            "data_year",
            "data_month",
            "variable",
            "aggregation",
            "data_source",
            name="uq_hist_weather_cell_period_variable_agg_source",
        ),
    )
    op.create_index(
        "ix_hist_weather_cell_period",
        "historical_weather_samples",
        ["latitude", "longitude", "data_year", "data_month"],
    )
    op.create_index("ix_hist_weather_year_month", "historical_weather_samples", ["data_year", "data_month"])


def downgrade() -> None:
    op.drop_table("historical_weather_samples")