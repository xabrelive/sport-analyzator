"""Лог доставки сигналов в личку пользователю (TG/email). Для блока «Мои сигналы» и статистики."""
import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SentVia(str, Enum):
    TELEGRAM = "telegram"
    EMAIL = "email"


class UserSignalDelivery(Base):
    __tablename__ = "user_signal_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    match_recommendation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("match_recommendations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sent_via: Mapped[str] = mapped_column(String(20), nullable=False)  # telegram | email
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    # Когда по батчу (несколько матчей в одном сообщении) отправили в личку итоги — у всех доставок батча ставим эту дату
    telegram_result_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    user = relationship("User", back_populates="signal_deliveries")
    match_recommendation = relationship(
        "MatchRecommendation",
        back_populates="user_deliveries",
        lazy="joined",
    )
