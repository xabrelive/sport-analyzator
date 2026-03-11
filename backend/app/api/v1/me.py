"""Profile and settings API (/me)."""
from datetime import time

from fastapi import APIRouter, Depends

from app.api.v1.auth import get_current_user
from app.db.session import get_async_session
from app.models.user import User
from app.schemas.me import MeProfile, MeSettingsUpdate
from app.services.subscription_access import (
    has_analytics_subscription,
    has_vip_channel_subscription,
)
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return email or ""
    local, domain = email.rsplit("@", 1)
    if len(local) <= 2:
        masked = "*" * len(local)
    else:
        masked = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked}@{domain}"


def _time_to_str(t: time | None) -> str | None:
    if t is None:
        return None
    return t.strftime("%H:%M")


def _str_to_time(s: str | None) -> time | None:
    if not s or ":" not in s:
        return None
    parts = s.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        h, m = int(parts[0], 10), int(parts[1], 10)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return time(hour=h, minute=m)
    except ValueError:
        pass
    return None


@router.get("", response_model=MeProfile)
async def get_me(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Профиль и настройки уведомлений: привязки Telegram/почты, режим тишины."""
    has_analytics = await has_analytics_subscription(user.id, session)
    has_vip = await has_vip_channel_subscription(user.id, session)
    telegram_linked = user.telegram_id is not None
    is_tg_only = user.is_telegram_only()
    email_linked = not is_tg_only or (user.notification_email or "").strip() != ""
    notification_email = (user.notification_email or "").strip() or None
    return MeProfile(
        email=user.email,
        email_masked=_mask_email(user.email),
        telegram_linked=telegram_linked,
        telegram_username=user.telegram_username,
        email_linked=email_linked,
        notification_email=notification_email,
        notification_email_masked=_mask_email(notification_email) if notification_email else None,
        quiet_hours_start=_time_to_str(user.quiet_hours_start),
        quiet_hours_end=_time_to_str(user.quiet_hours_end),
        notify_telegram=bool(user.notify_telegram),
        notify_email=bool(user.notify_email),
        is_telegram_only=is_tg_only,
        is_superadmin=bool(getattr(user, "is_superadmin", False)),
        has_analytics_subscription=has_analytics,
        has_vip_channel_subscription=has_vip,
    )


@router.patch("", response_model=MeProfile)
async def update_me(
    data: MeSettingsUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Обновить настройки: режим тишины."""
    has_analytics = await has_analytics_subscription(user.id, session)
    has_vip = await has_vip_channel_subscription(user.id, session)
    if data.quiet_hours_start is not None:
        user.quiet_hours_start = _str_to_time(data.quiet_hours_start)
    if data.quiet_hours_end is not None:
        user.quiet_hours_end = _str_to_time(data.quiet_hours_end)
    if data.notify_telegram is not None:
        user.notify_telegram = bool(data.notify_telegram)
    if data.notify_email is not None:
        user.notify_email = bool(data.notify_email)
    await session.commit()
    await session.refresh(user)
    telegram_linked = user.telegram_id is not None
    is_tg_only = user.is_telegram_only()
    email_linked = not is_tg_only or (user.notification_email or "").strip() != ""
    notification_email = (user.notification_email or "").strip() or None
    return MeProfile(
        email=user.email,
        email_masked=_mask_email(user.email),
        telegram_linked=telegram_linked,
        telegram_username=user.telegram_username,
        email_linked=email_linked,
        notification_email=notification_email,
        notification_email_masked=_mask_email(notification_email) if notification_email else None,
        quiet_hours_start=_time_to_str(user.quiet_hours_start),
        quiet_hours_end=_time_to_str(user.quiet_hours_end),
        notify_telegram=bool(user.notify_telegram),
        notify_email=bool(user.notify_email),
        is_telegram_only=is_tg_only,
        is_superadmin=bool(getattr(user, "is_superadmin", False)),
        has_analytics_subscription=has_analytics,
        has_vip_channel_subscription=has_vip,
    )


@router.post("/unlink-telegram", response_model=dict)
async def unlink_telegram(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Отвязать Telegram от аккаунта."""
    if user.telegram_id is None:
        return {"message": "ok", "detail": "Telegram не был привязан."}
    user.telegram_id = None
    user.telegram_username = None
    await session.commit()
    return {"message": "ok", "detail": "Telegram отвязан."}


@router.post("/unlink-notification-email", response_model=dict)
async def unlink_notification_email(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Убрать привязанную почту для уведомлений (только для аккаунтов через Telegram)."""
    if not user.is_telegram_only():
        return {"message": "ok", "detail": "У аккаунта по почте основная почта не отключается."}
    user.notification_email = None
    await session.commit()
    return {"message": "ok", "detail": "Почта для уведомлений отвязана."}
