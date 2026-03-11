"""Add user notification settings and delivery log.

Revision ID: 022
Revises: 021
Create Date: 2026-03-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "022"
down_revision: Union[str, None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("notify_telegram", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("users", sa.Column("notify_email", sa.Boolean(), nullable=False, server_default=sa.text("true")))

    op.create_table(
        "user_forecast_notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.String(length=64), sa.ForeignKey("table_tennis_line_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("forecast_v2_id", sa.Integer(), sa.ForeignKey("table_tennis_forecasts_v2.id", ondelete="SET NULL"), nullable=True),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("result_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_status", sa.String(length=32), nullable=True),
        sa.UniqueConstraint("user_id", "event_id", "channel", name="uq_user_forecast_notification_user_event_channel"),
    )
    op.create_index("ix_user_forecast_notifications_user_id", "user_forecast_notifications", ["user_id"])
    op.create_index("ix_user_forecast_notifications_event_id", "user_forecast_notifications", ["event_id"])
    op.create_index("ix_user_forecast_notifications_channel", "user_forecast_notifications", ["channel"])
    op.create_index("ix_user_forecast_notifications_forecast_v2_id", "user_forecast_notifications", ["forecast_v2_id"])
    op.create_index("ix_user_forecast_notifications_sent_at", "user_forecast_notifications", ["sent_at"])
    op.create_index("ix_user_forecast_notifications_result_notified_at", "user_forecast_notifications", ["result_notified_at"])


def downgrade() -> None:
    op.drop_index("ix_user_forecast_notifications_result_notified_at", table_name="user_forecast_notifications")
    op.drop_index("ix_user_forecast_notifications_sent_at", table_name="user_forecast_notifications")
    op.drop_index("ix_user_forecast_notifications_forecast_v2_id", table_name="user_forecast_notifications")
    op.drop_index("ix_user_forecast_notifications_channel", table_name="user_forecast_notifications")
    op.drop_index("ix_user_forecast_notifications_event_id", table_name="user_forecast_notifications")
    op.drop_index("ix_user_forecast_notifications_user_id", table_name="user_forecast_notifications")
    op.drop_table("user_forecast_notifications")
    op.drop_column("users", "notify_email")
    op.drop_column("users", "notify_telegram")
