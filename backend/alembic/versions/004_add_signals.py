"""Add signals table for tracking given signals and outcomes.

Revision ID: 004
Revises: 003
Create Date: 2025-02-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("market_type", sa.String(100), nullable=False),
        sa.Column("selection", sa.String(200), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_signals_match_id", "signals", ["match_id"], unique=False)
    op.create_index("ix_signals_outcome", "signals", ["outcome"], unique=False)
    op.create_index("ix_signals_created_at", "signals", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_signals_created_at", table_name="signals")
    op.drop_index("ix_signals_outcome", table_name="signals")
    op.drop_index("ix_signals_match_id", table_name="signals")
    op.drop_table("signals")
