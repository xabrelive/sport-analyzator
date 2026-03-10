"""Add notification_email and quiet_hours to users.

Revision ID: 004
Revises: 003
Create Date: 2025-03-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("notification_email", sa.String(255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("quiet_hours_start", sa.Time(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("quiet_hours_end", sa.Time(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "quiet_hours_end")
    op.drop_column("users", "quiet_hours_start")
    op.drop_column("users", "notification_email")
