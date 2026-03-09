"""Лог выдачи подписок через админку (история пополнений)."""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SubscriptionGrantLog(Base):
    """Запись о выдаче подписки через админку (с комментарием)."""
    __tablename__ = "subscription_grant_logs"

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
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    access_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    sport_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    valid_until: Mapped[date] = mapped_column(Date, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        nullable=False,
    )

    user = relationship("User", foreign_keys=[user_id], back_populates="subscription_grant_logs")
    granted_by = relationship("User", foreign_keys=[granted_by_user_id])
