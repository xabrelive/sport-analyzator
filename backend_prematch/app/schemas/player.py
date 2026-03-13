"""Player schemas."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator


class PlayerBase(BaseModel):
    name: str
    provider_player_id: str | None = None
    provider: str | None = None
    image_id: str | None = None
    country: str | None = None


class PlayerCreate(PlayerBase):
    pass


class PlayerInDB(PlayerBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def ensure_created_at(cls, v):
        if isinstance(v, dict):
            v.setdefault("created_at", None)
            return v
        if hasattr(v, "__dict__") and not hasattr(v, "created_at"):
            d = {k: getattr(v, k) for k in ("id", "name", "provider_player_id", "provider") if hasattr(v, k)}
            d["created_at"] = None
            return d
        return v


class PlayerList(PlayerInDB):
    pass


class PlayerStats(BaseModel):
    total_matches: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float | None = None
    wins_first_set: int = 0
    matches_with_first_set: int = 0
    win_first_set_pct: float | None = None
    wins_second_set: int = 0
    matches_with_second_set: int = 0
    win_second_set_pct: float | None = None
    total_sets_played: int = 0
    avg_sets_per_match: float | None = None
    set_win_pct_by_position: list[dict] = []
    set_patterns: list[dict] = []
