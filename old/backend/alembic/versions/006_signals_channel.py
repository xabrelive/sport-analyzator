"""Add signals.channel (free | paid) for landing stats split.

Revision ID: 006
Revises: 005
Create Date: 2025-02-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "signals",
        sa.Column("channel", sa.String(20), nullable=False, server_default=sa.text("'free'")),
    )
    op.create_index("ix_signals_channel", "signals", ["channel"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_signals_channel", table_name="signals")
    op.drop_column("signals", "channel")
