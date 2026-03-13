"""League schemas."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator


class LeagueBase(BaseModel):
    name: str
    country: str | None = None
    provider_league_id: str | None = None
    provider: str | None = None


class LeagueCreate(LeagueBase):
    pass


class LeagueInDB(LeagueBase):
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
            d = {k: getattr(v, k) for k in ("id", "name", "country", "provider_league_id", "provider") if hasattr(v, k)}
            d["created_at"] = None
            return d
        return v


class LeagueList(LeagueInDB):
    pass
