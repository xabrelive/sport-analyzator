"""Delivery log for Telegram FREE/VIP channel posts."""
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TelegramChannelNotification(Base):
    __tablename__ = "telegram_channel_notifications"
    __table_args__ = (
        UniqueConstraint("channel", "event_id", name="uq_telegram_channel_notifications_channel_event"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # free|vip
    event_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("table_tennis_line_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    forecast_v2_id: Mapped[int | None] = mapped_column(
        ForeignKey("table_tennis_forecasts_v2.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    telegram_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, index=True)
    result_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    result_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
