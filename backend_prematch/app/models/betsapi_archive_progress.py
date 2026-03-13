"""Прогресс загрузки архива BetsAPI: по каким дням все страницы уже обработаны."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BetsapiArchiveProgress(Base):
    """День, за который все страницы GET /v3/events/ended обработаны (или в процессе).
    completed_at is set when the day is fully done (empty page); last_processed_page — последняя сохранённая страница (для дозагрузки)."""
    __tablename__ = "betsapi_archive_progress"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="betsapi", index=True)
    day_yyyymmdd: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    last_processed_page: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=True)

    __table_args__ = (UniqueConstraint("provider", "day_yyyymmdd", name="uq_betsapi_archive_provider_day"),)
