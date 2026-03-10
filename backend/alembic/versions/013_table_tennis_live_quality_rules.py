"""Table tennis live quality flags and league rules.

Revision ID: 013
Revises: 012
Create Date: 2025-03-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "table_tennis_line_events",
        sa.Column("is_stale", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "table_tennis_line_events",
        sa.Column("stale_since", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "table_tennis_line_events",
        sa.Column("result_status", sa.String(length=32), nullable=False, server_default="open"),
    )
    op.add_column(
        "table_tennis_line_events",
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_table_tennis_line_events_is_stale", "table_tennis_line_events", ["is_stale"])
    op.create_index("ix_table_tennis_line_events_result_status", "table_tennis_line_events", ["result_status"])

    op.create_table(
        "table_tennis_league_rules",
        sa.Column("league_id", sa.String(length=64), nullable=False),
        sa.Column("league_name", sa.String(length=255), nullable=False),
        sa.Column("max_sets_wins", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("expected_duration_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("stale_after_minutes", sa.Integer(), nullable=False, server_default="25"),
        sa.PrimaryKeyConstraint("league_id"),
    )

    # Базовые правила для основных лиг, чтобы быстрее отсекать "подвисшие" матчи.
    op.execute(
        """
        INSERT INTO table_tennis_league_rules (league_id, league_name, max_sets_wins, expected_duration_minutes, stale_after_minutes)
        VALUES
          ('22307', 'Setka Cup', 3, 20, 20),
          ('22121', 'Setka Cup Women', 3, 20, 20),
          ('29128', 'TT Elite Series', 3, 20, 20),
          ('22742', 'Czech Liga Pro', 3, 30, 25),
          ('37274', 'WTT Champions Chongqing', 4, 45, 30),
          ('37279', 'WTT Champions Chongqing Women', 4, 45, 30)
        ON CONFLICT (league_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("table_tennis_league_rules")
    op.drop_index("ix_table_tennis_line_events_result_status", table_name="table_tennis_line_events")
    op.drop_index("ix_table_tennis_line_events_is_stale", table_name="table_tennis_line_events")
    op.drop_column("table_tennis_line_events", "locked_at")
    op.drop_column("table_tennis_line_events", "result_status")
    op.drop_column("table_tennis_line_events", "stale_since")
    op.drop_column("table_tennis_line_events", "is_stale")

