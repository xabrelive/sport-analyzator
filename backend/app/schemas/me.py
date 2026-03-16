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
    notify_telegram: bool
    notify_email: bool
    notification_tz_offset_minutes: int = 0
    is_telegram_only: bool  # зарегистрирован через Telegram
    is_superadmin: bool
    has_analytics_subscription: bool = False
    has_vip_channel_subscription: bool = False
    has_no_ml_analytics_subscription: bool = False


class MeSettingsUpdate(BaseModel):
    quiet_hours_start: str | None = None  # "HH:MM" (0-23:00-59)
    quiet_hours_end: str | None = None
    notify_telegram: bool | None = None
    notify_email: bool | None = None
    notification_tz_offset_minutes: int | None = None
