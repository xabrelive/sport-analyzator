"""Add OddsSnapshot.score_at_snapshot, Match.odds_stats for analysis (link odds to score).

Revision ID: 009
Revises: 008
Create Date: 2025-03-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "odds_snapshots",
        sa.Column("score_at_snapshot", sa.String(100), nullable=True),
    )
    op.add_column(
        "matches",
        sa.Column("odds_stats", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("matches", "odds_stats")
    op.drop_column("odds_snapshots", "score_at_snapshot")
