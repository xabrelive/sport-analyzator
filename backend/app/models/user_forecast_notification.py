"""Per-user delivery log for forecast notifications."""
from datetime import datetime, timezone
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UserForecastNotification(Base):
    __tablename__ = "user_forecast_notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "event_id", "channel", name="uq_user_forecast_notification_user_event_channel"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id: Mapped[str] = mapped_column(String(64), ForeignKey("table_tennis_line_events.id", ondelete="CASCADE"), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # telegram|email
    forecast_v2_id: Mapped[int | None] = mapped_column(ForeignKey("table_tennis_forecasts_v2.id", ondelete="SET NULL"), nullable=True, index=True)
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, index=True)
    result_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    result_status: Mapped[str | None] = mapped_column(String(32), nullable=True)  # hit|miss|cancelled|no_result
