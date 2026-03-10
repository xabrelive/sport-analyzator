"""Правила обработки лайв-матчей по лигам настольного тенниса."""
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TableTennisLeagueRule(Base):
    __tablename__ = "table_tennis_league_rules"

    league_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    league_name: Mapped[str] = mapped_column(String(255), nullable=False)
    max_sets_wins: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    expected_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    stale_after_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=25)

