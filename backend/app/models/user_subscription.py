"""User subscription / paid access: TG analytics and signals, one sport or all."""
import uuid
from datetime import date, datetime, timezone
from enum import Enum

from sqlalchemy import Date, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AccessType(str, Enum):
    """Тип доступа: полная аналитика в ТГ или сигналы."""
    TG_ANALYTICS = "tg_analytics"
    SIGNALS = "signals"


class SubscriptionScope(str, Enum):
    """Охват: один вид спорта (с выбором) или все виды."""
    ONE_SPORT = "one_sport"
    ALL = "all"


class UserSubscription(Base):
    __tablename__ = "user_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    access_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )  # AccessType value
    scope: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )  # SubscriptionScope value
    sport_key: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )  # e.g. "table_tennis" when scope=one_sport
    valid_until: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )  # включительно до какой даты доступ
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        nullable=False,
    )

    user = relationship("User", back_populates="subscriptions")
