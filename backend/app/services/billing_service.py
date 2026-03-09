"""Billing: create payment via YooKassa, process webhook, grant subscriptions."""
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Invoice, User, UserSubscription
from app.models.user_subscription import AccessType, SubscriptionScope
from app.services.telegram_channel_service import invite_user_to_paid_channel_async

logger = logging.getLogger(__name__)

YOOKASSA_API = "https://api.yookassa.ru/v3"


def _yookassa_auth() -> tuple[str, str]:
    return (settings.yookassa_shop_id, settings.yookassa_secret_key)


async def create_yookassa_payment(
    amount_rub: Decimal,
    description: str,
    return_url: str,
    metadata: dict,
) -> tuple[str | None, str | None]:
    """
    Создать платёж в YooKassa. Возвращает (payment_id, confirmation_url) или (None, error_message).
    """
    if not settings.yookassa_shop_id or not settings.yookassa_secret_key:
        return None, "Оплата не настроена (YooKassa)"
    value = f"{amount_rub:.2f}"
    payload = {
        "amount": {"value": value, "currency": "RUB"},
        "confirmation": {"type": "redirect", "return_url": return_url},
        "description": description[:255],
        "capture": True,
        "metadata": metadata,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{YOOKASSA_API}/payments",
                json=payload,
                auth=_yookassa_auth(),
                headers={"Idempotence-Key": metadata.get("invoice_id", "")},
            )
        if r.status_code != 200:
            logger.warning("YooKassa create payment failed: %s %s", r.status_code, r.text)
            return None, r.text or "Ошибка платёжной системы"
        data = r.json()
        pid = data.get("id")
        conf = data.get("confirmation", {})
        url = conf.get("confirmation_url") if isinstance(conf, dict) else None
        return pid, url
    except Exception as e:
        logger.exception("YooKassa request failed: %s", e)
        return None, str(e)


async def grant_subscriptions_from_invoice_payload(
    session: AsyncSession,
    user_id: UUID,
    payload: list[dict],
) -> int:
    """
    По payload инвойса (список items с access_type, scope, sport_key, days) создаёт подписки.
    Если у пользователя уже есть активная подписка того же типа (access_type, scope, sport_key),
    дни прибавляются к дате окончания текущей, а не от сегодня — тарифы суммируются.
    Возвращает количество созданных записей подписок.
    """
    today = datetime.now(timezone.utc).date()
    created = 0
    for item in payload:
        access_type = item.get("access_type")
        scope = item.get("scope")
        sport_key = item.get("sport_key")
        days = int(item.get("days", 0))
        if not access_type or access_type not in (AccessType.TG_ANALYTICS.value, AccessType.SIGNALS.value):
            continue
        if not scope or scope not in (SubscriptionScope.ONE_SPORT.value, SubscriptionScope.ALL.value):
            continue
        if scope == SubscriptionScope.ONE_SPORT.value and not sport_key:
            continue
        if days < 1:
            continue

        # Текущая максимальная дата окончания по такому же типу подписки (чтобы суммировать дни)
        q_existing = (
            select(UserSubscription.valid_until)
            .where(
                UserSubscription.user_id == user_id,
                UserSubscription.access_type == access_type,
                UserSubscription.scope == scope,
                UserSubscription.sport_key == (sport_key if scope == SubscriptionScope.ONE_SPORT.value else None),
            )
        )
        r_existing = await session.execute(q_existing)
        existing_dates = [row[0] for row in r_existing.all()]
        base_date = max(existing_dates) if existing_dates else today
        if base_date < today:
            base_date = today
        valid_until = base_date + timedelta(days=days)

        sub = UserSubscription(
            user_id=user_id,
            access_type=access_type,
            scope=scope,
            sport_key=sport_key if scope == SubscriptionScope.ONE_SPORT.value else None,
            valid_until=valid_until,
        )
        session.add(sub)
        created += 1
    if created:
        await session.flush()
        r = await session.execute(select(User).where(User.id == user_id))
        user = r.scalar_one_or_none()
        if user and user.telegram_id and not getattr(user, "is_blocked", False) and created:
            for item in payload:
                if item.get("access_type") == AccessType.SIGNALS.value and (
                    settings.telegram_signals_paid_chat_id or ""
                ).strip():
                    try:
                        await invite_user_to_paid_channel_async(user.telegram_id)
                    except Exception as e:
                        logger.warning("Invite to paid channel failed: %s", e)
                    break
    return created
