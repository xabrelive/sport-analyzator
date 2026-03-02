"""Stored pre-match recommendation (from line/live table). One per match, never updated."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Numeric, String
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

    match: Mapped["Match"] = relationship("Match", back_populates="stored_recommendation")
