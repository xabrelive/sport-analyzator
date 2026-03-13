"""Admin API: superadmin-only service management."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.config import settings
from app.db.session import get_async_session
from app.models.app_setting import AppSetting
from app.models.billing_product import BillingProduct
from app.models.invoice import Invoice
from app.models.payment_method import PaymentMethod
from app.models.user import User
from app.models.user_subscription import UserSubscription
from app.services.email import send_html_email
from app.services.vip_channel_access import send_vip_invite_to_user

router = APIRouter()

ALLOWED_SERVICE_KEYS = {"analytics", "analytics_no_ml", "vip_channel"}
ALLOWED_MESSAGE_TARGETS = {"free_channel", "vip_channel", "telegram_user", "email"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def require_superadmin(user: User = Depends(get_current_user)) -> User:
    if not bool(getattr(user, "is_superadmin", False)):
        raise HTTPException(status_code=403, detail="Требуются права суперадмина")
    return user


def _fmt_dt(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _event_link(event_id: str) -> str:
    base = (settings.frontend_public_url or "").strip().rstrip("/")
    if not base:
        base = "https://pingwin.pro"
    return f"{base}/dashboard/table-tennis/matches/{event_id}"


async def _send_telegram(chat_id: int, text: str) -> int | None:
    token = (settings.telegram_bot_token or "").strip()
    if not token:
        return None
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload)
    if resp.status_code != 200:
        return None
    data = resp.json()
    if not data.get("ok"):
        return None
    return int((data.get("result") or {}).get("message_id") or 0) or None


def _date_to_iso(d: date) -> str:
    return d.isoformat()


def _extend_valid_until(current: date | None, days: int) -> date:
    today = _utc_now().date()
    base = current if current and current >= today else today
    return base + timedelta(days=max(1, days))


@router.get("/me")
async def admin_me(user: User = Depends(require_superadmin)):
    return {
        "id": str(user.id),
        "email": user.email,
        "is_superadmin": bool(user.is_superadmin),
    }


@router.get("/users")
async def list_users(
    q: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=200),
    _: User = Depends(require_superadmin),
    session: AsyncSession = Depends(get_async_session),
):
    base = select(User)
    if q and q.strip():
        like = f"%{q.strip()}%"
        base = base.where(
            or_(
                User.email.ilike(like),
                User.telegram_username.ilike(like),
                User.notification_email.ilike(like),
            )
        )
    total = int((await session.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0)
    rows = (
        await session.execute(
            base.order_by(User.created_at.desc()).offset(offset).limit(limit)
        )
    ).scalars().all()
    return {
        "total": total,
        "items": [
            {
                "id": str(u.id),
                "email": u.email,
                "telegram_id": u.telegram_id,
                "telegram_username": u.telegram_username,
                "notification_email": u.notification_email,
                "is_active": bool(u.is_active),
                "is_blocked": bool(u.is_blocked),
                "is_superadmin": bool(u.is_superadmin),
                "last_login_at": _fmt_dt(u.last_login_at),
                "created_at": _fmt_dt(u.created_at),
            }
            for u in rows
        ],
    }


class AdminUserPatch(BaseModel):
    is_active: bool | None = None
    is_blocked: bool | None = None
    is_superadmin: bool | None = None
    notify_telegram: bool | None = None
    notify_email: bool | None = None


@router.patch("/users/{user_id}")
async def patch_user(
    user_id: UUID,
    body: AdminUserPatch,
    admin: User = Depends(require_superadmin),
    session: AsyncSession = Depends(get_async_session),
):
    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if body.is_active is not None:
        user.is_active = bool(body.is_active)
    if body.is_blocked is not None:
        user.is_blocked = bool(body.is_blocked)
    if body.notify_telegram is not None:
        user.notify_telegram = bool(body.notify_telegram)
    if body.notify_email is not None:
        user.notify_email = bool(body.notify_email)
    if body.is_superadmin is not None:
        if str(user.id) == str(admin.id) and not body.is_superadmin:
            raise HTTPException(status_code=400, detail="Нельзя снять флаг суперадмина у самого себя")
        user.is_superadmin = bool(body.is_superadmin)
    await session.commit()
    return {"ok": True}


@router.get("/users/{user_id}/subscriptions")
async def user_subscriptions(
    user_id: UUID,
    _: User = Depends(require_superadmin),
    session: AsyncSession = Depends(get_async_session),
):
    rows = (
        await session.execute(
            select(UserSubscription)
            .where(UserSubscription.user_id == user_id)
            .order_by(UserSubscription.valid_until.desc(), UserSubscription.created_at.desc())
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": str(s.id),
                "service_key": s.service_key,
                "duration_days": int(s.duration_days),
                "valid_until": _date_to_iso(s.valid_until),
                "source": s.source,
                "comment": s.comment,
                "created_at": _fmt_dt(s.created_at),
            }
            for s in rows
        ]
    }


class UpsertSubscriptionBody(BaseModel):
    service_key: str = Field(..., pattern="^(analytics|vip_channel)$")
    days: int = Field(default=30, ge=1, le=365)
    comment: str | None = None


@router.post("/users/{user_id}/subscriptions")
async def upsert_subscription(
    user_id: UUID,
    body: UpsertSubscriptionBody,
    _: User = Depends(require_superadmin),
    session: AsyncSession = Depends(get_async_session),
):
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if body.service_key not in ALLOWED_SERVICE_KEYS:
        raise HTTPException(status_code=400, detail="Некорректный service_key")

    active = (
        await session.execute(
            select(UserSubscription)
            .where(
                UserSubscription.user_id == user_id,
                UserSubscription.service_key == body.service_key,
            )
            .order_by(UserSubscription.valid_until.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    current_until = active.valid_until if active else None
    valid_until = _extend_valid_until(current_until, body.days)
    sub = UserSubscription(
        user_id=user_id,
        service_key=body.service_key,
        duration_days=body.days,
        valid_until=valid_until,
        source="admin",
        comment=(body.comment or "").strip() or None,
    )
    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    return {
        "id": str(sub.id),
        "service_key": sub.service_key,
        "duration_days": sub.duration_days,
        "valid_until": _date_to_iso(sub.valid_until),
        "source": sub.source,
        "comment": sub.comment,
    }


@router.delete("/users/{user_id}/subscriptions/{subscription_id}")
async def delete_subscription(
    user_id: UUID,
    subscription_id: UUID,
    _: User = Depends(require_superadmin),
    session: AsyncSession = Depends(get_async_session),
):
    row = (
        await session.execute(
            select(UserSubscription).where(
                UserSubscription.id == subscription_id,
                UserSubscription.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Подписка не найдена")
    await session.delete(row)
    await session.commit()
    return {"ok": True}


@router.get("/products")
async def list_products(
    _: User = Depends(require_superadmin),
    session: AsyncSession = Depends(get_async_session),
):
    rows = (
        await session.execute(
            select(BillingProduct).order_by(BillingProduct.sort_order.asc(), BillingProduct.created_at.asc())
        )
    ).scalars().all()
    return [
        {
            "id": str(p.id),
            "code": p.code,
            "name": p.name,
            "service_key": p.service_key,
            "duration_days": p.duration_days,
            "price_rub": float(p.price_rub),
            "price_usd": float(p.price_usd),
            "enabled": p.enabled,
            "sort_order": p.sort_order,
        }
        for p in rows
    ]


class ProductPatch(BaseModel):
    name: str | None = None
    price_rub: float | None = Field(default=None, ge=0)
    price_usd: float | None = Field(default=None, ge=0)
    enabled: bool | None = None
    sort_order: int | None = None


@router.patch("/products/{product_id}")
async def patch_product(
    product_id: UUID,
    body: ProductPatch,
    _: User = Depends(require_superadmin),
    session: AsyncSession = Depends(get_async_session),
):
    row = (await session.execute(select(BillingProduct).where(BillingProduct.id == product_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Тариф не найден")
    if body.name is not None:
        row.name = body.name.strip()
    if body.price_rub is not None:
        row.price_rub = Decimal(str(body.price_rub))
    if body.price_usd is not None:
        row.price_usd = Decimal(str(body.price_usd))
    if body.enabled is not None:
        row.enabled = bool(body.enabled)
    if body.sort_order is not None:
        row.sort_order = int(body.sort_order)
    await session.commit()
    return {"ok": True}


@router.get("/payment-methods")
async def list_payment_methods(
    _: User = Depends(require_superadmin),
    session: AsyncSession = Depends(get_async_session),
):
    rows = (
        await session.execute(
            select(PaymentMethod).order_by(PaymentMethod.sort_order.asc(), PaymentMethod.created_at.asc())
        )
    ).scalars().all()
    return [
        {
            "id": str(m.id),
            "name": m.name,
            "method_type": m.method_type,
            "enabled": m.enabled,
            "sort_order": m.sort_order,
            "instructions": m.instructions,
        }
        for m in rows
    ]


class PaymentMethodBody(BaseModel):
    name: str
    method_type: str = Field(default="custom", pattern="^(custom|card|crypto)$")
    enabled: bool = True
    sort_order: int = 0
    instructions: str | None = None


@router.post("/payment-methods")
async def create_payment_method(
    body: PaymentMethodBody,
    _: User = Depends(require_superadmin),
    session: AsyncSession = Depends(get_async_session),
):
    row = PaymentMethod(
        name=body.name.strip(),
        method_type=body.method_type,
        enabled=bool(body.enabled),
        sort_order=int(body.sort_order),
        instructions=(body.instructions or "").strip() or None,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {"id": str(row.id)}


class PaymentMethodPatch(BaseModel):
    name: str | None = None
    method_type: str | None = Field(default=None, pattern="^(custom|card|crypto)$")
    enabled: bool | None = None
    sort_order: int | None = None
    instructions: str | None = None


@router.patch("/payment-methods/{method_id}")
async def patch_payment_method(
    method_id: UUID,
    body: PaymentMethodPatch,
    _: User = Depends(require_superadmin),
    session: AsyncSession = Depends(get_async_session),
):
    row = (await session.execute(select(PaymentMethod).where(PaymentMethod.id == method_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Способ оплаты не найден")
    if body.name is not None:
        row.name = body.name.strip()
    if body.method_type is not None:
        row.method_type = body.method_type
    if body.enabled is not None:
        row.enabled = bool(body.enabled)
    if body.sort_order is not None:
        row.sort_order = int(body.sort_order)
    if body.instructions is not None:
        row.instructions = body.instructions.strip() or None
    await session.commit()
    return {"ok": True}


@router.delete("/payment-methods/{method_id}")
async def delete_payment_method(
    method_id: UUID,
    _: User = Depends(require_superadmin),
    session: AsyncSession = Depends(get_async_session),
):
    row = (await session.execute(select(PaymentMethod).where(PaymentMethod.id == method_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Способ оплаты не найден")
    await session.delete(row)
    await session.commit()
    return {"ok": True}


@router.get("/invoices")
async def admin_invoices(
    status: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _: User = Depends(require_superadmin),
    session: AsyncSession = Depends(get_async_session),
):
    q = select(Invoice, User.email).join(User, User.id == Invoice.user_id)
    if status:
        q = q.where(Invoice.status == status)
    total = int((await session.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0)
    rows = (await session.execute(q.order_by(Invoice.created_at.desc()).offset(offset).limit(limit))).all()
    return {
        "total": total,
        "items": [
            {
                "id": str(inv.id),
                "user_id": str(inv.user_id),
                "user_email": email,
                "status": inv.status,
                "amount_rub": float(inv.amount_rub),
                "payment_method_id": str(inv.payment_method_id) if inv.payment_method_id else None,
                "comment": inv.comment,
                "created_at": _fmt_dt(inv.created_at),
                "paid_at": _fmt_dt(inv.paid_at),
            }
            for inv, email in rows
        ],
    }


class MarkInvoicePaidBody(BaseModel):
    paid: bool = True


@router.patch("/invoices/{invoice_id}/status")
async def patch_invoice_status(
    invoice_id: UUID,
    body: MarkInvoicePaidBody,
    _: User = Depends(require_superadmin),
    session: AsyncSession = Depends(get_async_session),
):
    inv = (await session.execute(select(Invoice).where(Invoice.id == invoice_id))).scalar_one_or_none()
    if inv is None:
        raise HTTPException(status_code=404, detail="Инвойс не найден")
    if body.paid:
        if inv.status == "paid":
            return {"ok": True, "status": "paid", "message": "Инвойс уже был подтверждён"}
        inv.status = "paid"
        inv.paid_at = _utc_now()
        payload = inv.payload or {}
        items = payload.get("items") if isinstance(payload, dict) else []
        vip_valid_until: date | None = None
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                service_key = str(item.get("service_key") or "").strip()
                days = int(item.get("days") or 0)
                if service_key not in ALLOWED_SERVICE_KEYS or days < 1:
                    continue
                existing = (
                    await session.execute(
                        select(UserSubscription)
                        .where(
                            UserSubscription.user_id == inv.user_id,
                            UserSubscription.service_key == service_key,
                        )
                        .order_by(UserSubscription.valid_until.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                valid_until = _extend_valid_until(existing.valid_until if existing else None, days)
                session.add(
                    UserSubscription(
                        user_id=inv.user_id,
                        service_key=service_key,
                        duration_days=days,
                        valid_until=valid_until,
                        source="invoice",
                        comment=f"invoice:{inv.id}",
                    )
                )
                if service_key == "vip_channel":
                    vip_valid_until = valid_until
    else:
        if inv.status == "cancelled":
            return {"ok": True, "status": "cancelled", "message": "Инвойс уже отклонён"}
        inv.status = "cancelled"
    await session.commit()
    invite_sent = False
    if body.paid and vip_valid_until is not None:
        user = (await session.execute(select(User).where(User.id == inv.user_id))).scalar_one_or_none()
        if user is not None and user.telegram_id is not None:
            try:
                invite_sent = await send_vip_invite_to_user(user, vip_valid_until)
            except Exception:
                invite_sent = False
    return {"ok": True, "invite_sent": invite_sent}


class AdminMessageBody(BaseModel):
    target: str = Field(..., pattern="^(free_channel|vip_channel|telegram_user|email)$")
    text: str = Field(..., min_length=1, max_length=5000)
    user_id: str | None = None
    email: str | None = None
    subject: str | None = None


@router.post("/messages/send")
async def send_admin_message(
    body: AdminMessageBody,
    _: User = Depends(require_superadmin),
    session: AsyncSession = Depends(get_async_session),
):
    if body.target not in ALLOWED_MESSAGE_TARGETS:
        raise HTTPException(status_code=400, detail="Некорректный target")
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Пустое сообщение")

    if body.target in {"free_channel", "vip_channel"}:
        chat_raw = settings.telegram_signals_free_chat_id if body.target == "free_channel" else settings.telegram_signals_vip_chat_id
        chat_raw = (chat_raw or "").strip()
        if not chat_raw:
            raise HTTPException(status_code=400, detail="Chat ID канала не настроен")
        try:
            chat_id = int(chat_raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Некорректный chat_id в настройках") from exc
        mid = await _send_telegram(chat_id, text)
        if mid is None:
            raise HTTPException(status_code=502, detail="Не удалось отправить в Telegram канал")
        return {"ok": True, "telegram_message_id": mid}

    if body.target == "telegram_user":
        if not body.user_id:
            raise HTTPException(status_code=400, detail="Нужен user_id для telegram_user")
        try:
            uid = UUID(body.user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Некорректный user_id") from exc
        user = (await session.execute(select(User).where(User.id == uid))).scalar_one_or_none()
        if user is None or user.telegram_id is None:
            raise HTTPException(status_code=404, detail="Пользователь не найден или Telegram не привязан")
        mid = await _send_telegram(int(user.telegram_id), text)
        if mid is None:
            raise HTTPException(status_code=502, detail="Не удалось отправить в Telegram пользователю")
        return {"ok": True, "telegram_message_id": mid}

    target_email = (body.email or "").strip()
    if not target_email and body.user_id:
        try:
            uid = UUID(body.user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Некорректный user_id") from exc
        user = (await session.execute(select(User).where(User.id == uid))).scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        target_email = (user.notification_email or user.email or "").strip()
    if not target_email:
        raise HTTPException(status_code=400, detail="Нужен email или user_id")
    subj = (body.subject or "").strip() or "Сообщение от PingWin"
    html = f"<div style='font-family:Arial,sans-serif;white-space:pre-wrap'>{text}</div><br><div>🐧 <a href='https://pingwin.pro'>pingwin.pro</a></div>"
    ok = send_html_email(target_email, subj, text, html)
    if not ok:
        raise HTTPException(status_code=502, detail="Не удалось отправить email")
    return {"ok": True}


BOT_INFO_KEY = "telegram_bot_info_message"


@router.get("/telegram-bot-info")
async def get_telegram_bot_info(
    _: User = Depends(require_superadmin),
    session: AsyncSession = Depends(get_async_session),
):
    """Get the message shown in bot's «Получить информацию» button."""
    row = (
        await session.execute(select(AppSetting).where(AppSetting.key == BOT_INFO_KEY))
    ).scalar_one_or_none()
    return {"message": (row.value if row else "") or ""}


class TelegramBotInfoBody(BaseModel):
    message: str = Field(default="", max_length=10000)


@router.put("/telegram-bot-info")
async def put_telegram_bot_info(
    body: TelegramBotInfoBody,
    _: User = Depends(require_superadmin),
    session: AsyncSession = Depends(get_async_session),
):
    """Set the message shown in bot's «Получить информацию» button."""
    val = (body.message or "").strip() or None
    row = (
        await session.execute(select(AppSetting).where(AppSetting.key == BOT_INFO_KEY))
    ).scalar_one_or_none()
    if row:
        row.value = val
    else:
        session.add(AppSetting(key=BOT_INFO_KEY, value=val))
    await session.commit()
    return {"ok": True, "message": val or ""}


@router.post("/ml/sync-leagues")
async def admin_ml_sync_leagues(
    _: User = Depends(require_superadmin),
):
    """Синхронизация лиг из main DB в ML-базу."""
    from app.ml.pipeline import sync_leagues_to_ml

    result = await sync_leagues_to_ml()
    return {"ok": True, **result}


@router.post("/ml/sync-players")
async def admin_ml_sync_players(
    _: User = Depends(require_superadmin),
):
    """Синхронизация всех игроков из main DB в ML-базу (линия, лайв, архив)."""
    from app.ml.pipeline import sync_players_to_ml

    result = await sync_players_to_ml()
    return {"ok": True, **result}


@router.post("/ml/load-archive")
async def admin_ml_load_archive(
    _: User = Depends(require_superadmin),
    days: int = Query(default=90, ge=1, le=365),
):
    """Загрузка завершённых матчей из архива BetsAPI в main DB. Нужно для первичного наполнения."""
    from app.services.betsapi_table_tennis import load_archive_to_main

    result = await load_archive_to_main(days_back=days, max_pages_per_day=10)
    return {"ok": True, **result}


@router.get("/ml/verify")
async def admin_ml_verify(
    _: User = Depends(require_superadmin),
):
    """Проверка: все ли данные из main DB есть в ML. Сравнение main vs ML."""
    from sqlalchemy import text
    from app.ml.db import get_ml_session

    from app.db.session import async_session_maker

    main = {}
    async with async_session_maker() as session:
        # Main: finished матчи со счётом (то, что должно быть в ML)
        r = await session.execute(
            text("""
                SELECT COUNT(*) FROM table_tennis_line_events
                WHERE status = 'finished' AND live_sets_score IS NOT NULL
                  AND live_sets_score LIKE '%-%'
            """)
        )
        main["matches"] = int(r.scalar_one() or 0)

        # Main: уникальные игроки (home + away)
        r = await session.execute(
            text("""
                SELECT COUNT(*) FROM (
                    SELECT home_id FROM table_tennis_line_events WHERE home_id IS NOT NULL AND TRIM(home_id) != ''
                    UNION
                    SELECT away_id FROM table_tennis_line_events WHERE away_id IS NOT NULL AND TRIM(away_id) != ''
                ) t
            """)
        )
        main["players"] = int(r.scalar_one() or 0)

        # Main: уникальные лиги
        try:
            r = await session.execute(
                text("""
                    SELECT COUNT(*) FROM (
                        SELECT DISTINCT league_id FROM table_tennis_line_events
                        WHERE league_id IS NOT NULL AND TRIM(league_id) != ''
                        UNION
                        SELECT id FROM table_tennis_leagues WHERE id IS NOT NULL AND TRIM(id) != ''
                    ) t
                """)
            )
        except Exception:
            r = await session.execute(
                text("""
                    SELECT COUNT(DISTINCT league_id) FROM table_tennis_line_events
                    WHERE league_id IS NOT NULL AND TRIM(league_id) != ''
                """)
            )
        main["leagues"] = int(r.scalar_one() or 0)

    ml_session = get_ml_session()
    ml = {}
    try:
        ml["matches"] = int(ml_session.execute(text("SELECT COUNT(*) FROM matches")).scalar_one() or 0)
        ml["players"] = int(ml_session.execute(text("SELECT COUNT(*) FROM players")).scalar_one() or 0)
        try:
            ml["leagues"] = int(ml_session.execute(text("SELECT COUNT(*) FROM leagues")).scalar_one() or 0)
        except Exception:
            ml["leagues"] = 0
    finally:
        ml_session.close()

    diff = {
        "matches": main["matches"] - ml["matches"],
        "players": main["players"] - ml["players"],
        "leagues": main["leagues"] - ml["leagues"],
    }
    ok = all(v <= 0 for v in diff.values())
    return {
        "main": main,
        "ml": ml,
        "diff": diff,
        "ok": ok,
        "message": "Все данные в ML" if ok else f"Не хватает в ML: матчей {max(0, diff['matches'])}, игроков {max(0, diff['players'])}, лиг {max(0, diff['leagues'])}",
    }


def _ml_table_count(s, table: str) -> int:
    try:
        r = s.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
        return int(r or 0)
    except Exception:
        return 0


@router.get("/ml/stats")
async def admin_ml_stats(
    _: User = Depends(require_superadmin),
):
    """Статистика ML-базы: matches, match_features, players, leagues."""
    from app.ml.db import get_ml_session

    s = get_ml_session()
    try:
        matches = _ml_table_count(s, "matches")
        features = _ml_table_count(s, "match_features")
        players = _ml_table_count(s, "players")
        leagues = _ml_table_count(s, "leagues")
        return {"matches": matches, "match_features": features, "players": players, "leagues": leagues}
    finally:
        s.close()


@router.get("/ml/dashboard")
async def admin_ml_dashboard(
    _: User = Depends(require_superadmin),
):
    """Дашборд ML: наполнение таблиц, сравнение main→ML, прогресс операций."""
    from sqlalchemy import text
    from app.ml.db import get_ml_session
    from app.services.ml_progress import get_progress
    from app.services.ml_queue import queue_size

    s = get_ml_session()
    tables: dict[str, int] = {}
    try:
        for t in (
            "matches", "match_sets", "match_features", "odds",
            "players", "leagues", "player_ratings",
            "player_daily_stats", "player_style", "player_elo_history",
            "suspicious_matches", "league_performance", "signals",
        ):
            tables[t] = _ml_table_count(s, t)
    finally:
        s.close()

    matches = tables.get("matches", 0) or 1
    players = tables.get("players", 0) or 1
    fill = {
        "match_features": round(100 * tables.get("match_features", 0) / matches, 1) if matches else 0,
        "odds": round(100 * tables.get("odds", 0) / matches, 1) if matches else 0,
        "player_ratings": round(100 * tables.get("player_ratings", 0) / players, 1) if players else 0,
        "player_daily_stats": tables.get("player_daily_stats", 0),
        "player_style": round(100 * tables.get("player_style", 0) / players, 1) if players else 0,
        "player_elo_history": tables.get("player_elo_history", 0),
    }

    main_counts = {"matches": 0, "players": 0, "leagues": 0}
    try:
        from app.db.session import async_session_maker
        async with async_session_maker() as session:
            r = await session.execute(
                text("""
                    SELECT COUNT(*) FROM table_tennis_line_events
                    WHERE status = 'finished' AND live_sets_score IS NOT NULL AND live_sets_score LIKE '%-%'
                """)
            )
            main_counts["matches"] = int(r.scalar_one() or 0)
            r = await session.execute(
                text("""
                    SELECT COUNT(*) FROM (
                        SELECT home_id FROM table_tennis_line_events WHERE home_id IS NOT NULL AND TRIM(home_id) != ''
                        UNION SELECT away_id FROM table_tennis_line_events WHERE away_id IS NOT NULL AND TRIM(away_id) != ''
                    ) t
                """)
            )
            main_counts["players"] = int(r.scalar_one() or 0)
            try:
                r = await session.execute(
                    text("SELECT COUNT(DISTINCT league_id) FROM table_tennis_line_events WHERE league_id IS NOT NULL")
                )
                main_counts["leagues"] = int(r.scalar_one() or 0)
            except Exception:
                pass
    except Exception:
        pass

    diff = {
        "matches": main_counts["matches"] - tables.get("matches", 0),
        "players": main_counts["players"] - tables.get("players", 0),
        "leagues": main_counts["leagues"] - tables.get("leagues", 0),
    }
    sync_ok = diff["matches"] <= 0 and diff["players"] <= 0 and diff["leagues"] <= 0

    return {
        "tables": tables,
        "fill_pct": fill,
        "main": main_counts,
        "diff": diff,
        "sync_ok": sync_ok,
        "progress": get_progress(),
        "queue_size": queue_size(),
    }


@router.get("/ml/progress")
async def admin_ml_progress(_: User = Depends(require_superadmin)):
    """Прогресс ML-операций: sync, backfill, retrain."""
    from app.services.ml_progress import get_progress
    return get_progress()


@router.post("/ml/reset-progress")
async def admin_ml_reset_progress(
    _: User = Depends(require_superadmin),
    op: str | None = Query(default=None, description="sync|backfill|retrain|full_rebuild или пусто=все"),
):
    """Сброс зависшего прогресса. Используйте если retrain/sync «застрял» в статусе running."""
    from app.services.ml_progress import reset_progress
    reset_progress(op)
    return {"ok": True, "message": f"Прогресс сброшен: {op or 'все'}"}


@router.post("/ml/sync")
async def admin_ml_sync(
    _: User = Depends(require_superadmin),
    limit: int = Query(default=500, ge=1, le=50000),
    days_back: int = Query(default=0, ge=0, le=36500, description="0 = весь архив"),
    full: bool = Query(default=False, description="Полная загрузка всей основной БД"),
):
    """Синхронизация finished матчей в ML-базу. Задача идёт в очередь, воркер выполняет отдельно."""
    from app.services.ml_progress import is_running
    from app.services.ml_queue import enqueue

    if is_running("sync"):
        return {"ok": False, "error": "Синхронизация уже выполняется"}
    if not enqueue("sync", {"limit": limit, "days_back": days_back, "full": full}):
        return {"ok": False, "error": "Не удалось добавить в очередь"}
    return {"ok": True, "message": "Задача добавлена в очередь"}


@router.post("/ml/backfill-features")
async def admin_ml_backfill_features(
    _: User = Depends(require_superadmin),
    limit: int = Query(default=50000, ge=1, le=600000),
    workers: int = Query(default=0, ge=0, le=16, description="0 = из ML_BACKFILL_WORKERS"),
):
    """Расчёт фичей (параллельно, workers потоков). Задача идёт в очередь."""
    from app.services.ml_progress import is_running
    from app.services.ml_queue import enqueue

    if is_running("backfill"):
        return {"ok": False, "error": "Backfill уже выполняется"}
    params = {"limit": limit}
    if workers:
        params["workers"] = workers
    if not enqueue("backfill", params):
        return {"ok": False, "error": "Не удалось добавить в очередь"}
    return {"ok": True, "message": "Задача добавлена в очередь"}


@router.post("/ml/retrain")
async def admin_ml_retrain(
    _: User = Depends(require_superadmin),
    min_rows: int = Query(default=100, ge=50, le=10000),
):
    """Переобучение ML-моделей. Задача идёт в очередь."""
    from app.services.ml_progress import is_running
    from app.services.ml_queue import enqueue

    if is_running("retrain"):
        return {"ok": False, "error": "Переобучение уже выполняется"}
    if not enqueue("retrain", {"min_rows": min_rows}):
        return {"ok": False, "error": "Не удалось добавить в очередь"}
    return {"ok": True, "message": "Задача добавлена в очередь"}


@router.get("/ml/league-performance")
async def admin_ml_league_performance(
    _: User = Depends(require_superadmin),
):
    """Прибыльные лиги: ROI, upset_rate. Сигналы только если roi>5%, matches>300, upset<40%."""
    from sqlalchemy import text
    from app.ml.db import get_ml_session

    s = get_ml_session()
    try:
        rows = s.execute(
            text("""
                SELECT lp.league_id, l.name, lp.matches, lp.wins, lp.losses,
                       lp.roi_pct, lp.avg_ev, lp.avg_odds, lp.upset_rate, lp.underdog_wins
                FROM league_performance lp
                LEFT JOIN leagues l ON l.id = lp.league_id
                ORDER BY lp.roi_pct DESC NULLS LAST
            """)
        ).fetchall()
        return {
            "leagues": [
                {
                    "league_id": r[0],
                    "league_name": r[1] or r[0],
                    "matches": r[2],
                    "wins": r[3],
                    "losses": r[4],
                    "roi_pct": round(float(r[5] or 0), 2),
                    "avg_ev": round(float(r[6] or 0), 4),
                    "avg_odds": round(float(r[7] or 0), 2),
                    "upset_rate": round(float(r[8] or 0) * 100, 1),
                    "underdog_wins": r[9],
                    "passes_filter": (
                        r[2] and r[2] >= 300
                        and (r[5] or 0) >= 5
                        and (r[8] or 0) <= 0.4
                    ),
                }
                for r in rows
            ]
        }
    except Exception as e:
        if "does not exist" in str(e).lower() or "relation" in str(e).lower():
            return {"leagues": [], "message": "Запустите миграцию 05_league_performance.sql"}
        return {"leagues": [], "error": str(e)}
    finally:
        s.close()


@router.post("/ml/player-stats")
async def admin_ml_player_stats(
    _: User = Depends(require_superadmin),
    limit: int = Query(default=10000, ge=100, le=100000),
):
    """Backfill player_daily_stats, player_style, player_elo_history. Задача в очередь."""
    from app.services.ml_progress import is_running
    from app.services.ml_queue import enqueue

    if is_running("player_stats"):
        return {"ok": False, "error": "Player stats backfill уже выполняется"}
    if not enqueue("player_stats", {"limit": limit}):
        return {"ok": False, "error": "Не удалось добавить в очередь"}
    return {"ok": True, "message": "Задача добавлена в очередь"}


@router.post("/ml/league-performance")
async def admin_ml_league_performance_update(
    _: User = Depends(require_superadmin),
    limit: int = Query(default=10000, ge=100, le=200000),
):
    """Пересчёт league_performance. Задача идёт в очередь."""
    from app.services.ml_progress import is_running
    from app.services.ml_queue import enqueue

    if is_running("league_performance"):
        return {"ok": False, "error": "Обновление уже выполняется"}
    if not enqueue("league_performance", {"limit": limit}):
        return {"ok": False, "error": "Не удалось добавить в очередь"}
    return {"ok": True, "message": "Задача добавлена в очередь"}


@router.post("/ml/full-rebuild")
async def admin_ml_full_rebuild(
    _: User = Depends(require_superadmin),
    sync_limit: int = Query(default=50000, ge=1000, le=200000),
    backfill_limit: int = Query(default=100000, ge=1000, le=200000),
    player_stats_limit: int = Query(default=50000, ge=1000, le=150000),
    league_limit: int = Query(default=50000, ge=1000, le=150000),
    min_rows: int = Query(default=500, ge=100, le=5000),
):
    """Полный цикл: sync → backfill → player_stats → league_performance → retrain. Задача в очередь."""
    from app.services.ml_progress import is_running
    from app.services.ml_queue import enqueue

    if is_running("full_rebuild") or is_running("sync"):
        return {"ok": False, "error": "Full rebuild или sync уже выполняется"}
    if not enqueue("full_rebuild", {
        "sync_limit": sync_limit,
        "backfill_limit": backfill_limit,
        "player_stats_limit": player_stats_limit,
        "league_limit": league_limit,
        "min_rows": min_rows,
    }):
        return {"ok": False, "error": "Не удалось добавить в очередь"}
    return {"ok": True, "message": "Full rebuild добавлен в очередь (3–10 мин)"}
