"""Add match format: sets_to_win, points_per_set, win_by, is_doubles.

Revision ID: 002
Revises: 001
Create Date: 2025-02-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("sets_to_win", sa.Integer(), nullable=True))
    op.add_column("matches", sa.Column("points_per_set", sa.Integer(), nullable=True))
    op.add_column("matches", sa.Column("win_by", sa.Integer(), nullable=True))
    op.add_column("matches", sa.Column("is_doubles", sa.Boolean(), nullable=True))
    op.execute("UPDATE matches SET sets_to_win = 2 WHERE sets_to_win IS NULL")
    op.execute("UPDATE matches SET points_per_set = 11 WHERE points_per_set IS NULL")
    op.execute("UPDATE matches SET win_by = 2 WHERE win_by IS NULL")
    op.execute("UPDATE matches SET is_doubles = false WHERE is_doubles IS NULL")
    op.alter_column("matches", "sets_to_win", nullable=False)
    op.alter_column("matches", "points_per_set", nullable=False)
    op.alter_column("matches", "win_by", nullable=False)
    op.alter_column("matches", "is_doubles", nullable=False)


def downgrade() -> None:
    op.drop_column("matches", "is_doubles")
    op.drop_column("matches", "win_by")
    op.drop_column("matches", "points_per_set")
    op.drop_column("matches", "sets_to_win")
