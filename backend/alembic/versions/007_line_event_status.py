"""Add status to table_tennis_line_events (scheduled, live, finished, postponed, cancelled).

Revision ID: 007
Revises: 006
Create Date: 2025-03-09

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
        "table_tennis_line_events",
        sa.Column("status", sa.String(32), nullable=False, server_default="scheduled"),
    )
    op.create_index("ix_table_tennis_line_events_status", "table_tennis_line_events", ["status"])


def downgrade() -> None:
    op.drop_index("ix_table_tennis_line_events_status", table_name="table_tennis_line_events")
    op.drop_column("table_tennis_line_events", "status")
