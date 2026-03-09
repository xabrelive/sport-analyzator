"""Player model (table tennis — single player per side)."""
import uuid
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Player(Base):
    __tablename__ = "players"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    provider_player_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    image_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)

    home_matches: Mapped[list["Match"]] = relationship(
        "Match",
        foreign_keys="Match.home_player_id",
        back_populates="home_player",
        lazy="selectin",
    )
    away_matches: Mapped[list["Match"]] = relationship(
        "Match",
        foreign_keys="Match.away_player_id",
        back_populates="away_player",
        lazy="selectin",
    )
