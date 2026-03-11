"""Precomputed match-level feature snapshot for V2 scoring."""
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TableTennisMatchFeature(Base):
    __tablename__ = "table_tennis_match_features"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("table_tennis_line_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("table_tennis_model_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    home_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    away_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    league_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    data_quality_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, index=True)
    features_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, index=True)
