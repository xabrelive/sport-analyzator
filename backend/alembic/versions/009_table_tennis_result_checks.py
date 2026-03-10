"""Table tennis line events: result check timestamps (1h and 3h after planned start).

Revision ID: 009
Revises: 008
Create Date: 2025-03-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "table_tennis_line_events",
        sa.Column("result_checked_1h_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "table_tennis_line_events",
        sa.Column("result_checked_3h_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("table_tennis_line_events", "result_checked_3h_at")
    op.drop_column("table_tennis_line_events", "result_checked_1h_at")

