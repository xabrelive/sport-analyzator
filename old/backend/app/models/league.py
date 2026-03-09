"""League model."""
import uuid
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class League(Base):
    __tablename__ = "leagues"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider_league_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)

    matches: Mapped[list["Match"]] = relationship(
        "Match", back_populates="league", lazy="selectin"
    )
