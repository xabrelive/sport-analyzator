"""Add Player image_id, country; Match bet365_id, confirmed_at, started_at, timeline, extra, current_timer; OddsSnapshot line_value, snapshot_time.

Revision ID: 008
Revises: 007
Create Date: 2025-03-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Player
    op.add_column("players", sa.Column("image_id", sa.String(100), nullable=True))
    op.add_column("players", sa.Column("country", sa.String(100), nullable=True))

    # Match
    op.add_column("matches", sa.Column("bet365_id", sa.String(50), nullable=True))
    op.add_column(
        "matches",
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "matches",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "matches",
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("matches", sa.Column("timeline", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("matches", sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("matches", sa.Column("current_timer", sa.String(50), nullable=True))

    # OddsSnapshot: линия гандикапа/тотала + время снимка из API
    op.add_column(
        "odds_snapshots",
        sa.Column("line_value", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "odds_snapshots",
        sa.Column("snapshot_time", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("odds_snapshots", "snapshot_time")
    op.drop_column("odds_snapshots", "line_value")
    op.drop_column("matches", "current_timer")
    op.drop_column("matches", "extra")
    op.drop_column("matches", "timeline")
    op.drop_column("matches", "started_at")
    op.drop_column("matches", "finished_at")
    op.drop_column("matches", "confirmed_at")
    op.drop_column("matches", "bet365_id")
    op.drop_column("players", "country")
    op.drop_column("players", "image_id")
