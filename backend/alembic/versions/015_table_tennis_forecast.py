"""Add forecast fields for table tennis line events.

Revision ID: 015
Revises: 014
Create Date: 2026-03-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "table_tennis_line_events",
        sa.Column("forecast", sa.String(length=300), nullable=True),
    )
    op.add_column(
        "table_tennis_line_events",
        sa.Column("forecast_confidence", sa.Numeric(5, 2), nullable=True),
    )
    op.create_index(
        "ix_tt_line_events_forecast_confidence",
        "table_tennis_line_events",
        ["forecast_confidence"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tt_line_events_forecast_confidence",
        table_name="table_tennis_line_events",
    )
    op.drop_column("table_tennis_line_events", "forecast_confidence")
    op.drop_column("table_tennis_line_events", "forecast")

