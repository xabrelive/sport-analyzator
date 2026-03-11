"""Aggregated daily fatigue/workload features by player."""
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TableTennisPlayerDailyFeature(Base):
    __tablename__ = "table_tennis_player_daily_features"
    __table_args__ = (
        UniqueConstraint("player_id", "day", name="uq_tt_player_daily_features_player_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    player_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    player_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    matches_1d: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matches_2d: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matches_7d: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_rest_minutes_48h: Mapped[float | None] = mapped_column(Float, nullable=True)
    fatigue_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now)
