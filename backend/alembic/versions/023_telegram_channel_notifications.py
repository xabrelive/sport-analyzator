"""Add telegram FREE/VIP channel notification logs.

Revision ID: 023
Revises: 022
Create Date: 2026-03-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "023"
down_revision: Union[str, None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "telegram_channel_notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.String(length=64), sa.ForeignKey("table_tennis_line_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("forecast_v2_id", sa.Integer(), sa.ForeignKey("table_tennis_forecasts_v2.id", ondelete="SET NULL"), nullable=True),
        sa.Column("telegram_message_id", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("result_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_status", sa.String(length=32), nullable=True),
        sa.UniqueConstraint("channel", "event_id", name="uq_telegram_channel_notifications_channel_event"),
    )
    op.create_index("ix_telegram_channel_notifications_channel", "telegram_channel_notifications", ["channel"])
    op.create_index("ix_telegram_channel_notifications_event_id", "telegram_channel_notifications", ["event_id"])
    op.create_index("ix_telegram_channel_notifications_forecast_v2_id", "telegram_channel_notifications", ["forecast_v2_id"])
    op.create_index("ix_telegram_channel_notifications_sent_at", "telegram_channel_notifications", ["sent_at"])
    op.create_index("ix_telegram_channel_notifications_result_notified_at", "telegram_channel_notifications", ["result_notified_at"])

    op.create_table(
        "telegram_channel_markers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("marker_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("marker_type", sa.String(length=32), nullable=False),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_telegram_channel_markers_marker_key", "telegram_channel_markers", ["marker_key"])
    op.create_index("ix_telegram_channel_markers_channel", "telegram_channel_markers", ["channel"])
    op.create_index("ix_telegram_channel_markers_marker_type", "telegram_channel_markers", ["marker_type"])
    op.create_index("ix_telegram_channel_markers_sent_at", "telegram_channel_markers", ["sent_at"])


def downgrade() -> None:
    op.drop_index("ix_telegram_channel_markers_sent_at", table_name="telegram_channel_markers")
    op.drop_index("ix_telegram_channel_markers_marker_type", table_name="telegram_channel_markers")
    op.drop_index("ix_telegram_channel_markers_channel", table_name="telegram_channel_markers")
    op.drop_index("ix_telegram_channel_markers_marker_key", table_name="telegram_channel_markers")
    op.drop_table("telegram_channel_markers")

    op.drop_index("ix_telegram_channel_notifications_result_notified_at", table_name="telegram_channel_notifications")
    op.drop_index("ix_telegram_channel_notifications_sent_at", table_name="telegram_channel_notifications")
    op.drop_index("ix_telegram_channel_notifications_forecast_v2_id", table_name="telegram_channel_notifications")
    op.drop_index("ix_telegram_channel_notifications_event_id", table_name="telegram_channel_notifications")
    op.drop_index("ix_telegram_channel_notifications_channel", table_name="telegram_channel_notifications")
    op.drop_table("telegram_channel_notifications")
