"""Admin API: superadmin-only service management."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, delete, func, or_, select, text, update
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
from app.models.telegram_channel_notification import TelegramChannelNotification
from app.models.telegram_channel_marker import TelegramChannelMarker
from app.models.user_forecast_notification import UserForecastNotification
from app.models.table_tennis_forecast_v2 import TableTennisForecastV2
from app.models.table_tennis_forecast_early_scan import TableTennisForecastEarlyScan
from app.models.table_tennis_line_event import TableTennisLineEvent
from app.services.email import send_html_email
from app.services.telegram_channel_dispatcher import _load_dispatch_cfg
from app.services.vip_channel_access import send_vip_invite_to_user

router = APIRouter()

ALLOWED_SERVICE_KEYS = {"analytics", "analytics_no_ml", "vip_channel"}
ALLOWED_MESSAGE_TARGETS = {"free_channel", "vip_channel", "no_ml_channel", "telegram_user", "telegram_all_users", "email"}
DISPATCH_CFG_KEY = "telegram_dispatch_config"


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


def _channel_token(target: str | None) -> str:
    if target == "free_channel":
        return (settings.telegram_signals_free_bot_token or "").strip()
    if target == "vip_channel":
        return (settings.telegram_signals_vip_bot_token or "").strip()
    if target == "no_ml_channel":
        return (settings.telegram_signals_no_ml_bot_token or "").strip()
    return (settings.telegram_bot_token or "").strip()


async def _send_telegram(chat_id: int, text: str, *, target: str | None = None, image_url: str | None = None) -> int | None:
    token = _channel_token(target)
    if not token:
        return None
    method = "sendPhoto" if (image_url or "").strip() else "sendMessage"
    payload = {"chat_id": chat_id, "parse_mode": "HTML"}
    if method == "sendPhoto":
        payload["photo"] = (image_url or "").strip()
        payload["caption"] = text
    else:
        payload["text"] = text
        payload["disable_web_page_preview"] = True
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(f"https://api.telegram.org/bot{token}/{method}", json=payload)
    if resp.status_code != 200:
        return None
    data = resp.json()
    if not data.get("ok"):
        return None
    return int((data.get("result") or {}).get("message_id") or 0) or None


async def _send_telegram_with_images(
    chat_id: int,
    text: str,
    *,
    target: str | None = None,
    image_url: str | None = None,
    image_urls: list[str] | None = None,
) -> int | None:
    token = _channel_token(target)
    if not token:
        return None
    imgs = [u.strip() for u in (image_urls or []) if u and u.strip()]
    if image_url and image_url.strip():
        imgs.append(image_url.strip())
    # dedupe preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for u in imgs:
        if u in seen:
            continue
        seen.add(u)
        deduped.append(u)
    if len(deduped) <= 1:
        return await _send_telegram(
            chat_id=chat_id,
            text=text,
            target=target,
            image_url=(deduped[0] if deduped else None),
        )

    media = []
    for i, u in enumerate(deduped):
        if i == 0:
            media.append({"type": "photo", "media": u, "caption": text, "parse_mode": "HTML"})
        else:
            media.append({"type": "photo", "media": u})
    payload = {"chat_id": chat_id, "media": media}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"https://api.telegram.org/bot{token}/sendMediaGroup", json=payload)
    if resp.status_code != 200:
        return None
    data = resp.json()
    if not data.get("ok"):
        return None
    first = (data.get("result") or [{}])[0]
    return int(first.get("message_id") or 0) or None


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
    service_key: str = Field(..., pattern="^(analytics|analytics_no_ml|vip_channel)$")
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
    target: str = Field(..., pattern="^(free_channel|vip_channel|no_ml_channel|telegram_user|telegram_all_users|email)$")
    text: str = Field(..., min_length=1, max_length=5000)
    user_id: str | None = None
    email: str | None = None
    subject: str | None = None
    image_url: str | None = None
    image_urls: list[str] | None = None


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

    if body.target in {"free_channel", "vip_channel", "no_ml_channel"}:
        if body.target == "free_channel":
            chat_raw = settings.telegram_signals_free_chat_id
        elif body.target == "vip_channel":
            chat_raw = settings.telegram_signals_vip_chat_id
        else:
            chat_raw = settings.telegram_signals_no_ml_chat_id
        chat_raw = (chat_raw or "").strip()
        if not chat_raw:
            raise HTTPException(status_code=400, detail="Chat ID канала не настроен")
        try:
            chat_id = int(chat_raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Некорректный chat_id в настройках") from exc
        mid = await _send_telegram_with_images(
            chat_id=chat_id,
            text=text,
            target=body.target,
            image_url=(body.image_url or "").strip() or None,
            image_urls=body.image_urls or [],
        )
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
        mid = await _send_telegram_with_images(
            chat_id=int(user.telegram_id),
            text=text,
            image_url=(body.image_url or "").strip() or None,
            image_urls=body.image_urls or [],
        )
        if mid is None:
            raise HTTPException(status_code=502, detail="Не удалось отправить в Telegram пользователю")
        return {"ok": True, "telegram_message_id": mid}

    if body.target == "telegram_all_users":
        users = (
            await session.execute(
                select(User).where(User.telegram_id.is_not(None))
            )
        ).scalars().all()
        total = 0
        sent = 0
        for user in users:
            total += 1
            try:
                mid = await _send_telegram_with_images(
                    chat_id=int(user.telegram_id),  # type: ignore[arg-type]
                    text=text,
                    image_url=(body.image_url or "").strip() or None,
                    image_urls=body.image_urls or [],
                )
                if mid is not None:
                    sent += 1
            except Exception:
                continue
        return {"ok": True, "total": total, "sent": sent}

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


@router.get("/telegram-dispatch-config")
async def get_telegram_dispatch_config(
    _: User = Depends(require_superadmin),
    session: AsyncSession = Depends(get_async_session),
):
    cfg = await _load_dispatch_cfg(session)
    row = (await session.execute(select(AppSetting).where(AppSetting.key == DISPATCH_CFG_KEY))).scalars().one_or_none()
    has_saved = bool(row and (row.value or "").strip())
    try:
        raw_cfg = json.loads(row.value) if has_saved else None
    except Exception:
        raw_cfg = None
    return {"config": cfg, "raw_config": raw_cfg, "has_saved": has_saved}


class TelegramDispatchConfigBody(BaseModel):
    config: dict


@router.put("/telegram-dispatch-config")
async def put_telegram_dispatch_config(
    body: TelegramDispatchConfigBody,
    _: User = Depends(require_superadmin),
    session: AsyncSession = Depends(get_async_session),
):
    serialized = json.dumps(body.config, ensure_ascii=False)
    row = (
        await session.execute(select(AppSetting).where(AppSetting.key == DISPATCH_CFG_KEY))
    ).scalars().one_or_none()
    if row:
        row.value = serialized
    else:
        session.add(AppSetting(key=DISPATCH_CFG_KEY, value=serialized))
    await session.commit()
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
    ).scalars().one_or_none()
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
    ).scalars().one_or_none()
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
    days: int | None = Query(default=None, ge=1, le=365),
    date_from: str | None = Query(default=None, description="YYYYMMDD"),
    date_to: str | None = Query(default=None, description="YYYYMMDD"),
):
    """Загрузка завершённых матчей из архива BetsAPI в main DB. Нужно для первичного наполнения.
    Либо days (дней назад), либо date_from+date_to."""
    from datetime import date
    from app.services.betsapi_table_tennis import load_archive_to_main

    if date_from and date_to:
        df = date(int(date_from[:4]), int(date_from[4:6]), int(date_from[6:8]))
        dt = date(int(date_to[:4]), int(date_to[4:6]), int(date_to[6:8]))
        result = await load_archive_to_main(date_from=df, date_to=dt, max_pages_per_day=10)
    else:
        result = await load_archive_to_main(days_back=days or 90, max_pages_per_day=10)
    return {"ok": True, **result}


def _compute_streaks(statuses: list[str]) -> dict:
    """Считает серии подряд hit/miss. statuses — список 'hit'|'miss' в хронологическом порядке."""
    max_streak_miss = 0
    max_streak_hit = 0
    current_streak_miss = 0
    current_streak_hit = 0
    run_miss = 0
    run_hit = 0
    for s in statuses:
        if s == "miss":
            run_miss += 1
            run_hit = 0
            max_streak_miss = max(max_streak_miss, run_miss)
        else:
            run_hit += 1
            run_miss = 0
            max_streak_hit = max(max_streak_hit, run_hit)
    current_streak_miss = run_miss
    current_streak_hit = run_hit
    return {
        "max_streak_miss": max_streak_miss,
        "max_streak_hit": max_streak_hit,
        "current_streak_miss": current_streak_miss,
        "current_streak_hit": current_streak_hit,
    }


@router.get("/ml/no-ml-stats")
async def admin_ml_no_ml_stats(
    _: User = Depends(require_superadmin),
    session: AsyncSession = Depends(get_async_session),
):
    """Статистика Аналитики без ML: угадано/не угадано всего и по лигам; серии промахов; лиги с % < 50%."""
    from app.models.table_tennis_forecast_v2 import TableTennisForecastV2
    from app.models.table_tennis_line_event import TableTennisLineEvent

    # Общие счётчики по каналу no_ml (case для условного подсчёта)
    r = await session.execute(
        select(
            func.count(case((TableTennisForecastV2.status == "hit", 1))).label("hit"),
            func.count(case((TableTennisForecastV2.status == "miss", 1))).label("miss"),
        ).select_from(TableTennisForecastV2).where(
            TableTennisForecastV2.channel == "no_ml",
            TableTennisForecastV2.status.in_(["hit", "miss"]),
        )
    )
    row = r.one()
    total_hit = int(row.hit or 0)
    total_miss = int(row.miss or 0)

    # Серии не угадано / угадано: по одному исходу на матч (market=match), по времени начала матча
    r_streak = await session.execute(
        select(TableTennisForecastV2.status, TableTennisLineEvent.starts_at)
        .select_from(TableTennisForecastV2)
        .join(
            TableTennisLineEvent,
            TableTennisLineEvent.id == TableTennisForecastV2.event_id,
        )
        .where(
            TableTennisForecastV2.channel == "no_ml",
            TableTennisForecastV2.market == "match",
            TableTennisForecastV2.status.in_(["hit", "miss"]),
        )
        .order_by(TableTennisLineEvent.starts_at.asc())
    )
    statuses = [row[0] for row in r_streak.fetchall()]
    streaks = _compute_streaks(statuses) if statuses else {}

    # По лигам: hit и miss на лигу
    subq = (
        select(
            TableTennisLineEvent.league_id,
            TableTennisLineEvent.league_name,
            func.count(case((TableTennisForecastV2.status == "hit", 1))).label("hit"),
            func.count(case((TableTennisForecastV2.status == "miss", 1))).label("miss"),
        )
        .select_from(TableTennisForecastV2)
        .join(
            TableTennisLineEvent,
            TableTennisLineEvent.id == TableTennisForecastV2.event_id,
        )
        .where(
            TableTennisForecastV2.channel == "no_ml",
            TableTennisForecastV2.status.in_(["hit", "miss"]),
        )
        .group_by(TableTennisLineEvent.league_id, TableTennisLineEvent.league_name)
    )
    r = await session.execute(subq)
    by_league = []
    for x in r.all():
        hit = int(x.hit or 0)
        miss = int(x.miss or 0)
        total = hit + miss
        hit_rate_pct = round((hit / total) * 100, 1) if total else 0.0
        by_league.append({
            "league_id": x.league_id,
            "league_name": x.league_name,
            "hit": hit,
            "miss": miss,
            "total": total,
            "hit_rate_pct": hit_rate_pct,
        })
    leagues_bad = [x for x in by_league if x["miss"] > x["hit"]]
    leagues_bad.sort(key=lambda t: (t["miss"] - t["hit"], t["miss"]), reverse=True)
    # Лиги с процентом угадывания < 50% и хотя бы 5 исходов — кандидаты на exclude или invert.
    min_sample = 5
    leagues_weak = [x for x in by_league if x["total"] >= min_sample and x["hit_rate_pct"] < 50]
    leagues_weak.sort(key=lambda t: (t["hit_rate_pct"], -t["total"]))

    return {
        "total_hit": total_hit,
        "total_miss": total_miss,
        "streaks": streaks,
        "leagues_bad": leagues_bad,
        "leagues_weak": leagues_weak,
        "by_league": by_league,
    }


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


@router.get("/ml/sync-audit")
async def admin_ml_sync_audit(
    _: User = Depends(require_superadmin),
    sample_limit: int = Query(default=5000, ge=100, le=200000),
    missing_preview: int = Query(default=20, ge=1, le=200),
):
    """Ручная сверка покрытия main↔ML и preview пропущенных матчей."""
    from app.ml.db import get_ml_session
    from app.db.session import async_session_maker

    main_finished = 0
    main_players = 0
    main_leagues = 0
    recent_main_ids: list[str] = []

    async with async_session_maker() as session:
        r = await session.execute(
            text(
                "SELECT COUNT(*) FROM table_tennis_line_events "
                "WHERE status='finished' AND live_sets_score IS NOT NULL"
            )
        )
        main_finished = int(r.scalar_one() or 0)
        r = await session.execute(
            text(
                "SELECT COUNT(*) FROM ("
                " SELECT home_id AS pid FROM table_tennis_line_events WHERE home_id IS NOT NULL AND TRIM(home_id) != ''"
                " UNION"
                " SELECT away_id AS pid FROM table_tennis_line_events WHERE away_id IS NOT NULL AND TRIM(away_id) != ''"
                ") t"
            )
        )
        main_players = int(r.scalar_one() or 0)
        r = await session.execute(
            text(
                "SELECT COUNT(DISTINCT league_id) FROM table_tennis_line_events "
                "WHERE league_id IS NOT NULL AND TRIM(league_id) != ''"
            )
        )
        main_leagues = int(r.scalar_one() or 0)
        rows = await session.execute(
            text(
                "SELECT id FROM table_tennis_line_events "
                "WHERE status='finished' AND live_sets_score IS NOT NULL "
                "ORDER BY starts_at DESC LIMIT :lim"
            ),
            {"lim": sample_limit},
        )
        recent_main_ids = [str(x[0]) for x in rows.all()]

    ml_session = get_ml_session()
    try:
        ml_matches = _ml_table_count(ml_session, "matches")
        ml_players = _ml_table_count(ml_session, "players")
        ml_leagues = _ml_table_count(ml_session, "leagues")

        existing_recent: set[str] = set()
        if recent_main_ids:
            rows = ml_session.execute(
                text("SELECT external_id FROM matches WHERE external_id = ANY(:ids)"),
                {"ids": recent_main_ids},
            ).fetchall()
            existing_recent = {str(x[0]) for x in rows}
        missing_recent = [eid for eid in recent_main_ids if eid not in existing_recent]
    finally:
        ml_session.close()

    return {
        "main_finished_events": main_finished,
        "ml_matches": ml_matches,
        "delta_matches_main_minus_ml": main_finished - ml_matches,
        "main_players": main_players,
        "ml_players": ml_players,
        "delta_players_main_minus_ml": main_players - ml_players,
        "main_leagues": main_leagues,
        "ml_leagues": ml_leagues,
        "delta_leagues_main_minus_ml": main_leagues - ml_leagues,
        "recent_sample_checked": len(recent_main_ids),
        "recent_missing_count": len(missing_recent),
        "recent_missing_preview": missing_recent[:missing_preview],
    }


@router.post("/ml/request-full-sync")
async def admin_ml_request_full_sync(
    _: User = Depends(require_superadmin),
):
    """Ставит флаг: следующий проход ml_sync_loop выполнит полный sync."""
    from app.db.session import async_session_maker

    async with async_session_maker() as session:
        row = (
            await session.execute(
                select(AppSetting).where(AppSetting.key == "ml_sync_force_full_once")
            )
        ).scalar_one_or_none()
        if row:
            row.value = "1"
        else:
            session.add(AppSetting(key="ml_sync_force_full_once", value="1"))
        await session.commit()
    return {"ok": True, "message": "Флаг full sync установлен. Будет выполнен на следующем цикле ml_sync_loop."}


@router.post("/forecasts/clear-all")
async def admin_forecasts_clear_all(
    _: User = Depends(require_superadmin),
):
    """Удаляет все прогнозы V2, статистику каналов и денормализованные поля.
    После вызова forecast_v2_loop и no_ml_forecast_loop заново рассчитают и покажут прогнозы."""
    from app.db.session import async_session_maker

    async with async_session_maker() as session:
        # Логи публикаций в каналах (free, vip, no_ml)
        r1 = await session.execute(delete(TelegramChannelNotification))
        n_notif = r1.rowcount
        # Логи доставки пользователям (telegram/email)
        r2 = await session.execute(delete(UserForecastNotification))
        n_user_notif = r2.rowcount
        # Маркеры слотов каналов (чтобы снова публиковать)
        r3 = await session.execute(delete(TelegramChannelMarker))
        n_markers = r3.rowcount
        # Прогнозы V2 (CASCADE удалит table_tennis_forecast_explanations)
        r4 = await session.execute(delete(TableTennisForecastV2))
        n_forecasts = r4.rowcount
        # Денормализованные forecast/forecast_confidence на матчах
        r5 = await session.execute(
            update(TableTennisLineEvent).where(
                or_(
                    TableTennisLineEvent.forecast.is_not(None),
                    TableTennisLineEvent.forecast_confidence.is_not(None),
                )
            ).values(forecast=None, forecast_confidence=None)
        )
        n_line_cleared = r5.rowcount
        # Ранний скрининг (заново заполнится early_scan_loop)
        r6 = await session.execute(delete(TableTennisForecastEarlyScan))
        n_early_scan = r6.rowcount
        await session.commit()

    return {
        "ok": True,
        "message": "Все прогнозы и статистика каналов удалены. Прогнозы будут заново рассчитаны в следующих циклах forecast_v2_loop и no_ml_forecast_loop.",
        "deleted": {
            "telegram_channel_notifications": n_notif,
            "user_forecast_notifications": n_user_notif,
            "telegram_channel_markers": n_markers,
            "table_tennis_forecasts_v2": n_forecasts,
            "line_events_forecast_cleared": n_line_cleared,
            "table_tennis_forecast_early_scan": n_early_scan,
        },
    }


@router.post("/forecasts/clear-ml")
async def admin_forecasts_clear_ml(
    _: User = Depends(require_superadmin),
):
    """Удаляет только ML прогнозы/статистику (paid/free/vip/bot_signals), не трогая no_ml."""
    from app.db.session import async_session_maker

    no_ml_channels = ("no_ml", "no_ml_channel")
    ml_channel_notifications = ("free", "vip")

    async with async_session_maker() as session:
        ml_forecast_ids_subq = select(TableTennisForecastV2.id).where(
            ~TableTennisForecastV2.channel.in_(no_ml_channels)
        )

        r1 = await session.execute(
            delete(TelegramChannelNotification).where(
                TelegramChannelNotification.channel.in_(ml_channel_notifications)
            )
        )
        n_notif = r1.rowcount

        r2 = await session.execute(
            delete(UserForecastNotification).where(
                UserForecastNotification.forecast_v2_id.in_(ml_forecast_ids_subq)
            )
        )
        n_user_notif = r2.rowcount

        r3 = await session.execute(
            delete(TelegramChannelMarker).where(
                TelegramChannelMarker.channel.in_(ml_channel_notifications)
            )
        )
        n_markers = r3.rowcount

        r4 = await session.execute(
            delete(TableTennisForecastV2).where(
                ~TableTennisForecastV2.channel.in_(no_ml_channels)
            )
        )
        n_forecasts = r4.rowcount

        r5 = await session.execute(
            update(TableTennisLineEvent)
            .where(
                or_(
                    TableTennisLineEvent.forecast.is_not(None),
                    TableTennisLineEvent.forecast_confidence.is_not(None),
                )
            )
            .values(forecast=None, forecast_confidence=None)
        )
        n_line_cleared = r5.rowcount

        r6 = await session.execute(delete(TableTennisForecastEarlyScan))
        n_early_scan = r6.rowcount

        await session.commit()

    return {
        "ok": True,
        "message": "ML прогнозы и ML статистика очищены. no_ml данные сохранены.",
        "deleted": {
            "telegram_channel_notifications": n_notif,
            "user_forecast_notifications": n_user_notif,
            "telegram_channel_markers": n_markers,
            "table_tennis_forecasts_v2": n_forecasts,
            "line_events_forecast_cleared": n_line_cleared,
            "table_tennis_forecast_early_scan": n_early_scan,
        },
    }


@router.post("/forecasts/clear-no-ml")
async def admin_forecasts_clear_no_ml(
    _: User = Depends(require_superadmin),
):
    """Удаляет только no_ml прогнозы/статистику, не трогая ML."""
    from app.db.session import async_session_maker

    no_ml_channels = ("no_ml", "no_ml_channel")
    no_ml_channel_notifications = ("no_ml_channel",)

    async with async_session_maker() as session:
        no_ml_forecast_ids_subq = select(TableTennisForecastV2.id).where(
            TableTennisForecastV2.channel.in_(no_ml_channels)
        )

        r1 = await session.execute(
            delete(TelegramChannelNotification).where(
                TelegramChannelNotification.channel.in_(no_ml_channel_notifications)
            )
        )
        n_notif = r1.rowcount

        r2 = await session.execute(
            delete(UserForecastNotification).where(
                UserForecastNotification.forecast_v2_id.in_(no_ml_forecast_ids_subq)
            )
        )
        n_user_notif = r2.rowcount

        r3 = await session.execute(
            delete(TelegramChannelMarker).where(
                TelegramChannelMarker.channel.in_(no_ml_channel_notifications)
            )
        )
        n_markers = r3.rowcount

        r4 = await session.execute(
            delete(TableTennisForecastV2).where(
                TableTennisForecastV2.channel.in_(no_ml_channels)
            )
        )
        n_forecasts = r4.rowcount

        await session.commit()

    return {
        "ok": True,
        "message": "no_ml прогнозы и no_ml статистика очищены. ML данные сохранены.",
        "deleted": {
            "telegram_channel_notifications": n_notif,
            "user_forecast_notifications": n_user_notif,
            "telegram_channel_markers": n_markers,
            "table_tennis_forecasts_v2": n_forecasts,
        },
    }


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
    meta: dict[str, str] = {}
    try:
        async with async_session_maker() as session:
            rows = (
                await session.execute(
                    select(AppSetting).where(
                        AppSetting.key.in_(
                            [
                                "ml_last_sync_at_ts",
                                "ml_last_autosync_at_ts",
                                "ml_last_sync_synced",
                                "ml_last_sync_skipped",
                                "ml_last_sync_full",
                                "ml_last_data_pull_at_ts",
                                "ml_last_data_pull_total",
                                "ml_last_data_pull_odds",
                                "ml_last_data_pull_features",
                                "ml_last_retrain_at_ts",
                                "ml_last_retrain_trained",
                                "ml_last_retrain_rows",
                                "ml_last_retrain_path",
                                "ml_last_model_created_at_ts",
                                "ml_last_odds_backfill_at_ts",
                                "ml_last_odds_backfill_added_total",
                                "ml_last_odds_backfill_api_total",
                                "ml_last_odds_backfill_cursor",
                                "ml_v2_last_sync_at_ts",
                                "ml_v2_last_retrain_at_ts",
                                "ml_v2_last_retrain_requested_at_ts",
                                "ml_v2_last_retrain_trained",
                                "ml_v2_last_retrain_rows",
                                "ml_v2_last_model_created_at_ts",
                                "ml_v2_last_retrain_device",
                                "ml_v2_last_kpi",
                            ]
                        )
                    )
                )
            ).scalars().all()
        for r in rows:
            meta[str(r.key)] = str(r.value or "")
    except Exception:
        pass
    meta["ml_engine"] = str(getattr(settings, "ml_engine", "v1"))

    # Если модель обучали вручную (docker run ml_train_gpu), метки в БД не обновляются.
    # Подтягиваем время последней модели с диска, чтобы админка показывала актуальные даты.
    try:
        model_dir = getattr(settings, "ml_model_dir", None) or os.environ.get("ML_MODEL_DIR", "")
        if model_dir and Path(model_dir).is_dir():
            latest_ts = 0
            for p in Path(model_dir).glob("tt_ml_*.joblib"):
                try:
                    mtime = int(p.stat().st_mtime)
                    if mtime > latest_ts:
                        latest_ts = mtime
                except OSError:
                    continue
            if latest_ts > 0:
                db_created = int(meta.get("ml_last_model_created_at_ts") or 0)
                if latest_ts >= db_created:
                    meta["ml_last_model_created_at_ts"] = str(latest_ts)
                db_retrain = int(meta.get("ml_last_retrain_at_ts") or 0)
                if latest_ts > db_retrain:
                    meta["ml_last_retrain_at_ts"] = str(latest_ts)
                    meta["ml_last_retrain_trained"] = "1"
    except Exception:
        pass

    return {
        "tables": tables,
        "fill_pct": fill,
        "main": main_counts,
        "diff": diff,
        "sync_ok": sync_ok,
        "progress": get_progress(),
        "queue_size": queue_size(),
        "meta": meta,
    }


@router.get("/ml/v2/status")
async def admin_ml_v2_status(
    _: User = Depends(require_superadmin),
):
    """Статус ML v2: ClickHouse таблицы, мета автосинка/retrain, очередь, KPI."""
    from app.db.session import async_session_maker
    from app.ml_v2.ch_client import get_ch_client
    from app.services.ml_progress import get_progress
    from app.services.ml_queue import queue_size

    tables: dict[str, int] = {
        "matches": 0,
        "match_sets": 0,
        "match_features": 0,
        "player_match_stats": 0,
        "player_daily_stats": 0,
        "player_elo_history": 0,
        "match_sets_uniq_matches": 0,
        "matches_uniq_matches": 0,
        "match_sets_gap_count": 0,
    }
    ch_ok = True
    ch_error = ""
    try:
        client = get_ch_client()
        for table in (
            "matches",
            "match_sets",
            "match_features",
            "player_match_stats",
            "player_daily_stats",
            "player_elo_history",
        ):
            try:
                rows = client.query(f"SELECT count() FROM ml.{table}").result_rows
                tables[table] = int((rows[0][0] if rows else 0) or 0)
            except Exception:
                pass
        try:
            set_uniq_rows = client.query("SELECT uniqExact(match_id) FROM ml.match_sets").result_rows
            tables["match_sets_uniq_matches"] = int((set_uniq_rows[0][0] if set_uniq_rows else 0) or 0)
        except Exception:
            pass
        try:
            mu = client.query("SELECT uniqExact(match_id) FROM ml.matches").result_rows
            tables["matches_uniq_matches"] = int((mu[0][0] if mu else 0) or 0)
        except Exception:
            tables["matches_uniq_matches"] = int(tables.get("matches", 0))
        tables["match_sets_gap_count"] = max(0, int(tables.get("matches_uniq_matches", 0)) - int(tables.get("match_sets_uniq_matches", 0)))
    except Exception as exc:
        ch_ok = False
        ch_error = str(exc)

    main_finished = 0
    async with async_session_maker() as session:
        r = await session.execute(
            text(
                "SELECT COUNT(*) FROM table_tennis_line_events "
                "WHERE status='finished' AND live_sets_score IS NOT NULL"
            )
        )
        main_finished = int(r.scalar_one() or 0)

        meta_rows = (
            await session.execute(
                select(AppSetting).where(
                    AppSetting.key.in_(
                        [
                            "ml_v2_last_sync_at_ts",
                            "ml_v2_last_retrain_requested_at_ts",
                            "ml_v2_last_retrain_at_ts",
                            "ml_v2_last_retrain_trained",
                            "ml_v2_last_retrain_rows",
                            "ml_v2_last_model_created_at_ts",
                            "ml_v2_last_retrain_device",
                            "ml_v2_last_kpi",
                        ]
                    )
                )
            )
        ).scalars().all()

    meta: dict[str, str] = {str(row.key): str(row.value or "") for row in meta_rows}
    kpi: dict[str, float] = {}
    try:
        raw_kpi = meta.get("ml_v2_last_kpi")
        if raw_kpi:
            parsed = json.loads(raw_kpi)
            if isinstance(parsed, dict):
                kpi = {
                    "match_hit_rate": float(parsed.get("match_hit_rate", 0.0) or 0.0),
                    "set1_hit_rate": float(parsed.get("set1_hit_rate", 0.0) or 0.0),
                    "sample_size": float(parsed.get("sample_size", parsed.get("n", 0.0)) or 0.0),
                }
    except Exception:
        kpi = {}

    model_dir = Path(getattr(settings, "ml_model_dir", "/tmp/pingwin_ml_models"))
    v2_meta: dict[str, Any] = {}
    meta_path = model_dir / "tt_ml_v2_meta.json"
    if meta_path.exists():
        try:
            with open(meta_path, encoding="utf-8") as f:
                v2_meta = json.load(f)
        except Exception:
            v2_meta = {}

    return {
        "engine": str(getattr(settings, "ml_engine", "v1")),
        "queue_size": queue_size(),
        "progress": get_progress(),
        "clickhouse_ok": ch_ok,
        "clickhouse_error": ch_error,
        "tables": tables,
        "main_finished": int(main_finished),
        "delta_main_minus_ch_matches": int(main_finished - int(tables.get("matches", 0))),
        "delta_ch_matches_minus_features": int(int(tables.get("matches", 0)) - int(tables.get("match_features", 0))),
        "delta_ch_matches_minus_match_sets": int(tables.get("match_sets_gap_count", max(0, int(tables.get("matches", 0)) - int(tables.get("match_sets_uniq_matches", 0))))),
        "match_sets_gap_pct": round(
            100.0 * max(0, int(tables.get("match_sets_gap_count", 0))) / max(1, int(tables.get("matches_uniq_matches", tables.get("matches", 1)))),
            2,
        ),
        "match_sets_gap_alert": bool(int(tables.get("match_sets_gap_count", 0)) > 0),
        "delta_main_minus_ch_features": int(main_finished - int(tables.get("match_features", 0))),
        "meta": meta,
        "kpi": kpi,
        "v2_config": {
            "ml_v2_use_experience_regimes": bool(getattr(settings, "ml_v2_use_experience_regimes", False)),
            "ml_v2_experience_regime_min_train": int(getattr(settings, "ml_v2_experience_regime_min_train", 500)),
            "betsapi_table_tennis_v2_confidence_filter_min_pct": float(getattr(settings, "betsapi_table_tennis_v2_confidence_filter_min_pct", 0) or 0),
            "betsapi_table_tennis_v2_min_confidence_to_publish": float(getattr(settings, "betsapi_table_tennis_v2_min_confidence_to_publish", 0) or 0),
            "betsapi_table_tennis_v2_allow_hard_confidence_fallback": bool(getattr(settings, "betsapi_table_tennis_v2_allow_hard_confidence_fallback", False)),
            "ml_v2_train_max_league_upset_rate": float(getattr(settings, "ml_v2_train_max_league_upset_rate", 0.45)),
        },
        "v2_meta": v2_meta,
    }


@router.get("/ml/verify-models")
async def admin_ml_verify_models(
    _: User = Depends(require_superadmin),
    version: str = Query(default="", description="Версия моделей: v2 (по умолчанию) или v1"),
):
    """Проверка загруженных моделей: фичи, классы, число деревьев. Убедиться, что обучение прошло корректно."""
    from app.ml.model_trainer import load_models, _model_summary, FEATURE_COLS
    from app.ml_v2.features import FEATURE_COLS_V2, FEATURE_COLS_V2_TRAIN
    from pathlib import Path
    from app.config import settings
    import json

    version = (version or str(getattr(settings, "ml_engine", "v2"))).strip().lower()
    if version not in {"v1", "v2"}:
        version = "v2"

    model_dir = Path(getattr(settings, "ml_model_dir", None) or __import__("os").environ.get("ML_MODEL_DIR", "/tmp/pingwin_ml_models"))
    prefix = model_dir / f"tt_ml_{version}"
    meta_path = Path(str(prefix) + "_meta.json")
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
        except Exception:
            pass

    if version == "v2":
        import joblib

        match_path = model_dir / "tt_ml_v2_match.joblib"
        set1_path = model_dir / "tt_ml_v2_set1.joblib"
        if not (match_path.exists() and set1_path.exists()):
            return {"ok": False, "error": "ML v2 models not found", "version": version, "meta": meta}
        match_model = joblib.load(match_path)
        set1_model = joblib.load(set1_path)
        # LightGBM sklearn wrapper stores training names in feature_name_.
        match_names = list(getattr(match_model, "feature_name_", []) or [])
        set1_names = list(getattr(set1_model, "feature_name_", []) or [])
        report = {
            "ok": True,
            "version": version,
            "model_dir": str(model_dir),
            "expected_features_count": len(FEATURE_COLS_V2_TRAIN),
            "meta_training_features": len(meta.get("features") or []),
            "models": {
                "match": {
                    "loaded": True,
                    "n_features": len(match_names),
                    "best_iteration": int(getattr(match_model, "best_iteration_", 0) or 0),
                    "n_estimators": int(getattr(match_model, "n_estimators_", 0) or 0),
                },
                "set1": {
                    "loaded": True,
                    "n_features": len(set1_names),
                    "best_iteration": int(getattr(set1_model, "best_iteration_", 0) or 0),
                    "n_estimators": int(getattr(set1_model, "n_estimators_", 0) or 0),
                },
            },
        }
        report["warnings"] = []
        if report["models"]["match"]["n_features"] != len(FEATURE_COLS_V2):
            report["warnings"].append(
                f"match: n_features={report['models']['match']['n_features']}, ожидается {len(FEATURE_COLS_V2)}"
            )
        if report["models"]["set1"]["n_features"] != len(FEATURE_COLS_V2):
            report["warnings"].append(
                f"set1: n_features={report['models']['set1']['n_features']}, ожидается {len(FEATURE_COLS_V2)}"
            )
        return report

    try:
        match_model, set1_model, set_model, p_point_model = load_models(version=version)
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e), "meta": meta}

    report = {
        "ok": True,
        "version": version,
        "model_dir": str(model_dir),
        "expected_features_count": len(FEATURE_COLS),
        "meta_training_features": len(meta.get("training_features") or meta.get("features") or []),
        "models": {
            "match": _model_summary("match", match_model),
            "set1": _model_summary("set1", set1_model),
            "set": _model_summary("set", set_model),
            "p_point": _model_summary("p_point", p_point_model),
        },
    }
    # Проверка согласованности
    n_match = report["models"]["match"].get("n_features") or 0
    n_set1 = report["models"]["set1"].get("n_features") or 0
    report["warnings"] = []
    if n_match > 0 and n_match != len(FEATURE_COLS):
        report["warnings"].append(f"match: n_features={n_match}, ожидается {len(FEATURE_COLS)}")
    if n_set1 > 0 and n_set1 != len(FEATURE_COLS):
        report["warnings"].append(f"set1: n_features={n_set1}, ожидается {len(FEATURE_COLS)}")
    for name, s in report["models"].items():
        if s.get("missing_vs_feature_cols"):
            report["warnings"].append(f"{name}: отсутствуют фичи в обучении: {s['missing_vs_feature_cols'][:8]}")
    return report


@router.get("/ml/progress")
async def admin_ml_progress(_: User = Depends(require_superadmin)):
    """Прогресс ML-операций: sync, backfill, retrain."""
    from app.services.ml_progress import get_progress
    return get_progress()


@router.post("/ml/reset-progress")
async def admin_ml_reset_progress(
    _: User = Depends(require_superadmin),
    op: str | None = Query(default=None, description="sync|backfill|odds_backfill|retrain|full_rebuild или пусто=все"),
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


@router.post("/ml/recompute-elo")
async def admin_ml_recompute_elo(_: User = Depends(require_superadmin)):
    """Пересчёт рейтинга игроков (Elo) с первого матча по ml.matches. Источник истины — только ml.matches ORDER BY start_time."""
    from app.ml_v2.sync import recompute_elo_from_matches
    import asyncio

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, recompute_elo_from_matches)
    return {"ok": True, **result}


@router.post("/ml/v2/backfill-match-sets")
async def admin_ml_v2_backfill_match_sets(
    _: User = Depends(require_superadmin),
    limit: int = Query(default=5000, ge=100, le=20000, description="Макс. матчей без сетов за один проход"),
):
    """Дозаполняет ml.match_sets для матчей из ml.matches, у которых нет записей в match_sets.
    Источник: main DB (TableTennisLineEvent.live_sets_score, live_score). Возвращает filled, sets_inserted, remaining."""
    from app.ml_v2.sync import backfill_match_sets_from_main

    result = await backfill_match_sets_from_main(limit=limit)
    return {"ok": True, **result}


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


@router.post("/ml/odds-backfill-bg")
async def admin_ml_odds_backfill_bg(
    _: User = Depends(require_superadmin),
    limit: int = Query(default=5000, ge=100, le=20000, description="Размер батча по матчам"),
    batches: int = Query(default=100, ge=1, le=1000, description="Макс. число батчей за запуск"),
    pause_ms: int = Query(default=600, ge=0, le=5000, description="Пауза между батчами, мс"),
):
    """Фоновая догрузка odds (курсорно, с fallback через BetsAPI). Задача в очередь."""
    from app.services.ml_progress import is_running
    from app.services.ml_queue import enqueue

    if is_running("odds_backfill"):
        return {"ok": False, "error": "Фоновая догрузка odds уже выполняется"}
    if not enqueue("odds_backfill", {"limit": limit, "batches": batches, "pause_ms": pause_ms}):
        return {"ok": False, "error": "Не удалось добавить в очередь"}
    return {"ok": True, "message": "Фоновая догрузка odds добавлена в очередь"}


@router.post("/ml/hyperparameter-search")
async def admin_ml_hyperparameter_search(
    _: User = Depends(require_superadmin),
    n_iter: int = Query(default=25, ge=5, le=100),
    limit: int = Query(default=100_000, ge=5000, le=500_000),
):
    """Поиск гиперпараметров LightGBM (RandomizedSearchCV). Сохраняет лучшие в tt_ml_hyperparams.json. Может занять 10–30 мин."""
    from app.ml.model_trainer import load_training_data, run_hyperparameter_search
    from app.config import settings

    train_start = int(getattr(settings, "ml_train_year_start", 2017))
    train_end = int(getattr(settings, "ml_train_year_end", 2022))
    val_start_cfg = int(getattr(settings, "ml_val_year_start", 2023))
    if train_end >= val_start_cfg:
        train_end = max(train_start, val_start_cfg - 1)
    warmup_end = int(getattr(settings, "ml_warmup_year_end", 2016))
    odds_min = float(getattr(settings, "ml_train_odds_min", 0.0) or 0.0)
    odds_max = float(getattr(settings, "ml_train_odds_max", 999.0) or 999.0)
    df = load_training_data(
        limit=limit,
        train_year_start=train_start,
        train_year_end=train_end,
        warmup_year_end=warmup_end,
        odds_min=odds_min,
        odds_max=odds_max,
    )
    if len(df) < 3000:
        return {"ok": False, "error": f"Мало данных: {len(df)} строк. Нужно минимум 3000."}
    use_gpu = getattr(settings, "ml_use_gpu", True)
    best = run_hyperparameter_search(df, target_col="target_match", n_iter=n_iter, use_gpu=use_gpu)
    return {"ok": True, "best_params": best, "rows_used": len(df)}


@router.post("/ml/retrain")
async def admin_ml_retrain(
    _: User = Depends(require_superadmin),
    min_rows: int = Query(default=500, ge=50, le=500_000),
):
    """Переобучение ML-моделей. Задача идёт в очередь."""
    from app.services.ml_progress import is_running
    from app.services.ml_queue import enqueue

    if is_running("retrain"):
        return {"ok": False, "error": "Переобучение уже выполняется"}
    if not enqueue("retrain", {"min_rows": min_rows}):
        return {
            "ok": False,
            "error": "Не удалось добавить в очередь. Проверьте, что контейнер backend имеет volume с ML_MODEL_DIR (как в docker-compose) и ml_worker запущен.",
        }
    return {"ok": True, "message": "Задача добавлена в очередь. Выполнит ml_worker в течение ~5 сек (обучение 5–15 мин)."}


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
