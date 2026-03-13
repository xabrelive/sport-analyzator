"""Subscription access: analytics and VIP channel checks for forecast/notification gating."""
from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_subscription import UserSubscription


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


async def has_analytics_subscription(user_id: UUID, session: AsyncSession) -> bool:
    """True if user has active analytics subscription (valid_until >= today)."""
    row = (
        await session.execute(
            select(UserSubscription)
            .where(
                UserSubscription.user_id == user_id,
                UserSubscription.service_key == "analytics",
                UserSubscription.valid_until >= _today_utc(),
            )
            .order_by(UserSubscription.valid_until.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def has_no_ml_analytics_subscription(user_id: UUID, session: AsyncSession) -> bool:
    """True if user has active no-ML analytics subscription."""
    row = (
        await session.execute(
            select(UserSubscription)
            .where(
                UserSubscription.user_id == user_id,
                UserSubscription.service_key == "analytics_no_ml",
                UserSubscription.valid_until >= _today_utc(),
            )
            .order_by(UserSubscription.valid_until.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def has_vip_channel_subscription(user_id: UUID, session: AsyncSession) -> bool:
    """True if user has active VIP channel subscription."""
    row = (
        await session.execute(
            select(UserSubscription)
            .where(
                UserSubscription.user_id == user_id,
                UserSubscription.service_key == "vip_channel",
                UserSubscription.valid_until >= _today_utc(),
            )
            .order_by(UserSubscription.valid_until.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def get_subscription_access(user_id: UUID, session: AsyncSession) -> dict:
    """
    Returns:
        has_analytics: bool
        has_analytics_no_ml: bool
        has_vip_channel: bool
        can_see_forecasts: bool  # analytics OR vip
        forecast_channel: str | None  # "paid" if analytics, "vip" if vip_only, None if neither
        only_resolved: bool  # True if no analytics (vip-only or no subscription)
    """
    has_analytics = await has_analytics_subscription(user_id, session)
    has_analytics_no_ml = await has_no_ml_analytics_subscription(user_id, session)
    has_vip = await has_vip_channel_subscription(user_id, session)

    can_see_forecasts = has_analytics or has_vip
    if has_analytics:
        forecast_channel = "paid"
        only_resolved = False  # full access
    elif has_vip:
        forecast_channel = "vip"
        only_resolved = True  # vip only = only resolved
    else:
        forecast_channel = None
        only_resolved = True

    return {
        "has_analytics": has_analytics,
        "has_analytics_no_ml": has_analytics_no_ml,
        "has_vip_channel": has_vip,
        "can_see_forecasts": can_see_forecasts,
        "forecast_channel": forecast_channel,
        "only_resolved": only_resolved,
    }


# Placeholder messages for locked content
FORECAST_LOCKED_ANALYTICS = "Для просмотра приобретите подписку на аналитику"
FORECAST_LOCKED_VIP = "Для доступа в ТГ канал приобретите подписку VIP"
DASHBOARD_PURCHASE_URL = "https://pingwin.pro/dashboard"
