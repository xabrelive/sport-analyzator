"""Schemas for user subscriptions / paid access."""
from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    access_type: str  # tg_analytics | signals
    scope: str  # one_sport | all
    sport_key: str | None = None
    valid_until: date
    connected_at: datetime
    created_at: datetime

    @property
    def access_type_label(self) -> str:
        return "Полная аналитика (ТГ)" if self.access_type == "tg_analytics" else "Сигналы"

    @property
    def scope_label(self) -> str:
        if self.scope == "all":
            return "Все виды"
        return f"Один вид: {self.sport_key or '—'}"


class AccessItem(BaseModel):
    """Один тип доступа: есть ли, до какой даты, охват."""
    has: bool = False
    valid_until: date | None = None
    scope: str | None = None  # one_sport | all
    sport_key: str | None = None
    connected_at: datetime | None = None


class AccessSummary(BaseModel):
    """Сводка доступа пользователя: аналитика в ТГ и сигналы."""
    tg_analytics: AccessItem = Field(default_factory=AccessItem)
    signals: AccessItem = Field(default_factory=AccessItem)


class GrantSubscriptionBody(BaseModel):
    """Тело запроса на выдачу подписки (админ или после оплаты)."""
    access_type: str = Field(..., pattern="^(tg_analytics|signals)$")
    scope: str = Field(..., pattern="^(one_sport|all)$")
    sport_key: str | None = None  # обязателен при scope=one_sport
    valid_until: date  # до какой даты включительно
    user_id: str | None = None  # если не указан — текущий пользователь (для /me)
    comment: str | None = None  # комментарий при выдаче через админку
