"""Initial PostGIS schema and spatial indexes

Revision ID: 001_initial_schema
Revises: 
Create Date: 2025-08-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Ensure PostGIS extension is enabled
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis;")

    # 1. Users
    op.create_table(
        'users',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('username', sa.String(), unique=True, nullable=False),
        sa.Column('email', sa.String(), unique=True, nullable=False),
        sa.Column('hashed_password', sa.String(), nullable=False),
        sa.Column('role', sa.String(), nullable=False, server_default='viewer'),
        sa.Column('full_name', sa.String(), nullable=False),
        sa.Column('designation', sa.String(), nullable=True),
        sa.Column('department', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
    )

    # 2. Habitations
    op.create_table(
        'habitations',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('village_code', sa.String(), unique=True, nullable=False),
        sa.Column('village_name', sa.String(), nullable=False),
        sa.Column('district', sa.String(), nullable=False, server_default='Chamoli'),
        sa.Column('state', sa.String(), nullable=False, server_default='Uttarakhand'),
        sa.Column('population', sa.Integer(), nullable=False),
        sa.Column('households', sa.Integer(), nullable=False),
        sa.Column('children_count', sa.Integer(), server_default='0'),
        sa.Column('elderly_count', sa.Integer(), server_default='0'),
        sa.Column('hospital_distance_km', sa.Float(), nullable=False),
        sa.Column('road_access_score', sa.Float(), server_default='50.0'),
        sa.Column('vulnerability_score', sa.Float(), server_default='50.0'),
        sa.Column('hazard_score', sa.Float(), server_default='50.0'),
        sa.Column('priority_score', sa.Float(), server_default='50.0'),
        sa.Column('priority_level', sa.String(), server_default='Medium-Term Relocation'),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
        sa.Column('landslide_risk', sa.Float(), server_default='50.0'),
        sa.Column('flood_risk', sa.Float(), server_default='50.0'),
        sa.Column('extreme_rainfall_risk', sa.Float(), server_default='50.0'),
        sa.Column('past_disaster_frequency', sa.Float(), server_default='50.0'),
        sa.Column('disaster_history_count', sa.Integer(), server_default='0'),
        sa.Column('notes', sa.Text(), nullable=True),
    )
    # Add PostGIS geometry column and GIST spatial index
    op.execute("SELECT AddGeometryColumn('habitations', 'location', 4326, 'POINT', 2);")
    op.execute("UPDATE habitations SET location = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326);")
    op.execute("CREATE INDEX idx_habitations_location ON habitations USING GIST (location);")

    # 3. Hazard Events
    op.create_table(
        'hazard_events',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('habitation_id', sa.String(), sa.ForeignKey('habitations.id'), nullable=False),
        sa.Column('hazard_type', sa.String(), nullable=False),
        sa.Column('event_date', sa.String(), nullable=False),
        sa.Column('intensity', sa.String(), nullable=False),
        sa.Column('severity_level', sa.String(), server_default='High'),
        sa.Column('affected_people', sa.Integer(), server_default='0'),
        sa.Column('houses_damaged', sa.Integer(), server_default='0'),
        sa.Column('deaths', sa.Integer(), server_default='0'),
        sa.Column('source_url', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
    )

    # 4. Red Zones
    op.create_table(
        'red_zones',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('zone_name', sa.String(), nullable=False),
        sa.Column('hazard_type', sa.String(), nullable=False),
        sa.Column('risk_level', sa.String(), server_default='Critical'),
        sa.Column('hazard_score', sa.Float(), nullable=False),
        sa.Column('data_source', sa.String(), nullable=False),
        sa.Column('last_updated', sa.String(), nullable=False),
    )
    op.execute("SELECT AddGeometryColumn('red_zones', 'zone_geometry', 4326, 'MULTIPOLYGON', 2);")
    op.execute("CREATE INDEX idx_red_zones_geom ON red_zones USING GIST (zone_geometry);")

    # 5. Relocation Sites
    op.create_table(
        'relocation_sites',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('site_name', sa.String(), nullable=False),
        sa.Column('district', sa.String(), nullable=False, server_default='Chamoli'),
        sa.Column('land_area_acres', sa.Float(), nullable=False),
        sa.Column('estimated_capacity', sa.Integer(), nullable=False),
        sa.Column('current_occupancy_families', sa.Integer(), server_default='0'),
        sa.Column('water_score', sa.Float(), server_default='80.0'),
        sa.Column('road_score', sa.Float(), server_default='80.0'),
        sa.Column('school_score', sa.Float(), server_default='80.0'),
        sa.Column('hospital_score', sa.Float(), server_default='80.0'),
        sa.Column('low_hazard_score', sa.Float(), server_default='90.0'),
        sa.Column('flat_land_score', sa.Float(), server_default='85.0'),
        sa.Column('suitability_score', sa.Float(), server_default='85.0'),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
        sa.Column('land_capacity_families', sa.Integer(), server_default='500'),
        sa.Column('water_capacity_families', sa.Integer(), server_default='500'),
        sa.Column('school_capacity_families', sa.Integer(), server_default='400'),
        sa.Column('health_capacity_families', sa.Integer(), server_default='450'),
        sa.Column('road_capacity_families', sa.Integer(), server_default='600'),
        sa.Column('final_capacity_families', sa.Integer(), server_default='400'),
        sa.Column('available_capacity_families', sa.Integer(), server_default='400'),
    )
    op.execute("SELECT AddGeometryColumn('relocation_sites', 'location', 4326, 'POINT', 2);")
    op.execute("UPDATE relocation_sites SET location = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326);")
    op.execute("CREATE INDEX idx_relocation_sites_location ON relocation_sites USING GIST (location);")

    # 6. Relocation Recommendations
    op.create_table(
        'relocation_recommendations',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('habitation_id', sa.String(), sa.ForeignKey('habitations.id'), nullable=False),
        sa.Column('relocation_site_id', sa.String(), sa.ForeignKey('relocation_sites.id'), nullable=False),
        sa.Column('hazard_score', sa.Float(), nullable=False),
        sa.Column('vulnerability_score', sa.Float(), nullable=False),
        sa.Column('disaster_history_score', sa.Float(), nullable=False),
        sa.Column('final_priority_score', sa.Float(), nullable=False),
        sa.Column('priority_level', sa.String(), nullable=False),
        sa.Column('recommended_families', sa.Integer(), server_default='100'),
        sa.Column('risk_reduction_percent', sa.Float(), server_default='80.0'),
        sa.Column('explanation', sa.Text(), nullable=False),
        sa.Column('status', sa.String(), server_default='Draft'),
        sa.Column('created_at', sa.String(), nullable=False),
    )

    # 7. Field Reports
    op.create_table(
        'field_reports',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('habitation_id', sa.String(), sa.ForeignKey('habitations.id'), nullable=False),
        sa.Column('officer_id', sa.String(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('report_type', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('image_url', sa.String(), nullable=True),
        sa.Column('reported_at', sa.String(), nullable=False),
        sa.Column('verified', sa.Boolean(), server_default='false'),
        sa.Column('severity', sa.String(), server_default='High'),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
    )

def downgrade() -> None:
    op.drop_table('field_reports')
    op.drop_table('relocation_recommendations')
    op.drop_table('relocation_sites')
    op.drop_table('red_zones')
    op.drop_table('hazard_events')
    op.drop_table('habitations')
    op.drop_table('users')
