"""Odds snapshot — история коэффициентов."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MarketType(str, Enum):
    WINNER = "winner"
    SET_WINNER = "set_winner"
    TOTAL = "total"
    HANDICAP = "handicap"


class OddsSnapshot(Base):
    __tablename__ = "odds_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("matches.id", ondelete="CASCADE"),
        nullable=False,
    )
    bookmaker: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    market: Mapped[str] = mapped_column(String(50), nullable=False)
    selection: Mapped[str] = mapped_column(String(255), nullable=False)
    odds: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    implied_probability: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 6), nullable=True
    )
    line_value: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    # line = коэффициенты по линии (до начала), live = в лайве (как меняются после старта)
    phase: Mapped[str | None] = mapped_column(
        String(20), nullable=True, index=True
    )  # 'line' | 'live'
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now
    )
    snapshot_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    score_at_snapshot: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )

    match: Mapped["Match"] = relationship("Match", back_populates="odds_snapshots")
