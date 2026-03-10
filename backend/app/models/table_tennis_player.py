"""Игроки настольного тенниса (BetsAPI id + имя).

Один и тот же игрок может быть в матчах на первой позиции (home) или на второй (away),
поэтому храним по id игрока, а не по позиции в матче.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TableTennisPlayer(Base):
    """Игрок. id — внешний id (BetsAPI team/player id)."""
    __tablename__ = "table_tennis_players"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        onupdate=_utc_now,
        nullable=False,
    )
