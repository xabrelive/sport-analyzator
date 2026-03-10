"""Schemas for /me (profile and settings)."""
from pydantic import BaseModel


class MeProfile(BaseModel):
    email: str
    email_masked: str  # для отображения (скрытая часть)
    telegram_linked: bool
    telegram_username: str | None
    email_linked: bool  # реальная почта для уведомлений (email не плейсхолдер или notification_email задан)
    notification_email: str | None  # привязанная почта для уведомлений (может быть маскирована)
    notification_email_masked: str | None
    quiet_hours_start: str | None  # "HH:MM" или null
    quiet_hours_end: str | None
    is_telegram_only: bool  # зарегистрирован через Telegram


class MeSettingsUpdate(BaseModel):
    quiet_hours_start: str | None = None  # "HH:MM" (0-23:00-59)
    quiet_hours_end: str | None = None
