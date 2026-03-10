"""Stored pre-match forecast for table tennis matches."""
from datetime import datetime, timezone

from sqlalchemy import DateTime, Numeric, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TableTennisForecast(Base):
    __tablename__ = "table_tennis_forecasts"

    # Внутренний surrogate‑ключ — позволяет иметь несколько прогнозов на один матч (по разным каналам).
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Внешний идентификатор матча (может повторяться для разных каналов).
    event_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("table_tennis_line_events.id", ondelete="CASCADE"),
    )
    league_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    league_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    home_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    home_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    away_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    away_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Текст прогноза и уверенность (копируются из table_tennis_line_events.forecast*).
    forecast_text: Mapped[str] = mapped_column(String(300), nullable=False)
    confidence_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    forecast_odds: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True, index=True)

    # Канал аналитики: paid / free / vip / bot_signals и т.п.
    channel: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="paid",
        index=True,
    )

    # Статус прогноза относительно исхода матча:
    # pending — матч ещё не завершён / нет результата,
    # hit — прогноз угадан,
    # miss — прогноз не угадан,
    # cancelled — матч отменён,
    # no_result — нет достаточных данных для проверки (нет счёта по сетам и т.п.).
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        index=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    # Финальный статус матча и счёт на момент резолва прогноза
    final_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    final_sets_score: Mapped[str | None] = mapped_column(String(32), nullable=True)

    event: Mapped["TableTennisLineEvent"] = relationship(
        "TableTennisLineEvent",
        backref="forecast_row",
        lazy="joined",
    )

