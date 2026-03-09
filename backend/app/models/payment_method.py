"""Способы оплаты: ЮKassa, кастомный (реквизиты и т.п.). Управление в админке."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # yookassa = оплата картой через ЮKassa; custom = показать сообщение (реквизиты и т.д.)
    type: Mapped[str] = mapped_column(String(32), nullable=False, default="yookassa")
    enabled: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    # Для type=custom: текст в модалке (реквизиты, инструкция)
    custom_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)
