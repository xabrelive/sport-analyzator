"""BetsAPI request logs for debugging (counts per interval).

Revision ID: 011
Revises: 010
Create Date: 2025-03-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "betsapi_request_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("endpoint", sa.String(length=64), nullable=False),
        sa.Column("status_code", sa.Integer, nullable=False),
        sa.Column("ok", sa.Boolean, nullable=False),
    )
    op.create_index(
        "ix_betsapi_request_logs_created_at",
        "betsapi_request_logs",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_betsapi_request_logs_created_at", table_name="betsapi_request_logs")
    op.drop_table("betsapi_request_logs")

