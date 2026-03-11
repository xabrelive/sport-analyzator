"""Billing API for products, payment methods and user invoices."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.db.session import get_async_session
from app.models.billing_product import BillingProduct
from app.models.invoice import Invoice
from app.models.payment_method import PaymentMethod
from app.models.user import User
from app.models.user_subscription import UserSubscription
from app.services.vip_channel_access import (
    create_vip_invite_link,
    get_vip_member_status,
    is_vip_member_status,
    vip_public_url,
)

router = APIRouter()


def _fmt_dt(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


@router.get("/products")
async def billing_products(session: AsyncSession = Depends(get_async_session)):
    rows = (
        await session.execute(
            select(BillingProduct)
            .where(BillingProduct.enabled.is_(True))
            .order_by(BillingProduct.sort_order.asc(), BillingProduct.created_at.asc())
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
        }
        for p in rows
    ]


@router.get("/payment-methods")
async def billing_payment_methods(session: AsyncSession = Depends(get_async_session)):
    rows = (
        await session.execute(
            select(PaymentMethod)
            .where(PaymentMethod.enabled.is_(True))
            .order_by(PaymentMethod.sort_order.asc(), PaymentMethod.created_at.asc())
        )
    ).scalars().all()
    return [
        {
            "id": str(m.id),
            "name": m.name,
            "method_type": m.method_type,
            "instructions": m.instructions,
        }
        for m in rows
    ]


class CheckoutItem(BaseModel):
    product_code: str
    quantity: int = Field(default=1, ge=1, le=5)


class CheckoutBody(BaseModel):
    items: list[CheckoutItem]
    payment_method_id: str | None = None
    comment: str | None = None


@router.post("/checkout")
async def billing_checkout(
    body: CheckoutBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    if not body.items:
        raise HTTPException(status_code=400, detail="Добавьте хотя бы один тариф")
    codes = list({it.product_code.strip() for it in body.items if it.product_code.strip()})
    if not codes:
        raise HTTPException(status_code=400, detail="Некорректные товары")
    products = (
        await session.execute(
            select(BillingProduct).where(BillingProduct.code.in_(codes), BillingProduct.enabled.is_(True))
        )
    ).scalars().all()
    by_code = {p.code: p for p in products}
    total = Decimal("0.00")
    payload_items: list[dict] = []
    for item in body.items:
        product = by_code.get(item.product_code)
        if not product:
            raise HTTPException(status_code=400, detail=f"Товар не найден: {item.product_code}")
        qty = int(item.quantity)
        total += Decimal(str(product.price_rub)) * qty
        payload_items.append(
            {
                "product_code": product.code,
                "service_key": product.service_key,
                "days": int(product.duration_days) * qty,
                "quantity": qty,
                "price_rub": float(product.price_rub),
                "price_usd": float(product.price_usd),
            }
        )

    payment_method_uuid: UUID | None = None
    if body.payment_method_id:
        try:
            payment_method_uuid = UUID(body.payment_method_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Некорректный payment_method_id") from exc
        method = (
            await session.execute(select(PaymentMethod).where(PaymentMethod.id == payment_method_uuid))
        ).scalar_one_or_none()
        if method is None:
            raise HTTPException(status_code=404, detail="Способ оплаты не найден")

    invoice = Invoice(
        user_id=user.id,
        status="pending",
        amount_rub=total,
        payment_method_id=payment_method_uuid,
        payload={"items": payload_items},
        comment=(body.comment or "").strip() or None,
    )
    session.add(invoice)
    await session.commit()
    await session.refresh(invoice)
    return {
        "invoice_id": str(invoice.id),
        "status": invoice.status,
        "amount_rub": float(invoice.amount_rub),
        "created_at": _fmt_dt(invoice.created_at),
        "detail": "Счёт создан. Ожидает подтверждения оплаты администратором.",
    }


@router.get("/invoices/my")
async def billing_my_invoices(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    rows = (
        await session.execute(
            select(Invoice)
            .where(Invoice.user_id == user.id)
            .order_by(Invoice.created_at.desc())
            .limit(100)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": str(inv.id),
                "status": inv.status,
                "amount_rub": float(inv.amount_rub),
                "payment_method_id": str(inv.payment_method_id) if inv.payment_method_id else None,
                "comment": inv.comment,
                "created_at": _fmt_dt(inv.created_at),
                "paid_at": _fmt_dt(inv.paid_at),
            }
            for inv in rows
        ]
    }


@router.get("/subscriptions/my")
async def billing_my_subscriptions(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    today = datetime.now(timezone.utc).date()
    rows = (
        await session.execute(
            select(UserSubscription)
            .where(UserSubscription.user_id == user.id)
            .order_by(UserSubscription.valid_until.desc(), UserSubscription.created_at.desc())
        )
    ).scalars().all()

    latest_by_service: dict[str, UserSubscription] = {}
    for row in rows:
        if row.service_key not in latest_by_service:
            latest_by_service[row.service_key] = row

    def _service_payload(service_key: str) -> dict:
        s = latest_by_service.get(service_key)
        if s is None:
            return {
                "service_key": service_key,
                "has_subscription": False,
                "is_active": False,
                "valid_until": None,
                "days_left": 0,
            }
        days_left = (s.valid_until - today).days
        return {
            "service_key": service_key,
            "has_subscription": True,
            "is_active": days_left >= 0,
            "valid_until": s.valid_until.isoformat(),
            "days_left": max(0, days_left),
            "source": s.source,
        }

    return {
        "items": [
            {
                "id": str(s.id),
                "service_key": s.service_key,
                "duration_days": s.duration_days,
                "valid_until": s.valid_until.isoformat(),
                "source": s.source,
                "comment": s.comment,
                "created_at": _fmt_dt(s.created_at),
            }
            for s in rows
        ],
        "analytics": _service_payload("analytics"),
        "vip_channel": _service_payload("vip_channel"),
    }


@router.get("/vip/access")
async def billing_vip_access(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    today = datetime.now(timezone.utc).date()
    active = (
        await session.execute(
            select(UserSubscription)
            .where(
                UserSubscription.user_id == user.id,
                UserSubscription.service_key == "vip_channel",
                UserSubscription.valid_until >= today,
            )
            .order_by(UserSubscription.valid_until.desc(), UserSubscription.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if active is None:
        return {
            "has_active_subscription": False,
            "telegram_linked": bool(user.telegram_id),
            "is_member": False,
            "can_create_invite": False,
            "channel_url": vip_public_url(),
            "message": "Нет активной подписки VIP.",
        }

    member_status = await get_vip_member_status(int(user.telegram_id)) if user.telegram_id else None
    is_member = is_vip_member_status(member_status)
    can_create_invite = bool(user.telegram_id) and (not is_member)
    message = (
        "Вы уже состоите в VIP-канале."
        if is_member
        else ("Привяжите Telegram в настройках, чтобы получить доступ к VIP-каналу." if not user.telegram_id else "Можно получить одноразовую ссылку для входа.")
    )
    return {
        "has_active_subscription": True,
        "telegram_linked": bool(user.telegram_id),
        "is_member": is_member,
        "can_create_invite": can_create_invite,
        "member_status": member_status,
        "valid_until": active.valid_until.isoformat(),
        "channel_url": vip_public_url(),
        "message": message,
    }


@router.post("/vip/create-invite")
async def billing_vip_create_invite(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    today = datetime.now(timezone.utc).date()
    active = (
        await session.execute(
            select(UserSubscription)
            .where(
                UserSubscription.user_id == user.id,
                UserSubscription.service_key == "vip_channel",
                UserSubscription.valid_until >= today,
            )
            .order_by(UserSubscription.valid_until.desc(), UserSubscription.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if active is None:
        raise HTTPException(status_code=400, detail="Нет активной подписки VIP")
    if user.telegram_id is None:
        raise HTTPException(status_code=400, detail="Привяжите Telegram в настройках")
    member_status = await get_vip_member_status(int(user.telegram_id))
    if is_vip_member_status(member_status):
        return {
            "already_in_channel": True,
            "channel_url": vip_public_url(),
            "message": "Вы уже состоите в VIP-канале.",
        }
    invite = await create_vip_invite_link(user, active.valid_until)
    if not invite:
        raise HTTPException(status_code=502, detail="Не удалось создать ссылку приглашения")
    return {
        "already_in_channel": False,
        "invite_link": invite,
        "channel_url": vip_public_url(),
        "warning": "Ссылка одноразовая: после перехода она станет недействительной.",
        "valid_until": active.valid_until.isoformat(),
    }
