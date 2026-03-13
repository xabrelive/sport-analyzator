"""Match schemas."""
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.league import LeagueList
from app.schemas.player import PlayerList


def _is_set_completed(
    home_score: int,
    away_score: int,
    points_per_set: int = 11,
    win_by: int = 2,
) -> bool:
    """Сет завершён, если один из игроков набрал не менее points_per_set и вёл минимум на win_by."""
    max_pts = max(home_score, away_score)
    diff = abs(home_score - away_score)
    return max_pts >= points_per_set and diff >= win_by


def _count_sets_won(
    scores: list,
    points_per_set: int,
    win_by: int,
) -> tuple[int, int]:
    """Возвращает (home_sets_won, away_sets_won) только по завершённым сетам."""
    sorted_scores = sorted(scores, key=lambda s: s.set_number)
    home_won = 0
    away_won = 0
    for s in sorted_scores:
        if _is_set_completed(s.home_score, s.away_score, points_per_set, win_by):
            if s.home_score > s.away_score:
                home_won += 1
            else:
                away_won += 1
    return home_won, away_won


class MatchScoreSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    set_number: int
    home_score: int
    away_score: int
    timestamp: datetime | None = None
    is_completed: bool = False


class OddsSnapshotSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    bookmaker: str
    market: str
    selection: str
    odds: Decimal
    implied_probability: Decimal | None = None
    line_value: Decimal | None = None
    phase: str | None = None
    timestamp: datetime | None = None
    snapshot_time: datetime | None = None
    score_at_snapshot: str | None = None


class MatchResultSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    final_score: str
    winner_id: UUID | None = None
    winner_name: str | None = None
    finished_at: datetime | None = None


class MatchBase(BaseModel):
    provider_match_id: str
    provider: str
    league_id: UUID | None = None
    home_player_id: UUID
    away_player_id: UUID
    start_time: datetime
    status: str = "scheduled"
    bet365_id: str | None = None
    confirmed_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    timeline: list | dict | None = None
    extra: dict | None = None
    current_timer: str | None = None
    odds_stats: dict | None = None
    sets_to_win: int = 2
    points_per_set: int = 11
    win_by: int = 2
    is_doubles: bool = False


class MatchCreate(MatchBase):
    pass


class MatchInDB(MatchBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MatchList(MatchInDB):
    league: LeagueList | None = None
    home_player: PlayerList | None = None
    away_player: PlayerList | None = None
    scores: list[MatchScoreSchema] = []
    status: str
    result: MatchResultSchema | None = None
    home_sets_won: int = 0
    away_sets_won: int = 0

    @model_validator(mode="after")
    def fill_sets_from_scores(self) -> "MatchList":
        """Заполняем home_sets_won, away_sets_won и is_completed у каждого сета из данных матча."""
        if not self.scores:
            return self
        pts = self.points_per_set
        wb = self.win_by
        home_won, away_won = _count_sets_won(self.scores, pts, wb)
        new_scores = [
            MatchScoreSchema(
                set_number=s.set_number,
                home_score=s.home_score,
                away_score=s.away_score,
                timestamp=getattr(s, "timestamp", None),
                is_completed=_is_set_completed(s.home_score, s.away_score, pts, wb),
            )
            for s in sorted(self.scores, key=lambda x: x.set_number)
        ]
        return self.model_copy(
            update={
                "home_sets_won": home_won,
                "away_sets_won": away_won,
                "scores": new_scores,
            }
        )


class MatchListWithOdds(MatchList):
    odds_snapshots: list[OddsSnapshotSchema] = []


class MatchListWithResult(MatchList):
    result: MatchResultSchema | None = None


class FinishedMatchesResponse(BaseModel):
    """Список завершённых матчей с пагинацией и общим количеством."""
    total: int
    items: list[MatchListWithResult]


class MatchDetail(MatchList):
    odds_snapshots: list[OddsSnapshotSchema] = []
    result: MatchResultSchema | None = None
