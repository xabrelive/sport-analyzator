"""Admin API: пользователи, подписки, триал. Доступ: X-Admin-Key или JWT с is_admin."""
import logging
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import or_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_async_session
from app.models import User, UserSubscription, Invoice, AccessType, SubscriptionScope, PaymentMethod, Product
from app.models.subscription_grant_log import SubscriptionGrantLog
from app.models.scheduled_telegram_post import ScheduledTelegramPost
from app.schemas.subscription import GrantSubscriptionBody, SubscriptionOut
from app.services.telegram_channel_service import invite_user_to_paid_channel_async

router = APIRouter()
logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)


async def get_admin_auth(
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session: AsyncSession = Depends(get_async_session),
) -> User | None:
    """Доступ: X-Admin-Key (сервер/скрипты) или JWT с is_admin (админка в браузере)."""
    if x_admin_key and settings.admin_secret and x_admin_key == settings.admin_secret:
        return None  # key auth
    if not credentials or credentials.scheme != "Bearer":
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    from jose import jwt as jose_jwt
    from jose import JWTError
    try:
        payload = jose_jwt.decode(
            credentials.credentials,
            settings.secret_key,
            algorithms=[settings.algorithm],
        )
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="Неверный токен")
        user_uuid = UUID(sub)
    except (JWTError, ValueError):
        raise HTTPException(status_code=401, detail="Неверный или истёкший токен")
    r = await session.execute(select(User).where(User.id == user_uuid))
    user = r.scalar_one_or_none()
    if not user or not getattr(user, "is_admin", False):
        raise HTTPException(status_code=403, detail="Требуются права администратора")
    return user


async def require_admin(admin_auth: User | None = Depends(get_admin_auth)):
    return True


class AdminUserPatch(BaseModel):
    """Изменение пользователя. trial_until — явная дата окончания триала.
    trial_add_days — продлить триал на N дней от сегодня или от текущей trial_until.
    trial_clear — True: выключить триал (trial_until = null).
    grant_subscriptions_until_trial — при установке триала выдать аналитику и сигналы до trial_until (суммирование)."""
    trial_until: date | None = None
    trial_add_days: int | None = None
    trial_clear: bool = False
    grant_subscriptions_until_trial: bool = False
    is_admin: bool | None = None
    is_blocked: bool | None = None


@router.get("/users")
async def admin_list_users(
    _: bool = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    q: str | None = Query(None),
):
    """Список пользователей с пагинацией. Поиск по email/username при q."""
    base = select(User)
    if q and q.strip():
        qq = f"%{q.strip()}%"
        base = base.where(or_(User.email.ilike(qq), User.telegram_username.ilike(qq)))
    total_q = select(func.count()).select_from(base.subquery())
    total = (await session.execute(total_q)).scalar() or 0
    rows = (await session.execute(base.order_by(User.created_at.desc()).offset(offset).limit(limit))).scalars().all()
    return {
        "total": total,
        "items": [
            {
                "id": str(u.id),
                "email": u.email,
                "telegram_id": u.telegram_id,
                "telegram_username": u.telegram_username,
                "is_admin": getattr(u, "is_admin", False),
                "is_blocked": getattr(u, "is_blocked", False),
                "trial_until": u.trial_until.isoformat() if getattr(u, "trial_until", None) else None,
                "last_login_at": u.last_login_at.isoformat() if getattr(u, "last_login_at", None) else None,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in rows
        ],
    }


@router.get("/users/{user_id}")
async def admin_get_user(
    user_id: UUID,
    _: bool = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Пользователь по ID: профиль + подписки + инвойсы."""
    r = await session.execute(select(User).where(User.id == user_id))
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    subs = (await session.execute(
        select(UserSubscription).where(UserSubscription.user_id == user_id).order_by(UserSubscription.valid_until.desc())
    )).scalars().all()
    invs = (await session.execute(
        select(Invoice).where(Invoice.user_id == user_id).order_by(Invoice.created_at.desc()).limit(20)
    )).scalars().all()
    grant_logs = (await session.execute(
        select(SubscriptionGrantLog).where(SubscriptionGrantLog.user_id == user_id).order_by(SubscriptionGrantLog.created_at.desc()).limit(50)
    )).scalars().all()
    return {
        "id": str(user.id),
        "email": user.email,
        "email_verified": user.email_verified,
        "telegram_id": user.telegram_id,
        "telegram_username": user.telegram_username,
        "is_admin": getattr(user, "is_admin", False),
        "is_blocked": getattr(user, "is_blocked", False),
        "trial_until": user.trial_until.isoformat() if getattr(user, "trial_until", None) else None,
        "last_login_at": user.last_login_at.isoformat() if getattr(user, "last_login_at", None) else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "subscriptions": [
            {"id": str(s.id), "access_type": s.access_type, "scope": s.scope, "sport_key": s.sport_key, "valid_until": s.valid_until.isoformat()}
            for s in subs
        ],
        "invoices": [
            {"id": str(i.id), "amount": float(i.amount), "currency": i.currency, "status": i.status, "created_at": i.created_at.isoformat() if i.created_at else None, "paid_at": i.paid_at.isoformat() if i.paid_at else None}
            for i in invs
        ],
        "subscription_grant_logs": [
            {"id": str(g.id), "access_type": g.access_type, "scope": g.scope, "sport_key": g.sport_key, "valid_until": g.valid_until.isoformat(), "comment": g.comment, "created_at": g.created_at.isoformat() if g.created_at else None}
            for g in grant_logs
        ],
    }


@router.patch("/users/{user_id}")
async def admin_patch_user(
    user_id: UUID,
    body: AdminUserPatch,
    _: bool = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Изменить trial_until, is_admin или is_blocked. Триал: можно задать дату или trial_add_days; при grant_subscriptions_until_trial — выдать подписки до trial_until."""
    r = await session.execute(select(User).where(User.id == user_id))
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    today = datetime.now(timezone.utc).date()

    trial_until_value: date | None = body.trial_until
    if body.trial_clear:
        trial_until_value = None
        user.trial_until = None
    elif body.trial_add_days is not None:
        if body.trial_add_days < 0:
            raise HTTPException(status_code=400, detail="trial_add_days должен быть >= 0")
        base = (user.trial_until if getattr(user, "trial_until", None) and user.trial_until >= today else today)
        trial_until_value = base + timedelta(days=body.trial_add_days)
        user.trial_until = trial_until_value
    elif body.trial_until is not None:
        user.trial_until = body.trial_until

    if body.is_admin is not None:
        user.is_admin = body.is_admin
    if body.is_blocked is not None:
        user.is_blocked = body.is_blocked

    if body.grant_subscriptions_until_trial and trial_until_value is not None:
        for access_type in (AccessType.TG_ANALYTICS.value, AccessType.SIGNALS.value):
            scope = SubscriptionScope.ALL.value
            sport_key = None
            q_existing = (
                select(UserSubscription.valid_until)
                .where(
                    UserSubscription.user_id == user_id,
                    UserSubscription.access_type == access_type,
                    UserSubscription.scope == scope,
                    UserSubscription.sport_key.is_(None),
                )
            )
            existing = [row[0] for row in (await session.execute(q_existing)).all()]
            base_date = max(existing) if existing else today
            if base_date < trial_until_value:
                sub = UserSubscription(
                    user_id=user_id,
                    access_type=access_type,
                    scope=scope,
                    sport_key=sport_key,
                    valid_until=trial_until_value,
                )
                session.add(sub)
        await session.flush()
        if (
            user.telegram_id
            and not getattr(user, "is_blocked", False)
            and (settings.telegram_signals_paid_chat_id or "").strip()
        ):
            try:
                await invite_user_to_paid_channel_async(user.telegram_id)
            except Exception as e:
                logger.warning("Invite to paid channel after trial grant failed: %s", e)

    await session.commit()
    return {"ok": True}


@router.post("/subscriptions", response_model=SubscriptionOut)
async def admin_grant_subscription(
    body: GrantSubscriptionBody,
    admin_user: User | None = Depends(get_admin_auth),
    session: AsyncSession = Depends(get_async_session),
):
    """Выдать подписку пользователю по user_id (после оплаты или вручную). Можно указать комментарий."""
    if not body.user_id:
        raise HTTPException(status_code=400, detail="Укажите user_id")
    try:
        user_uuid = UUID(body.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Некорректный user_id")

    r = await session.execute(select(User).where(User.id == user_uuid))
    user = r.scalar_one_or_none()
    if user is None:
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
    await session.flush()

    log = SubscriptionGrantLog(
        user_id=user_uuid,
        granted_by_user_id=admin_user.id if admin_user else None,
        access_type=body.access_type,
        scope=body.scope,
        sport_key=body.sport_key,
        valid_until=body.valid_until,
        comment=body.comment.strip() if body.comment and body.comment.strip() else None,
    )
    session.add(log)

    await session.commit()
    await session.refresh(sub)
    if (
        body.access_type == AccessType.SIGNALS.value
        and user.telegram_id
        and not getattr(user, "is_blocked", False)
        and (settings.telegram_signals_paid_chat_id or "").strip()
    ):
        try:
            await invite_user_to_paid_channel_async(user.telegram_id)
        except Exception as e:
            logger.warning("Invite to paid channel failed: %s", e)
    return sub


# ——— Отложенные посты в Telegram ———

class ScheduledPostCreate(BaseModel):
    name: str
    target: str  # free_channel | paid_channel | bot_dm
    template_type: str | None = None  # daily_stats_12 | daily_stats_19_sport | пусто для своего текста
    body: str | None = None
    send_at_time_msk: str  # HH:MM
    is_active: bool = True


class ScheduledPostUpdate(BaseModel):
    name: str | None = None
    target: str | None = None
    template_type: str | None = None
    body: str | None = None
    send_at_time_msk: str | None = None
    is_active: bool | None = None


def _scheduled_post_to_dict(p: ScheduledTelegramPost) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "target": p.target,
        "template_type": p.template_type,
        "body": p.body,
        "send_at_time_msk": p.send_at_time_msk,
        "is_active": p.is_active,
        "last_sent_at": p.last_sent_at.isoformat() if p.last_sent_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("/scheduled-posts")
async def admin_list_scheduled_posts(
    _: bool = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Список отложенных постов (расписание рассылки в каналы и бота)."""
    r = await session.execute(
        select(ScheduledTelegramPost).order_by(ScheduledTelegramPost.send_at_time_msk.asc(), ScheduledTelegramPost.created_at.asc())
    )
    rows = r.scalars().all()
    return {"items": [_scheduled_post_to_dict(p) for p in rows]}


@router.post("/scheduled-posts")
async def admin_create_scheduled_post(
    body: ScheduledPostCreate,
    _: bool = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Добавить отложенный пост."""
    if body.target not in ("free_channel", "paid_channel", "bot_dm"):
        raise HTTPException(status_code=400, detail="target: free_channel, paid_channel или bot_dm")
    if body.template_type and body.template_type not in ("daily_stats_12", "daily_stats_19_sport"):
        raise HTTPException(status_code=400, detail="template_type: daily_stats_12, daily_stats_19_sport или пусто")
    if not body.template_type and not (body.body and body.body.strip()):
        raise HTTPException(status_code=400, detail="Укажите template_type или body")
    if len(body.send_at_time_msk) != 5 or body.send_at_time_msk[2] != ":":
        raise HTTPException(status_code=400, detail="send_at_time_msk в формате HH:MM (например 12:00)")
    p = ScheduledTelegramPost(
        name=body.name.strip(),
        target=body.target,
        template_type=(body.template_type or "").strip() or None,
        body=body.body.strip() if body.body else None,
        send_at_time_msk=body.send_at_time_msk.strip(),
        is_active=body.is_active,
    )
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return _scheduled_post_to_dict(p)


@router.get("/scheduled-posts/{post_id}")
async def admin_get_scheduled_post(
    post_id: UUID,
    _: bool = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Один отложенный пост."""
    r = await session.execute(select(ScheduledTelegramPost).where(ScheduledTelegramPost.id == post_id))
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Пост не найден")
    return _scheduled_post_to_dict(p)


@router.patch("/scheduled-posts/{post_id}")
async def admin_update_scheduled_post(
    post_id: UUID,
    body: ScheduledPostUpdate,
    _: bool = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Изменить отложенный пост."""
    r = await session.execute(select(ScheduledTelegramPost).where(ScheduledTelegramPost.id == post_id))
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Пост не найден")
    if body.name is not None:
        p.name = body.name.strip()
    if body.target is not None:
        if body.target not in ("free_channel", "paid_channel", "bot_dm"):
            raise HTTPException(status_code=400, detail="target: free_channel, paid_channel или bot_dm")
        p.target = body.target
    if body.template_type is not None:
        if body.template_type and body.template_type not in ("daily_stats_12", "daily_stats_19_sport"):
            raise HTTPException(status_code=400, detail="template_type: daily_stats_12, daily_stats_19_sport или пусто")
        p.template_type = body.template_type.strip() or None if body.template_type else None
    if body.body is not None:
        p.body = body.body.strip() or None
    if body.send_at_time_msk is not None:
        if len(body.send_at_time_msk) != 5 or body.send_at_time_msk[2] != ":":
            raise HTTPException(status_code=400, detail="send_at_time_msk в формате HH:MM")
        p.send_at_time_msk = body.send_at_time_msk.strip()
    if body.is_active is not None:
        p.is_active = body.is_active
    await session.commit()
    await session.refresh(p)
    return _scheduled_post_to_dict(p)


@router.delete("/scheduled-posts/{post_id}")
async def admin_delete_scheduled_post(
    post_id: UUID,
    _: bool = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Удалить отложенный пост."""
    r = await session.execute(select(ScheduledTelegramPost).where(ScheduledTelegramPost.id == post_id))
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Пост не найден")
    await session.delete(p)
    await session.commit()
    return {"ok": True}


# ——— Способы оплаты ———

class PaymentMethodCreate(BaseModel):
    name: str
    type: str  # yookassa | custom
    enabled: bool = True
    sort_order: int = 0
    custom_message: str | None = None


class PaymentMethodUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    enabled: bool | None = None
    sort_order: int | None = None
    custom_message: str | None = None


@router.get("/payment-methods")
async def admin_list_payment_methods(
    _: bool = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Список всех способов оплаты (включённые и выключенные)."""
    r = await session.execute(
        select(PaymentMethod).order_by(PaymentMethod.sort_order.asc(), PaymentMethod.created_at.asc())
    )
    rows = r.scalars().all()
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "type": p.type,
            "enabled": p.enabled,
            "sort_order": p.sort_order,
            "custom_message": p.custom_message,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in rows
    ]


@router.post("/payment-methods")
async def admin_create_payment_method(
    body: PaymentMethodCreate,
    _: bool = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Добавить способ оплаты."""
    if body.type not in ("yookassa", "custom"):
        raise HTTPException(status_code=400, detail="type должен быть yookassa или custom")
    pm = PaymentMethod(
        name=body.name.strip(),
        type=body.type,
        enabled=body.enabled,
        sort_order=body.sort_order,
        custom_message=body.custom_message.strip() if body.custom_message else None,
    )
    session.add(pm)
    await session.commit()
    await session.refresh(pm)
    return {
        "id": str(pm.id),
        "name": pm.name,
        "type": pm.type,
        "enabled": pm.enabled,
        "sort_order": pm.sort_order,
        "custom_message": pm.custom_message,
        "created_at": pm.created_at.isoformat() if pm.created_at else None,
    }


@router.patch("/payment-methods/{pm_id}")
async def admin_update_payment_method(
    pm_id: UUID,
    body: PaymentMethodUpdate,
    _: bool = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Изменить способ оплаты."""
    r = await session.execute(select(PaymentMethod).where(PaymentMethod.id == pm_id))
    pm = r.scalar_one_or_none()
    if not pm:
        raise HTTPException(status_code=404, detail="Способ оплаты не найден")
    if body.name is not None:
        pm.name = body.name.strip()
    if body.type is not None:
        if body.type not in ("yookassa", "custom"):
            raise HTTPException(status_code=400, detail="type: yookassa или custom")
        pm.type = body.type
    if body.enabled is not None:
        pm.enabled = body.enabled
    if body.sort_order is not None:
        pm.sort_order = body.sort_order
    if body.custom_message is not None:
        pm.custom_message = body.custom_message.strip() or None
    await session.commit()
    return {"ok": True}


@router.delete("/payment-methods/{pm_id}")
async def admin_delete_payment_method(
    pm_id: UUID,
    _: bool = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Удалить способ оплаты."""
    r = await session.execute(select(PaymentMethod).where(PaymentMethod.id == pm_id))
    pm = r.scalar_one_or_none()
    if not pm:
        raise HTTPException(status_code=404, detail="Способ оплаты не найден")
    await session.delete(pm)
    await session.commit()
    return {"ok": True}


# ——— Услуги (продукты) ———

class ProductUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    sort_order: int | None = None


@router.get("/products")
async def admin_list_products(
    _: bool = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Список всех услуг (подписка на аналитику, на приватный канал)."""
    r = await session.execute(
        select(Product).order_by(Product.sort_order.asc(), Product.created_at.asc())
    )
    rows = r.scalars().all()
    return [
        {
            "id": str(p.id),
            "key": p.key,
            "name": p.name,
            "enabled": p.enabled,
            "sort_order": p.sort_order,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in rows
    ]


@router.patch("/products/{product_id}")
async def admin_update_product(
    product_id: UUID,
    body: ProductUpdate,
    _: bool = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Изменить услугу (название, включена/выключена, порядок)."""
    r = await session.execute(select(Product).where(Product.id == product_id))
    product = r.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Услуга не найдена")
    if body.name is not None:
        product.name = body.name.strip()
    if body.enabled is not None:
        product.enabled = body.enabled
    if body.sort_order is not None:
        product.sort_order = body.sort_order
    await session.commit()
    return {"ok": True}
