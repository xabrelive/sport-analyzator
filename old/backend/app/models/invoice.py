"""Invoice for billing: one invoice per payment intent, paid via YooKassa (or other)."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RUB")
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )  # pending, paid, failed, cancelled
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="yookassa")
    provider_payment_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payload: Mapped[dict | None] = mapped_column(
        JSONB(),
        nullable=True,
    )  # items: [{ access_type, scope, sport_key, days }] for subscription grants
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        nullable=False,
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    user = relationship("User", back_populates="invoices")
