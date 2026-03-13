"""Players API."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_async_session
from app.models import Match, MatchStatus, Player
from app.schemas.match import MatchList, MatchListWithResult
from app.schemas.player import PlayerList, PlayerStats
from app.services.player_stats_service import compute_player_stats

router = APIRouter()


@router.get("", response_model=list[PlayerList])
async def list_players(
    search: str | None = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_async_session),
):
    q = select(Player).order_by(Player.name).limit(limit).offset(offset)
    if search:
        q = q.where(Player.name.ilike(f"%{search}%"))
    result = await session.execute(q)
    return result.scalars().all()


@router.get("/{player_id}", response_model=PlayerList)
async def get_player(
    player_id: UUID,
    session: AsyncSession = Depends(get_async_session),
):
    result = await session.execute(select(Player).where(Player.id == player_id))
    player = result.scalar_one_or_none()
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")
    return player


@router.get("/{player_id}/stats", response_model=PlayerStats)
async def get_player_stats(player_id: UUID, session: AsyncSession = Depends(get_async_session)):
    stats = await compute_player_stats(session, player_id)
    if stats is None:
        raise HTTPException(status_code=404, detail="Player not found")
    return stats


@router.get("/{player_id}/matches", response_model=list[MatchList])
async def get_player_matches(
    player_id: UUID,
    status: MatchStatus | None = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_async_session),
):
    from app.models.match_result import MatchResult

    r = await session.execute(select(Player).where(Player.id == player_id))
    if r.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Player not found")
    q = (
        select(Match)
        .where((Match.home_player_id == player_id) | (Match.away_player_id == player_id))
        .options(
            selectinload(Match.league),
            selectinload(Match.home_player),
            selectinload(Match.away_player),
            selectinload(Match.scores),
            selectinload(Match.result).selectinload(MatchResult.winner),
        )
        .limit(limit)
        .offset(offset)
    )
    if status is not None:
        q = q.where(Match.status == status.value)
    q = q.order_by(Match.start_time.desc() if status == MatchStatus.FINISHED or status is None else Match.start_time.asc())
    result = await session.execute(q)
    return result.scalars().unique().all()
