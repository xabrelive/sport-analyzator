"""Match result (final score, winner)."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MatchResult(Base):
    __tablename__ = "match_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("matches.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    final_score: Mapped[str] = mapped_column(String(50), nullable=False)
    winner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("players.id", ondelete="SET NULL"),
        nullable=True,
    )
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    match: Mapped["Match"] = relationship("Match", back_populates="result")
    winner: Mapped["Player | None"] = relationship("Player", foreign_keys=[winner_id])

    @property
    def winner_name(self) -> str | None:
        return self.winner.name if self.winner else None
