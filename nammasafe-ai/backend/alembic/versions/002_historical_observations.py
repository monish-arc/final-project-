"""Historical hazard observations (previous-year Kerala rainfall)

Revision ID: 002_historical_observations
Revises: 001_initial_schema
Create Date: 2025-09-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '002_historical_observations'
down_revision = '001_initial_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'historical_hazard_observations',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('district_id', sa.Integer(), nullable=False),
        sa.Column('district', sa.String(), nullable=False),
        sa.Column('observation_date', sa.Date(), nullable=False),
        sa.Column('hazard_type', sa.String(), nullable=False, server_default='rainfall'),
        sa.Column('rainfall_mm', sa.Float(), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('source_reference', sa.String(), nullable=False, server_default=''),
        sa.Column('data_year', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.UniqueConstraint(
            'district_id', 'observation_date', 'data_year', 'source_reference',
            name='uq_historical_obs_district_date_year_source',
        ),
    )
    op.create_index('ix_historical_obs_district_id', 'historical_hazard_observations', ['district_id'])
    op.create_index('ix_historical_obs_observation_date', 'historical_hazard_observations', ['observation_date'])
    op.create_index('ix_historical_obs_hazard_type', 'historical_hazard_observations', ['hazard_type'])
    op.create_index('ix_historical_obs_data_year', 'historical_hazard_observations', ['data_year'])


def downgrade() -> None:
    op.drop_index('ix_historical_obs_data_year', table_name='historical_hazard_observations')
    op.drop_index('ix_historical_obs_hazard_type', table_name='historical_hazard_observations')
    op.drop_index('ix_historical_obs_observation_date', table_name='historical_hazard_observations')
    op.drop_index('ix_historical_obs_district_id', table_name='historical_hazard_observations')
    op.drop_table('historical_hazard_observations')