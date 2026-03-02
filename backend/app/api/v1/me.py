"""Current user: access summary and subscriptions. Requires JWT."""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.v1.auth import get_current_user
from app.db.session import get_async_session
from app.models import User, UserSubscription, AccessType, SubscriptionScope
from app.schemas.subscription import (
    AccessItem,
    AccessSummary,
    GrantSubscriptionBody,
    SubscriptionOut,
)
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


def _today() -> date:
    return datetime.now(timezone.utc).date()


@router.get("/access", response_model=AccessSummary)
async def get_my_access(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Сводка: есть ли доступ к полной аналитике (ТГ) и к сигналам, до какой даты."""
    q = (
        select(UserSubscription)
        .where(
            UserSubscription.user_id == user.id,
            UserSubscription.valid_until >= _today(),
        )
    )
    result = await session.execute(q)
    subs = list(result.scalars().all())

    def pick_best(subs_list: list[UserSubscription], access_type: str) -> AccessItem:
        filtered = [s for s in subs_list if s.access_type == access_type]
        if not filtered:
            return AccessItem(has=False)
        best = max(filtered, key=lambda s: s.valid_until)
        return AccessItem(
            has=True,
            valid_until=best.valid_until,
            scope=best.scope,
            sport_key=best.sport_key,
            connected_at=best.connected_at,
        )

    return AccessSummary(
        tg_analytics=pick_best(subs, AccessType.TG_ANALYTICS.value),
        signals=pick_best(subs, AccessType.SIGNALS.value),
    )


@router.get("/subscriptions", response_model=list[SubscriptionOut])
async def list_my_subscriptions(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Список активных подписок (valid_until >= сегодня), от старых к новым по дате окончания."""
    q = (
        select(UserSubscription)
        .where(
            UserSubscription.user_id == user.id,
            UserSubscription.valid_until >= _today(),
        )
        .order_by(UserSubscription.valid_until.asc(), UserSubscription.connected_at.asc())
    )
    result = await session.execute(q)
    return list(result.scalars().all())


@router.post("/subscriptions", response_model=SubscriptionOut)
async def grant_my_subscription(
    body: GrantSubscriptionBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Выдать себе подписку (для демо/теста; в проде — после успешной оплаты или вебхук)."""
    if body.user_id is not None:
        raise HTTPException(status_code=400, detail="user_id не допускается для текущего пользователя")
    if body.scope == SubscriptionScope.ONE_SPORT.value and not body.sport_key:
        raise HTTPException(status_code=400, detail="Укажите sport_key для доступа «один вид спорта»")

    sub = UserSubscription(
        user_id=user.id,
        access_type=body.access_type,
        scope=body.scope,
        sport_key=body.sport_key,
        valid_until=body.valid_until,
    )
    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    return sub
