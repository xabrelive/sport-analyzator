"""Table tennis line events (upcoming matches + odds).

Revision ID: 005
Revises: 004
Create Date: 2025-03-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "table_tennis_line_events",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("league_id", sa.String(64), nullable=False),
        sa.Column("league_name", sa.String(255), nullable=False),
        sa.Column("home_id", sa.String(64), nullable=False),
        sa.Column("home_name", sa.String(255), nullable=False),
        sa.Column("away_id", sa.String(64), nullable=False),
        sa.Column("away_name", sa.String(255), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("odds_1", sa.Numeric(10, 4), nullable=True),
        sa.Column("odds_2", sa.Numeric(10, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_table_tennis_line_events_league_id", "table_tennis_line_events", ["league_id"])
    op.create_index("ix_table_tennis_line_events_home_id", "table_tennis_line_events", ["home_id"])
    op.create_index("ix_table_tennis_line_events_away_id", "table_tennis_line_events", ["away_id"])
    op.create_index("ix_table_tennis_line_events_starts_at", "table_tennis_line_events", ["starts_at"])


def downgrade() -> None:
    op.drop_index("ix_table_tennis_line_events_starts_at", table_name="table_tennis_line_events")
    op.drop_index("ix_table_tennis_line_events_away_id", table_name="table_tennis_line_events")
    op.drop_index("ix_table_tennis_line_events_home_id", table_name="table_tennis_line_events")
    op.drop_index("ix_table_tennis_line_events_league_id", table_name="table_tennis_line_events")
    op.drop_table("table_tennis_line_events")
