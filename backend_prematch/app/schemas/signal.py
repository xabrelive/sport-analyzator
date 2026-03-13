"""Signal schemas — список сигналов и статистика (дано/выиграло/проиграло)."""
from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SignalList(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    match_id: UUID
    market_type: str
    selection: str
    outcome: str  # pending | won | lost
    channel: str = "free"  # free | paid
    created_at: datetime


class SignalStatsDay(BaseModel):
    """Статистика сигналов за один день."""
    date: date
    total: int
    won: int
    lost: int
    pending: int


class SignalStats(BaseModel):
    """Общая статистика и по дням."""
    total: int
    won: int
    lost: int
    pending: int
    by_day: list[SignalStatsDay] = []


class SignalPeriodStats(BaseModel):
    """Статистика за период: всего, угадано, не угадано."""
    total: int
    won: int
    lost: int


class SignalChannelStats(BaseModel):
    """Статистика по каналу за день, неделю, месяц."""
    day: SignalPeriodStats
    week: SignalPeriodStats
    month: SignalPeriodStats


class SignalLandingStats(BaseModel):
    """Статистика для главной: бесплатный канал и платная подписка."""
    free_channel: SignalChannelStats
    paid_subscription: SignalChannelStats
