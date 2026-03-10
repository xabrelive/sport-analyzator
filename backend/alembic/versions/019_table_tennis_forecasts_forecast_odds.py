"""Add forecast_odds to table_tennis_forecasts.

Revision ID: 019
Revises: 018
Create Date: 2026-03-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "table_tennis_forecasts",
        sa.Column("forecast_odds", sa.Numeric(10, 3), nullable=True),
    )
    op.create_index(
        "ix_tt_forecasts_forecast_odds",
        "table_tennis_forecasts",
        ["forecast_odds"],
    )

    # Backfill: для уже существующих прогнозов берём матчевый кф по стороне П1/П2.
    op.execute(
        """
        UPDATE table_tennis_forecasts f
        SET forecast_odds = CASE
          WHEN lower(f.forecast_text) LIKE '%п1%' THEN e.odds_1
          WHEN lower(f.forecast_text) LIKE '%п2%' THEN e.odds_2
          ELSE NULL
        END
        FROM table_tennis_line_events e
        WHERE e.id = f.event_id
          AND f.forecast_odds IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_tt_forecasts_forecast_odds", table_name="table_tennis_forecasts")
    op.drop_column("table_tennis_forecasts", "forecast_odds")

