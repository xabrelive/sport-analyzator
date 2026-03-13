"""Signal model — выданные сигналы по матчам с исходом (сыграл/не сыграл)."""
import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SignalOutcome(str, Enum):
    PENDING = "pending"
    WON = "won"
    LOST = "lost"


class SignalChannel(str, Enum):
    """Куда отправлен сигнал: бесплатный ТГ-канал или платная подписка."""
    FREE = "free"
    PAID = "paid"


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("matches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    market_type: Mapped[str] = mapped_column(String(100), nullable=False)
    selection: Mapped[str] = mapped_column(String(200), nullable=False)
    outcome: Mapped[SignalOutcome] = mapped_column(
        String(20),
        nullable=False,
        default=SignalOutcome.PENDING,
        index=True,
    )
    channel: Mapped[SignalChannel] = mapped_column(
        String(20),
        nullable=False,
        default=SignalChannel.FREE,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )

    match = relationship("Match", back_populates="signals")
