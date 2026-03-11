"""Subscription expiry notifications table.

Revision ID: 026
Revises: 025
Create Date: 2026-03-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "026"
down_revision: Union[str, None] = "025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscription_expiry_notifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_subscription_id", UUID(as_uuid=True), sa.ForeignKey("user_subscriptions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("notification_type", sa.String(32), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_subscription_expiry_notif_sub_type",
        "subscription_expiry_notifications",
        ["user_subscription_id", "notification_type"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("subscription_expiry_notifications")
