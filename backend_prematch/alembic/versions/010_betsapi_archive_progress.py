"""Add betsapi_archive_progress for tracking which days are fully loaded.

Revision ID: 010
Revises: 009
Create Date: 2025-03-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "betsapi_archive_progress",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("day_yyyymmdd", sa.String(8), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "day_yyyymmdd", name="uq_betsapi_archive_provider_day"),
    )
    op.create_index(
        "ix_betsapi_archive_progress_provider",
        "betsapi_archive_progress",
        ["provider"],
        unique=False,
    )
    op.create_index(
        "ix_betsapi_archive_progress_day_yyyymmdd",
        "betsapi_archive_progress",
        ["day_yyyymmdd"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_betsapi_archive_progress_day_yyyymmdd", table_name="betsapi_archive_progress")
    op.drop_index("ix_betsapi_archive_progress_provider", table_name="betsapi_archive_progress")
    op.drop_table("betsapi_archive_progress")
