"""Предстоящие матчи настольного тенниса (линия) и коэффициенты.

Данные загружаются воркером из BetsAPI и отдаются API для дашборда.
status: scheduled | live | finished | postponed | cancelled — для отображения только предстоящих.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, Numeric, String, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Статусы матча (BetsAPI time_status: 0=Not Started, 1=Inplay, 3=Ended, 4=Postponed, 5=Cancelled и т.д.)
LINE_EVENT_STATUS_SCHEDULED = "scheduled"
LINE_EVENT_STATUS_LIVE = "live"
LINE_EVENT_STATUS_FINISHED = "finished"
LINE_EVENT_STATUS_POSTPONED = "postponed"
LINE_EVENT_STATUS_CANCELLED = "cancelled"

STATUSES_UPCOMING = (LINE_EVENT_STATUS_SCHEDULED, LINE_EVENT_STATUS_POSTPONED)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TableTennisLineEvent(Base):
    """Один матч в линии. id — внешний id события (BetsAPI). status — для фильтра предстоящих."""
    __tablename__ = "table_tennis_line_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # BetsAPI event id
    league_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    league_name: Mapped[str] = mapped_column(String(255), nullable=False)
    home_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    home_name: Mapped[str] = mapped_column(String(255), nullable=False)
    away_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    away_name: Mapped[str] = mapped_column(String(255), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=LINE_EVENT_STATUS_SCHEDULED, index=True
    )  # scheduled | live | finished | postponed | cancelled
    odds_1: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)   # коэффициент на победу 1
    odds_2: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)   # коэффициент на победу 2
    # Лайв-счёт: общий счёт по сетам (например, "2-1") и детальный счёт по каждому сету (JSON из BetsAPI).
    live_sets_score: Mapped[str | None] = mapped_column(String(32), nullable=True)
    live_score: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Когда в последний раз менялся счёт по сетам (live_score / live_sets_score).
    last_score_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Признак "подвисшего" лайв-матча (скрываем из блока "Сейчас играют").
    is_stale: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    stale_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Статус итоговой валидации результата: open | locked | not_received
    result_status: Mapped[str] = mapped_column(String(32), nullable=False, default="open", index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Однократные проверки результата (доп. запрос к API) спустя 1 и 3 часа после планового начала.
    result_checked_1h_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_checked_3h_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Время, когда матч впервые зафиксирован как завершённый (status=finished).
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Прематч‑рекомендация (из аналитики по истории игроков).
    forecast: Mapped[str | None] = mapped_column(String(300), nullable=True)
    forecast_confidence: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        onupdate=_utc_now,
        nullable=False,
    )
