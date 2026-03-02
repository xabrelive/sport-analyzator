"""Admin API: выдача подписки по user_id. Требует X-Admin-Key."""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_async_session
from app.models import User, UserSubscription, AccessType, SubscriptionScope
from app.schemas.subscription import GrantSubscriptionBody, SubscriptionOut

router = APIRouter()


async def require_admin(x_admin_key: str | None = Header(None, alias="X-Admin-Key")):
    if not settings.admin_secret:
        raise HTTPException(status_code=503, detail="Admin API отключён")
    if x_admin_key != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    return True


@router.post("/subscriptions", response_model=SubscriptionOut)
async def admin_grant_subscription(
    body: GrantSubscriptionBody,
    _: bool = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Выдать подписку пользователю по user_id (после оплаты или вручную)."""
    if not body.user_id:
        raise HTTPException(status_code=400, detail="Укажите user_id")
    try:
        user_uuid = UUID(body.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Некорректный user_id")

    r = await session.execute(select(User).where(User.id == user_uuid))
    if r.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if body.scope == SubscriptionScope.ONE_SPORT.value and not body.sport_key:
        raise HTTPException(status_code=400, detail="Укажите sport_key для доступа «один вид спорта»")

    sub = UserSubscription(
        user_id=user_uuid,
        access_type=body.access_type,
        scope=body.scope,
        sport_key=body.sport_key,
        valid_until=body.valid_until,
    )
    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    return sub
