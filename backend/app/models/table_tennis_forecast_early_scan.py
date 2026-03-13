"""Stage 1: ранний скрининг (6-12h). Считаем, не публикуем, храним временно."""
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TableTennisForecastEarlyScan(Base):
    """Ранний скрининг: потенциальные value-матчи за 6-12h. Не публикуем."""
    __tablename__ = "table_tennis_forecast_early_scan"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("table_tennis_line_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    minutes_to_match: Mapped[int | None] = mapped_column(Integer, nullable=True)
    p_match: Mapped[float | None] = mapped_column(Float, nullable=True)
    has_value: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        index=True,
    )
