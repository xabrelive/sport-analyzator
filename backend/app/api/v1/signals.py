"""Signals API — список сигналов и статистика (дано за сутки, угадано/не угадано)."""
from datetime import date, datetime, time, timezone, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.models import Signal, SignalOutcome, SignalChannel
from app.schemas.signal import (
    SignalList,
    SignalStats,
    SignalStatsDay,
    SignalLandingStats,
    SignalPeriodStats,
    SignalChannelStats,
)

router = APIRouter()


class SignalOutcomeUpdate(BaseModel):
    outcome: str  # "won" | "lost" | "pending"


@router.get("", response_model=list[SignalList])
async def list_signals(
    match_id: UUID | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_async_session),
):
    q = select(Signal).order_by(Signal.created_at.desc()).limit(limit).offset(offset)
    if match_id is not None:
        q = q.where(Signal.match_id == match_id)
    if date_from is not None:
        q = q.where(Signal.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to is not None:
        end = datetime.combine(date_to, time(23, 59, 59, 999999), tzinfo=timezone.utc)
        q = q.where(Signal.created_at <= end)
    result = await session.execute(q)
    return result.scalars().all()


@router.get("/stats", response_model=SignalStats)
async def get_signals_stats(
    days: int = Query(7, ge=1, le=90),
    session: AsyncSession = Depends(get_async_session),
):
    """Статистика: всего дано, выиграло, проиграло; за последние N дней — разбивка по дням."""
    q_totals = select(
        func.count(Signal.id).label("total"),
        func.count(Signal.id).filter(Signal.outcome == SignalOutcome.WON).label("won"),
        func.count(Signal.id).filter(Signal.outcome == SignalOutcome.LOST).label("lost"),
        func.count(Signal.id).filter(Signal.outcome == SignalOutcome.PENDING).label("pending"),
    )
    row = (await session.execute(q_totals)).one()
    total = row.total or 0
    won = row.won or 0
    lost = row.lost or 0
    pending = row.pending or 0

    since = datetime.now(timezone.utc) - timedelta(days=days)
    q_day = (
        select(
            func.date(Signal.created_at).label("d"),
            func.count(Signal.id).label("total"),
            func.count(Signal.id).filter(Signal.outcome == SignalOutcome.WON).label("won"),
            func.count(Signal.id).filter(Signal.outcome == SignalOutcome.LOST).label("lost"),
            func.count(Signal.id).filter(Signal.outcome == SignalOutcome.PENDING).label("pending"),
        )
        .where(Signal.created_at >= since)
        .group_by(func.date(Signal.created_at))
        .order_by(func.date(Signal.created_at).desc())
    )
    rows_day = (await session.execute(q_day)).all()
    by_day = [
        SignalStatsDay(
            date=r.d,
            total=r.total or 0,
            won=r.won or 0,
            lost=r.lost or 0,
            pending=r.pending or 0,
        )
        for r in rows_day
    ]

    return SignalStats(total=total, won=won, lost=lost, pending=pending, by_day=by_day)


@router.get("/stats/landing", response_model=SignalLandingStats)
async def get_signals_landing_stats(
    session: AsyncSession = Depends(get_async_session),
):
    """Публичная статистика для главной: бесплатный ТГ-канал и платная подписка — всего, угадано, не угадано за день/неделю/месяц."""
    now = datetime.now(timezone.utc)
    day_start = now - timedelta(days=1)
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=30)

    async def period_stats(since: datetime, channel: SignalChannel) -> SignalPeriodStats:
        q = select(
            func.count(Signal.id).label("total"),
            func.count(Signal.id).filter(Signal.outcome == SignalOutcome.WON).label("won"),
            func.count(Signal.id).filter(Signal.outcome == SignalOutcome.LOST).label("lost"),
        ).where(Signal.created_at >= since, Signal.channel == channel)
        row = (await session.execute(q)).one()
        return SignalPeriodStats(
            total=row.total or 0,
            won=row.won or 0,
            lost=row.lost or 0,
        )

    async def channel_stats(channel: SignalChannel) -> SignalChannelStats:
        return SignalChannelStats(
            day=await period_stats(day_start, channel),
            week=await period_stats(week_start, channel),
            month=await period_stats(month_start, channel),
        )

    return SignalLandingStats(
        free_channel=await channel_stats(SignalChannel.FREE),
        paid_subscription=await channel_stats(SignalChannel.PAID),
    )


@router.patch("/{signal_id}", response_model=SignalList)
async def update_signal_outcome(
    signal_id: UUID,
    body: SignalOutcomeUpdate,
    session: AsyncSession = Depends(get_async_session),
):
    """Установить исход сигнала (сыграл / не сыграл)."""
    q = select(Signal).where(Signal.id == signal_id)
    r = await session.execute(q)
    sig = r.scalar_one_or_none()
    if not sig:
        raise HTTPException(status_code=404, detail="Signal not found")
    sig.outcome = SignalOutcome(body.outcome)
    await session.commit()
    await session.refresh(sig)
    return sig
