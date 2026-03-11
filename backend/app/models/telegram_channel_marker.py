"""Idempotency markers for scheduled Telegram channel jobs."""
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TelegramChannelMarker(Base):
    __tablename__ = "telegram_channel_markers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    marker_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # free|vip
    marker_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # slot|hourly|summary
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, index=True)
