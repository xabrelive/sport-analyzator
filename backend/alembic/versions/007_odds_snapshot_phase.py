"""Add odds_snapshots.phase (line | live) for prematch vs inplay odds history.

Revision ID: 007
Revises: 006
Create Date: 2025-02-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "odds_snapshots",
        sa.Column("phase", sa.String(20), nullable=True),
    )
    op.create_index("ix_odds_snapshots_phase", "odds_snapshots", ["phase"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_odds_snapshots_phase", table_name="odds_snapshots")
    op.drop_column("odds_snapshots", "phase")
