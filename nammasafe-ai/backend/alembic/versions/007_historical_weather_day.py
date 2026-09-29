"""data_day on historical_weather_samples (per-day grid cache)

Revision ID: 007_historical_weather_day
Revises: 006_admin_boundaries_census
Create Date: 2026-09-27

The ERA5 grid layer now serves *single completed days* (playback) in addition
to the completed-month aggregate. The persistent cache key therefore gains a
`data_day` column: 0 = whole-month aggregate, 1..N = that day of the month.
The unique constraint and the cell-period index are rebuilt to include it.
"""
from alembic import op
import sqlalchemy as sa

revision = "007_historical_weather_day"
down_revision = "006_admin_boundaries_census"
branch_labels = None
depends_on = None

_TABLE = "historical_weather_samples"
_UNIQUE = "uq_hist_weather_cell_period_variable_agg_source"
_INDEX_CELL_PERIOD = "ix_hist_weather_cell_period"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column("data_day", sa.Integer(), nullable=False, server_default="0"),
    )
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_constraint(_UNIQUE, type_="unique")
        batch_op.create_unique_constraint(
            _UNIQUE,
            [
                "latitude",
                "longitude",
                "data_year",
                "data_month",
                "data_day",
                "variable",
                "aggregation",
                "data_source",
            ],
        )
        batch_op.drop_index(_INDEX_CELL_PERIOD)
        batch_op.create_index(
            _INDEX_CELL_PERIOD,
            ["latitude", "longitude", "data_year", "data_month", "data_day"],
        )


def downgrade() -> None:
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_constraint(_UNIQUE, type_="unique")
        batch_op.create_unique_constraint(
            _UNIQUE,
            [
                "latitude",
                "longitude",
                "data_year",
                "data_month",
                "variable",
                "aggregation",
                "data_source",
            ],
        )
        batch_op.drop_index(_INDEX_CELL_PERIOD)
        batch_op.create_index(
            _INDEX_CELL_PERIOD,
            ["latitude", "longitude", "data_year", "data_month"],
        )
    op.drop_column(_TABLE, "data_day")