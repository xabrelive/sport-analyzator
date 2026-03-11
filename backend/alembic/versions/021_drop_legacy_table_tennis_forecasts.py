"""Drop legacy table_tennis_forecasts table.

Revision ID: 021
Revises: 020
Create Date: 2026-03-09
"""
from typing import Sequence, Union

from alembic import op


revision: str = "021"
down_revision: Union[str, None] = "020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS table_tennis_forecasts CASCADE")


def downgrade() -> None:
    # Legacy table was fully replaced by table_tennis_forecasts_v2.
    # We intentionally do not restore deprecated schema on downgrade.
    pass
