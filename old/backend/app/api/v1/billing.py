"""Billing API: checkout (create payment), list invoices, webhook."""
import logging
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_async_session
from app.models import Invoice, User, PaymentMethod, Product
from app.api.v1.auth import get_current_user
from app.services.billing_service import (
    create_yookassa_payment,
    grant_subscriptions_from_invoice_payload,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/payment-methods")
async def list_payment_methods(session: AsyncSession = Depends(get_async_session)):
    """Список включённых способов оплаты для выбора на странице тарифов (без авторизации)."""
    r = await session.execute(
        select(PaymentMethod)
        .where(PaymentMethod.enabled == True)
        .order_by(PaymentMethod.sort_order.asc(), PaymentMethod.created_at.asc())
    )
    rows = r.scalars().all()
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "type": p.type,
            "custom_message": p.custom_message,
        }
        for p in rows
    ]


@router.get("/products")
async def list_products(session: AsyncSession = Depends(get_async_session)):
    """Список включённых услуг для страницы тарифов (без авторизации)."""
    r = await session.execute(
        select(Product)
        .where(Product.enabled == True)
        .order_by(Product.sort_order.asc(), Product.created_at.asc())
    )
    rows = r.scalars().all()
    return [
        {"id": str(p.id), "key": p.key, "name": p.name}
        for p in rows
    ]


class CheckoutItem(BaseModel):
    access_type: str = Field(..., pattern="^(tg_analytics|signals)$")
    scope: str = Field(..., pattern="^(one_sport|all)$")
    sport_key: str | None = None
    days: int = Field(..., ge=1, le=365)


class CheckoutBody(BaseModel):
    items: list[CheckoutItem]


class CheckoutOut(BaseModel):
    invoice_id: str
    payment_id: str | None
    confirmation_url: str | None
    error: str | None = None


@router.post("/checkout", response_model=CheckoutOut)
async def create_checkout(
    body: CheckoutBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Создать платёж: создаётся инвойс и платёж в YooKassa.
    Возвращается confirmation_url — на него нужно перенаправить пользователя.
    Подписки выдаются только после успешной оплаты (webhook).
    """
    if not body.items:
        raise HTTPException(status_code=400, detail="Укажите хотя бы один товар")
    for it in body.items:
        if it.scope == "one_sport" and not it.sport_key:
            raise HTTPException(status_code=400, detail="Для одного вида спорта укажите sport_key")

    # Сумма из тарифа (можно вынести в конфиг/таблицу)
    total = Decimal("0")
    payload_items = []
    for it in body.items:
        if it.access_type == "tg_analytics":
            if it.days == 1:
                total += Decimal("299")
            elif it.days == 7:
                total += Decimal("1990")
            else:
                total += Decimal("5990")
        else:
            if it.days == 1:
                total += Decimal("150")
            elif it.days == 7:
                total += Decimal("995")
            else:
                total += Decimal("2995")
        payload_items.append({
            "access_type": it.access_type,
            "scope": it.scope,
            "sport_key": it.sport_key,
            "days": it.days,
        })

    return_url = (settings.billing_return_url or "").strip()
    if not return_url and (settings.frontend_public_url or settings.frontend_url):
        base = (settings.frontend_public_url or settings.frontend_url or "").rstrip("/")
        return_url = f"{base}{settings.billing_success_path}"
    if not return_url:
        return_url = "https://example.com/pricing?paid=1"

    invoice = Invoice(
        user_id=user.id,
        amount=total,
        currency="RUB",
        status="pending",
        provider="yookassa",
        description=f"Подписка PingWin — {len(body.items)} шт.",
        payload={"items": payload_items},
    )
    session.add(invoice)
    await session.commit()
    await session.refresh(invoice)

    payment_id, confirmation_url = await create_yookassa_payment(
        amount_rub=total,
        description=invoice.description or "Подписка",
        return_url=return_url,
        metadata={"invoice_id": str(invoice.id)},
    )
    if payment_id:
        invoice.provider_payment_id = payment_id
        await session.commit()
    return CheckoutOut(
        invoice_id=str(invoice.id),
        payment_id=payment_id,
        confirmation_url=confirmation_url,
        error=None if confirmation_url else "Не удалось создать платёж",
    )


@router.get("/invoices")
async def list_my_invoices(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Список инвойсов текущего пользователя."""
    r = await session.execute(
        select(Invoice)
        .where(Invoice.user_id == user.id)
        .order_by(Invoice.created_at.desc())
        .limit(50)
    )
    rows = r.scalars().all()
    return [
        {
            "id": str(inv.id),
            "amount": float(inv.amount),
            "currency": inv.currency,
            "status": inv.status,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
            "paid_at": inv.paid_at.isoformat() if inv.paid_at else None,
        }
        for inv in rows
    ]


@router.post("/webhook/yookassa")
async def webhook_yookassa(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Webhook от YooKassa при смене статуса платежа.
    При payment.succeeded ищем инвойс по provider_payment_id, помечаем paid и выдаём подписки.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    event = body.get("event") or body.get("type")
    obj = body.get("object") or body
    if event != "payment.succeeded" and obj.get("status") != "succeeded":
        return {"ok": True}
    payment_id = obj.get("id")
    if not payment_id:
        return {"ok": True}
    r = await session.execute(
        select(Invoice).where(
            Invoice.provider_payment_id == payment_id,
            Invoice.status == "pending",
        )
    )
    invoice = r.scalar_one_or_none()
    if not invoice:
        return {"ok": True}
    invoice.status = "paid"
    invoice.paid_at = datetime.now(timezone.utc)
    await session.flush()
    items = (invoice.payload or {}).get("items") or []
    if isinstance(items, list):
        n = await grant_subscriptions_from_invoice_payload(
            session, invoice.user_id, items
        )
        logger.info("Invoice %s paid, granted %d subscriptions", invoice.id, n)
    await session.commit()
    return {"ok": True}
