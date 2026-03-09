"""Add last_processed_page to betsapi_archive_progress for resume and progress.

Revision ID: 011
Revises: 010
Create Date: 2025-03-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "betsapi_archive_progress",
        sa.Column("last_processed_page", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("betsapi_archive_progress", "last_processed_page")
