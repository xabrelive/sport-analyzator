"""Forecast V2 rows for table tennis picks."""
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TableTennisForecastV2(Base):
    __tablename__ = "table_tennis_forecasts_v2"
    __table_args__ = (
        UniqueConstraint("event_id", "channel", "market", name="uq_tt_forecasts_v2_event_channel_market"),
    )

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
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="paid", index=True)
    market: Mapped[str] = mapped_column(String(32), nullable=False, default="match", index=True)  # match|set1|set2
    pick_side: Mapped[str] = mapped_column(String(16), nullable=False)  # home|away
    forecast_text: Mapped[str] = mapped_column(String(300), nullable=False)
    probability_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    edge_pct: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    odds_used: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    final_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    final_sets_score: Mapped[str | None] = mapped_column(String(32), nullable=True)
    explanation_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
