"""User model for auth."""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, Date, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _email_placeholder(telegram_id: int) -> str:
    return f"tg_{telegram_id}@telegram.pingwin.local"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_verified: Mapped[bool] = mapped_column(default=False, nullable=False)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True, index=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
    )

    subscriptions: Mapped[list["UserSubscription"]] = relationship(
        "UserSubscription",
        back_populates="user",
        lazy="selectin",
    )

    @property
    def is_telegram_user(self) -> bool:
        return self.telegram_id is not None

    @staticmethod
    def email_placeholder(telegram_id: int) -> str:
        return _email_placeholder(telegram_id)
