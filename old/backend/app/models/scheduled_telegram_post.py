"""Отложенные посты в Telegram: рекламные/статистика по расписанию (бесплатный канал, платный, бот в личку)."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ScheduledTelegramPost(Base):
    __tablename__ = "scheduled_telegram_posts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    # Название для админки
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # free_channel | paid_channel | bot_dm
    target: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # Шаблон: daily_stats_12 (утро, общая статистика), daily_stats_19_sport (вечер, по видам спорта), или пусто для своего текста
    template_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Текст сообщения (если template_type пустой). Поддерживает HTML для Telegram.
    body: Mapped[str | None] = mapped_column(String(8000), nullable=True)
    # Время отправки по МСК, формат HH:MM (например 12:00, 19:00)
    send_at_time_msk: Mapped[str] = mapped_column(String(5), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now, nullable=False)
