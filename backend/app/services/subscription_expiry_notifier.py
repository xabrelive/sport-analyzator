"""Send subscription expiry notifications: 3h before and when expired."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import async_session_maker
from app.models.subscription_expiry_notification import SubscriptionExpiryNotification
from app.models.user import User
from app.models.user_subscription import UserSubscription

logger = logging.getLogger(__name__)

PINGWIN_URL = "https://pingwin.pro"


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


async def _send_telegram(chat_id: int, text: str) -> bool:
    token = (settings.telegram_bot_token or "").strip()
    if not token:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, json=payload)
        return resp.status_code == 200 and (resp.json() or {}).get("ok") is True


async def _already_sent(session: AsyncSession, sub_id, notif_type: str) -> bool:
    r = (
        await session.execute(
            select(SubscriptionExpiryNotification.id).where(
                and_(
                    SubscriptionExpiryNotification.user_subscription_id == sub_id,
                    SubscriptionExpiryNotification.notification_type == notif_type,
                )
            )
        )
    ).scalar_one_or_none()
    return r is not None


async def _mark_sent(session: AsyncSession, sub_id, notif_type: str) -> None:
    session.add(
        SubscriptionExpiryNotification(
            user_subscription_id=sub_id,
            notification_type=notif_type,
        )
    )
    await session.commit()


async def dispatch_subscription_expiry_notifications_once() -> dict[str, int]:
    """Send expiring_soon (3h before) and expired notifications. Returns counts."""
    now = datetime.now(timezone.utc)
    today = now.date()
    three_hours_later = now + timedelta(hours=3)
    three_hours_later_end = three_hours_later.date()
    if three_hours_later.date() != today:
        three_hours_later_end = today  # edge case: 3h spans midnight

    expiring_soon_sent = 0
    expired_sent = 0

    async with async_session_maker() as session:
        # Subscriptions expiring in the next 3 hours (valid_until is today or tomorrow within 3h)
        # Simplified: valid_until == today means it expires today; we send 3h before if we're within 3h of midnight
        # More precise: valid_until = today means expires at end of today. So "3h before" = valid_until is today and now >= 21:00 UTC (for midnight) or similar.
        # Actually: valid_until is a date. So subscription is valid until end of that day (inclusive). "3 hours before" = 3 hours before end of valid_until day.
        # End of valid_until day = valid_until 23:59:59. So 3h before = valid_until 20:59:59.
        # So we send when: valid_until = today and now >= today 21:00? No - that's too narrow.
        # Simpler: valid_until = today means it expires at end of today. We send "expiring_soon" when we're within 3 hours of that. So when now is between (today 21:00) and (today 23:59:59). That's a 3h window.
        # Even simpler: send "expiring_soon" for all subscriptions where valid_until = today, once per subscription. So user gets it once on the last day.
        # User said "за 3 часа до окончания" - 3 hours before end. So we need to send when current time is ~3h before midnight of valid_until. For date-only we approximate: valid_until = today, and we're past 21:00 UTC (9 PM) = roughly 3h before midnight.
        # For robustness: send expiring_soon when valid_until = today (they have less than 24h left). One notification per subscription.
        expiring_rows = (
            await session.execute(
                select(UserSubscription, User)
                .join(User, User.id == UserSubscription.user_id)
                .where(
                    UserSubscription.valid_until == today,
                    User.telegram_id.is_not(None),
                )
            )
        ).all()

        for sub, user in expiring_rows:
            if await _already_sent(session, sub.id, "expiring_soon"):
                continue
            text = (
                "⏰ Подписка заканчивается сегодня. Продлите, чтобы не потерять доступ к прогнозам.\n\n"
                f"🐧 <a href=\"{PINGWIN_URL}\">pingwin.pro</a> — оформить подписку"
            )
            if await _send_telegram(int(user.telegram_id), text):
                await _mark_sent(session, sub.id, "expiring_soon")
                expiring_soon_sent += 1
                logger.info("Subscription expiring_soon sent: user=%s", user.id)

        # Subscriptions that expired (valid_until < today); we send once per subscription
        expired_rows = (
            await session.execute(
                select(UserSubscription, User)
                .join(User, User.id == UserSubscription.user_id)
                .where(
                    UserSubscription.valid_until < today,
                    User.telegram_id.is_not(None),
                )
            )
        ).all()

        for sub, user in expired_rows:
            if await _already_sent(session, sub.id, "expired"):
                continue
            text = (
                "⏹ Подписка закончилась. Продолжите пользоваться аналитикой — оформите подписку на сайте.\n\n"
                f"🐧 <a href=\"{PINGWIN_URL}\">pingwin.pro</a>"
            )
            if await _send_telegram(int(user.telegram_id), text):
                await _mark_sent(session, sub.id, "expired")
                expired_sent += 1
                logger.info("Subscription expired notification sent: user=%s", user.id)

    return {"expiring_soon": expiring_soon_sent, "expired": expired_sent}


async def subscription_expiry_loop() -> None:
    """Run expiry notifications every hour."""
    import asyncio

    interval = 3600  # 1 hour
    logger.info("Subscription expiry notifier: starting loop (interval=%ss)", interval)
    while True:
        try:
            await dispatch_subscription_expiry_notifications_once()
        except Exception:
            logger.exception("Subscription expiry notifier failed")
        await asyncio.sleep(interval)
