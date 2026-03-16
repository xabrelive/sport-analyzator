"""User model."""
import uuid
from datetime import datetime, time, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, String, Time
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _email_placeholder(telegram_id: int) -> str:
    return f"tg_{telegram_id}@telegram.pingwin.local"


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
    telegram_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Для получения уведомлений (привязка почты к аккаунту, зарегистрированному через Telegram)
    notification_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notify_telegram: Mapped[bool] = mapped_column(Boolean(), default=True, nullable=False)
    notify_email: Mapped[bool] = mapped_column(Boolean(), default=True, nullable=False)
    # Режим тишины: не слать уведомления в этот интервал (локальное время пользователя)
    quiet_hours_start: Mapped[time | None] = mapped_column(Time(), nullable=True)
    quiet_hours_end: Mapped[time | None] = mapped_column(Time(), nullable=True)
    # Часовой пояс пользователя как смещение от UTC в минутах (например, UTC+3 = 180).
    notification_tz_offset_minutes: Mapped[int] = mapped_column(nullable=False, default=0)
    is_blocked: Mapped[bool] = mapped_column(Boolean(), default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True, nullable=False)
    is_superadmin: Mapped[bool] = mapped_column(Boolean(), default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    privacy_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
    )

    @staticmethod
    def email_placeholder(telegram_id: int) -> str:
        return _email_placeholder(telegram_id)

    def is_telegram_only(self) -> bool:
        """Аккаунт зарегистрирован через Telegram (email — плейсхолдер)."""
        return self.email.startswith("tg_") and "telegram.pingwin.local" in self.email
