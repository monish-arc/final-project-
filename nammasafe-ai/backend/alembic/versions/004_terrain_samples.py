"""terrain_samples cache table (NASA SRTM persistent point cache)

Revision ID: 004_terrain_samples
Revises: 003_disaster_events
Create Date: 2026-09-21 00:00:00.000000

The live NASA Earthdata SRTM service caches validated LIVE samples to this
table on a ~55 m grid. `geometry` is PostGIS-only: migration 001-style
AddGeometryColumn runs only on PostgreSQL; SQLite uses the ORM's nullable
JSON column and never executes the PostGIS DDL.
"""
from alembic import op
import sqlalchemy as sa

revision = "004_terrain_samples"
down_revision = "003_disaster_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "terrain_samples",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("elevation_m", sa.Float(), nullable=True),
        sa.Column("slope_degrees", sa.Float(), nullable=True),
        sa.Column("slope_percent", sa.Float(), nullable=True),
        sa.Column("slope_category", sa.String(), nullable=True),
        sa.Column("elevation_change_m", sa.Float(), nullable=True),
        sa.Column("slope_window_arcsec", sa.Integer(), nullable=True),
        sa.Column("dataset", sa.String(), nullable=True),
        sa.Column("data_source", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("data_status", sa.String(), nullable=False, server_default="LIVE"),
        sa.Column("computed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("latitude", "longitude", "data_source", name="uq_terrain_sample_grid_source"),
    )
    op.create_index("ix_terrain_samples_lat_lng", "terrain_samples", ["latitude", "longitude"])
    op.create_index("ix_terrain_samples_source", "terrain_samples", ["data_source"])
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SELECT AddGeometryColumn('terrain_samples', 'geometry', 4326, 'POINT', 2);")
        op.execute(
            "CREATE INDEX idx_terrain_samples_geom ON terrain_samples USING GIST (geometry);"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP INDEX IF EXISTS idx_terrain_samples_geom;"
        )
        op.execute("SELECT DropGeometryColumn('terrain_samples', 'geometry');")
    op.drop_table("terrain_samples")