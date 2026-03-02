"""Match model."""
import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MatchStatus(str, Enum):
    SCHEDULED = "scheduled"
    LIVE = "live"
    FINISHED = "finished"
    CANCELLED = "cancelled"
    POSTPONED = "postponed"


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    provider_match_id: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    league_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leagues.id", ondelete="SET NULL"),
        nullable=True,
    )
    home_player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("players.id", ondelete="CASCADE"),
        nullable=False,
    )
    away_player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("players.id", ondelete="CASCADE"),
        nullable=False,
    )
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=MatchStatus.SCHEDULED.value
    )
    bet365_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    timeline: Mapped[dict | list | None] = mapped_column(
        JSONB(), nullable=True
    )
    extra: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    current_timer: Mapped[str | None] = mapped_column(String(50), nullable=True)
    odds_stats: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    # Формат матча: 3/5/7 сетов, до 11 или до 6 очков, парные
    sets_to_win: Mapped[int] = mapped_column(nullable=False, default=2)  # 2=BO3, 3=BO5, 4=BO7
    points_per_set: Mapped[int] = mapped_column(nullable=False, default=11)  # 11 или 6
    win_by: Mapped[int] = mapped_column(nullable=False, default=2)
    is_doubles: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )

    league: Mapped["League | None"] = relationship("League", back_populates="matches")
    home_player: Mapped["Player"] = relationship(
        "Player", foreign_keys=[home_player_id], back_populates="home_matches"
    )
    away_player: Mapped["Player"] = relationship(
        "Player", foreign_keys=[away_player_id], back_populates="away_matches"
    )
    scores: Mapped[list["MatchScore"]] = relationship(
        "MatchScore", back_populates="match", order_by="MatchScore.set_number"
    )
    odds_snapshots: Mapped[list["OddsSnapshot"]] = relationship(
        "OddsSnapshot", back_populates="match"
    )
    result: Mapped["MatchResult | None"] = relationship(
        "MatchResult", back_populates="match", uselist=False
    )
    stored_recommendation: Mapped["MatchRecommendation | None"] = relationship(
        "MatchRecommendation",
        back_populates="match",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="noload",
    )
    signals: Mapped[list["Signal"]] = relationship(
        "Signal", back_populates="match", cascade="all, delete-orphan"
    )
