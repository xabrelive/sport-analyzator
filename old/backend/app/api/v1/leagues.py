"""Leagues API."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.db.session import get_async_session
from app.models import League
from app.schemas.league import LeagueList

router = APIRouter()


@router.get("", response_model=list[LeagueList])
async def list_leagues(
    country: str | None = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    session=Depends(get_async_session),
):
    from sqlalchemy.ext.asyncio import AsyncSession

    session: AsyncSession = session
    q = select(League).order_by(League.name).limit(limit).offset(offset)
    if country:
        q = q.where(League.country == country)
    result = await session.execute(q)
    return result.scalars().all()


@router.get("/{league_id}", response_model=LeagueList)
async def get_league(
    league_id: UUID,
    session=Depends(get_async_session),
):
    from fastapi import HTTPException
    from sqlalchemy.ext.asyncio import AsyncSession

    session: AsyncSession = session
    result = await session.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if league is None:
        raise HTTPException(status_code=404, detail="League not found")
    return league
