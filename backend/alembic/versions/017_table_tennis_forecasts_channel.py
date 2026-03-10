"""Add channel column to table_tennis_forecasts for different analytics feeds.

Revision ID: 017
Revises: 016
Create Date: 2026-03-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "table_tennis_forecasts",
        sa.Column(
            "channel",
            sa.String(length=32),
            nullable=False,
            server_default="paid",
        ),
    )
    op.create_index(
        "ix_tt_forecasts_channel",
        "table_tennis_forecasts",
        ["channel"],
    )
    # Drop server_default so new rows rely on application‑level default.
    op.alter_column(
        "table_tennis_forecasts",
        "channel",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_index("ix_tt_forecasts_channel", table_name="table_tennis_forecasts")
    op.drop_column("table_tennis_forecasts", "channel")

