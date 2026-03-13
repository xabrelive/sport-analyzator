"""Stored pre-match recommendation (from line/live table). One per match, never updated."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MatchRecommendation(Base):
    __tablename__ = "match_recommendations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("matches.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    recommendation_text: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
    )
    odds_at_recommendation: Mapped[float | None] = mapped_column(
        Numeric(10, 2),
        nullable=True,
    )
    confidence_pct: Mapped[float | None] = mapped_column(
        Numeric(5, 2),
        nullable=True,
    )  # 0–100, для фильтра бесплатного канала (только высокоуверенные)
    signals_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    free_channel_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )  # отправлено в бесплатный канал (3–4 в сутки, кф ≤2, уверенность ~100%)
    paid_channel_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )  # отправлено в платный канал (1–3 в час, прогноз с макс. вероятностью; экспресс — позже)
    free_channel_telegram_message_id: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    paid_channel_telegram_message_id: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    free_result_replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_result_replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user_deliveries: Mapped[list["UserSignalDelivery"]] = relationship(
        "UserSignalDelivery",
        back_populates="match_recommendation",
        cascade="all, delete-orphan",
        lazy="select",
    )

    match: Mapped["Match"] = relationship("Match", back_populates="stored_recommendation")
