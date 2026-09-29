"""Curated historical disaster events (India-wide provenance table)

Revision ID: 003_disaster_events
Revises: 002_historical_observations
Create Date: 2025-09-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '003_disaster_events'
down_revision = '002_historical_observations'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'disaster_events',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('hazard_type', sa.String(), nullable=False),
        sa.Column('event_date', sa.Date(), nullable=False),
        sa.Column('state', sa.String(), nullable=False),
        sa.Column('district', sa.String(), nullable=True),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
        sa.Column('severity_level', sa.String(), nullable=True),
        sa.Column('affected_population', sa.Integer(), nullable=True),
        sa.Column('fatalities', sa.Integer(), nullable=True),
        sa.Column('damage_estimate_inr_crore', sa.Float(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('source_reference', sa.String(), nullable=False, server_default=''),
        sa.Column('data_status', sa.String(), nullable=False, server_default='HISTORICAL'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.UniqueConstraint('name', 'event_date', 'source_reference', name='uq_disaster_event_name_date_source'),
    )
    op.create_index('ix_disaster_events_event_date', 'disaster_events', ['event_date'])
    op.create_index('ix_disaster_events_hazard_type', 'disaster_events', ['hazard_type'])
    op.create_index('ix_disaster_events_state', 'disaster_events', ['state'])
    op.create_index('ix_disaster_events_district', 'disaster_events', ['district'])


def downgrade() -> None:
    op.drop_index('ix_disaster_events_district', table_name='disaster_events')
    op.drop_index('ix_disaster_events_state', table_name='disaster_events')
    op.drop_index('ix_disaster_events_hazard_type', table_name='disaster_events')
    op.drop_index('ix_disaster_events_event_date', table_name='disaster_events')
    op.drop_table('disaster_events')