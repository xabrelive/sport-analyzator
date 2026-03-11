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

ALLOWED_SERVICE_KEYS = {"analytics", "vip_channel"}
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
