"""Table tennis live scores (sets summary and per-set scores).

Revision ID: 008
Revises: 007
Create Date: 2025-03-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
  op.add_column(
      "table_tennis_line_events",
      sa.Column("live_sets_score", sa.String(length=32), nullable=True),
  )
  op.add_column(
      "table_tennis_line_events",
      sa.Column("live_score", sa.JSON(), nullable=True),
  )


def downgrade() -> None:
  op.drop_column("table_tennis_line_events", "live_score")
  op.drop_column("table_tennis_line_events", "live_sets_score")

