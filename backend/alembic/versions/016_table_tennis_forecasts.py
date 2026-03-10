"""Table for table tennis pre-match forecasts.

Revision ID: 016
Revises: 015
Create Date: 2026-03-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
  op.create_table(
      "table_tennis_forecasts",
      sa.Column("event_id", sa.String(length=64), primary_key=True),
      sa.Column("league_id", sa.String(length=64), nullable=True),
      sa.Column("league_name", sa.String(length=255), nullable=True),
      sa.Column("home_id", sa.String(length=64), nullable=True),
      sa.Column("home_name", sa.String(length=255), nullable=True),
      sa.Column("away_id", sa.String(length=64), nullable=True),
      sa.Column("away_name", sa.String(length=255), nullable=True),
      sa.Column("forecast_text", sa.String(length=300), nullable=False),
      sa.Column("confidence_pct", sa.Numeric(5, 2), nullable=True),
      sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
      sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
      sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
      sa.Column("final_status", sa.String(length=32), nullable=True),
      sa.Column("final_sets_score", sa.String(length=32), nullable=True),
      sa.ForeignKeyConstraint(["event_id"], ["table_tennis_line_events.id"], ondelete="CASCADE"),
  )
  op.create_index("ix_tt_forecasts_status", "table_tennis_forecasts", ["status"])
  op.create_index("ix_tt_forecasts_created_at", "table_tennis_forecasts", ["created_at"])
  op.create_index("ix_tt_forecasts_resolved_at", "table_tennis_forecasts", ["resolved_at"])
  op.create_index("ix_tt_forecasts_league_id", "table_tennis_forecasts", ["league_id"])


def downgrade() -> None:
  op.drop_index("ix_tt_forecasts_league_id", table_name="table_tennis_forecasts")
  op.drop_index("ix_tt_forecasts_resolved_at", table_name="table_tennis_forecasts")
  op.drop_index("ix_tt_forecasts_created_at", table_name="table_tennis_forecasts")
  op.drop_index("ix_tt_forecasts_status", table_name="table_tennis_forecasts")
  op.drop_table("table_tennis_forecasts")

