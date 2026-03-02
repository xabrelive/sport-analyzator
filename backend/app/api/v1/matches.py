"""Matches API."""
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_async_session
from app.models import Match, MatchStatus, BetsapiArchiveProgress
from app.models.match_result import MatchResult
from app.models.match_recommendation import MatchRecommendation
from app.models.odds_snapshot import OddsSnapshot
from app.schemas.match import MatchDetail, MatchList, MatchListWithOdds, MatchListWithResult, FinishedMatchesResponse
from app.services.player_stats_service import compute_player_stats
from app.services.analytics_service import first_recommendation_text
from app.worker.tasks.collect_betsapi import load_betsapi_history_task

router = APIRouter()
logger = logging.getLogger(__name__)

LIVE_RECENTLY_FINISHED_MINUTES = 5
# В «линии» показываем только матчи, время начала которых ещё не прошло (или прошло не более 15 мин — запас на переход в лайв)
UPCOMING_START_CUTOFF_MINUTES = 15


class LoadHistoryRequest(BaseModel):
    """Параметры ручной загрузки архива завершённых матчей BetsAPI."""
    day_from: str = Field(default="20160901", description="Начальная дата YYYYMMDD (min 20160901)")
    day_to: str | None = Field(default=None, description="Конечная дата YYYYMMDD, по умолчанию сегодня")
    delay_seconds: float = Field(default=7.0, ge=1, le=60, description="Пауза между запросами к API (сек)")


class LoadHistoryResponse(BaseModel):
    task_id: str
    message: str


class DayProgress(BaseModel):
    day: str
    completed: bool
    last_processed_page: int | None = None


class LoadHistoryStatusResponse(BaseModel):
    day_from: str
    day_to: str
    completed: list[str]
    not_completed: list[str]
    progress: list[DayProgress] = Field(default_factory=list, description="По дням: страница и признак завершения")


def _days_in_range(day_from: str, day_to: str) -> list[str]:
    start = datetime.strptime(day_from, "%Y%m%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(day_to, "%Y%m%d").replace(tzinfo=timezone.utc)
    out: list[str] = []
    d = start
    while d <= end:
        out.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    return out


@router.get("", response_model=list[MatchList])
async def list_matches(
    status: MatchStatus | None = Query(None),
    league_id: UUID | None = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_async_session),
):
    q = (
        select(Match)
        .options(
            selectinload(Match.league),
            selectinload(Match.home_player),
            selectinload(Match.away_player),
            selectinload(Match.scores),
            selectinload(Match.result).selectinload(MatchResult.winner),
        )
        .order_by(Match.start_time.desc())
        .limit(limit)
        .offset(offset)
    )
    if status is not None:
        q = q.where(Match.status == status.value)
    if league_id is not None:
        q = q.where(Match.league_id == league_id)
    result = await session.execute(q)
    return result.scalars().all()


@router.get("/recommendations")
async def get_matches_recommendations(
    match_ids: str = Query(..., description="UUID матчей через запятую"),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Рекомендация по матчу для отображения в таблице линия/лайв.
    Если рекомендация уже сохранена (MatchRecommendation) — возвращаем её (как в статистике).
    Иначе считаем first_recommendation_text и при наличии — сохраняем и возвращаем.
    Возвращает: { "match_id_uuid": "П1 победа в матче (72%)" или null }.
    """
    out: dict[str, str | None] = {}
    raw = [x.strip() for x in match_ids.split(",") if x.strip()]
    ids: list[UUID] = []
    for s in raw:
        try:
            ids.append(UUID(s))
        except ValueError:
            continue
    ids = list(dict.fromkeys(ids))[:150]
    if not ids:
        return out
    # Сначала загружаем сохранённые рекомендации — в таблице показываем то же, что в статистике
    stored_q = select(MatchRecommendation.match_id, MatchRecommendation.recommendation_text).where(
        MatchRecommendation.match_id.in_(ids)
    )
    stored_r = await session.execute(stored_q)
    stored = {str(row[0]): row[1] for row in stored_r.all()}
    need_compute = [mid for mid in ids if str(mid) not in stored or stored.get(str(mid)) is None]
    for mid in ids:
        if str(mid) in stored and stored[str(mid)]:
            out[str(mid)] = stored[str(mid)]
            continue
        out[str(mid)] = None
    if not need_compute:
        return out
    q = select(Match).where(Match.id.in_(need_compute))
    result = await session.execute(q)
    matches = {m.id: m for m in result.scalars().all()}
    for mid in need_compute:
        match = matches.get(mid)
        if not match or not match.home_player_id or not match.away_player_id:
            continue
        stats_home = await compute_player_stats(session, match.home_player_id)
        stats_away = await compute_player_stats(session, match.away_player_id)
        rec = first_recommendation_text(stats_home, stats_away)
        out[str(mid)] = rec
        if rec:
            existing = await session.execute(select(MatchRecommendation).where(MatchRecommendation.match_id == mid))
            if existing.scalar_one_or_none() is None:
                odds_val: float | None = None
                rec_lower = rec.lower()
                if "п1" in rec_lower:
                    side = "home"
                elif "п2" in rec_lower:
                    side = "away"
                else:
                    side = None
                if side is not None:
                    odds_q = (
                        select(OddsSnapshot)
                        .where(
                            OddsSnapshot.match_id == mid,
                            OddsSnapshot.market.in_(["winner", "92_1", "win"]),
                        )
                        .order_by(
                            OddsSnapshot.snapshot_time.asc().nullslast(),
                            OddsSnapshot.timestamp.asc().nullslast(),
                        )
                        .limit(50)
                    )
                    odds_result = await session.execute(odds_q)
                    snaps = odds_result.scalars().all()
                    for s in snaps:
                        sel = (s.selection or "").lower()
                        if odds_val is None and side == "home" and sel in ("home", "1"):
                            odds_val = float(s.odds)
                            break
                        if odds_val is None and side == "away" and sel in ("away", "2"):
                            odds_val = float(s.odds)
                            break
                session.add(MatchRecommendation(match_id=mid, recommendation_text=rec, odds_at_recommendation=odds_val))
                logger.info(
                    "recommendation_saved match_id=%s recommendation_text=%s odds=%s",
                    str(mid),
                    rec[:200] if len(rec) > 200 else rec,
                    odds_val,
                )
    try:
        await session.commit()
    except Exception as e:
        logger.warning("Failed to persist match recommendations: %s", e)
    return out


@router.post("/load-history", response_model=LoadHistoryResponse)
async def load_history(body: LoadHistoryRequest):
    """Ручной запуск загрузки архива BetsAPI (GET /v3/events/ended по дням).
    Задача выполняется в Celery: раз в delay_seconds запрос по страницам, с 2016 года.
    Матчи пишутся в Match + MatchScore + MatchResult; если матч с таким provider_match_id уже есть — пропускаем."""
    task = load_betsapi_history_task.delay(
        day_from=body.day_from,
        day_to=body.day_to,
        delay_seconds=body.delay_seconds,
    )
    return LoadHistoryResponse(
        task_id=task.id,
        message="Задача загрузки архива запущена. Результат смотрите в логах Celery или по task_id.",
    )


@router.get("/load-history/status", response_model=LoadHistoryStatusResponse)
async def load_history_status(
    day_from: str = Query("20160901", description="Начало диапазона YYYYMMDD"),
    day_to: str | None = Query(None, description="Конец диапазона YYYYMMDD (по умолчанию сегодня)"),
    session: AsyncSession = Depends(get_async_session),
):
    """По каким дням все страницы архива обработаны (completed), по каким ещё нет (not_completed), постраничный прогресс."""
    if day_to is None:
        day_to = datetime.now(timezone.utc).strftime("%Y%m%d")
    all_days = _days_in_range(day_from, day_to)
    r = await session.execute(
        select(
            BetsapiArchiveProgress.day_yyyymmdd,
            BetsapiArchiveProgress.last_processed_page,
            BetsapiArchiveProgress.completed_at,
        ).where(
            BetsapiArchiveProgress.provider == "betsapi",
            BetsapiArchiveProgress.day_yyyymmdd >= day_from,
            BetsapiArchiveProgress.day_yyyymmdd <= day_to,
        )
    )
    rows = r.all()
    completed_set = {row[0] for row in rows if row[2] is not None}
    completed = sorted(d for d in all_days if d in completed_set)
    not_completed = sorted(d for d in all_days if d not in completed_set)
    by_day = {row[0]: (row[1], row[2] is not None) for row in rows}
    progress = [
        DayProgress(
            day=d,
            completed=by_day[d][1] if d in by_day else False,
            last_processed_page=by_day[d][0] if d in by_day else None,
        )
        for d in all_days
    ]
    return LoadHistoryStatusResponse(
        day_from=day_from,
        day_to=day_to,
        completed=completed,
        not_completed=not_completed,
        progress=progress,
    )


@router.get("/live", response_model=list[MatchListWithOdds])
async def list_live_matches(
    session: AsyncSession = Depends(get_async_session),
):
    """Матчи в лайве + недавно завершённые (до 5 минут после окончания), затем они уходят в результаты. Отменённые и отложенные не показываем."""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=LIVE_RECENTLY_FINISHED_MINUTES)
        q = (
            select(Match)
            .where(
                Match.status.notin_([MatchStatus.CANCELLED.value, MatchStatus.POSTPONED.value]),
                or_(
                    Match.status == MatchStatus.LIVE.value,
                    and_(
                        Match.status == MatchStatus.FINISHED.value,
                        Match.result.has(MatchResult.finished_at >= cutoff),
                    ),
                ),
            )
            .options(
                selectinload(Match.league),
                selectinload(Match.home_player),
                selectinload(Match.away_player),
                selectinload(Match.scores),
                selectinload(Match.odds_snapshots),
                selectinload(Match.result).selectinload(MatchResult.winner),
            )
            .order_by(Match.start_time.desc())
        )
        result = await session.execute(q)
        return result.scalars().all()
    except Exception as e:
        logger.exception("list_live_matches failed: %s", e)
        raise


@router.get("/upcoming", response_model=list[MatchListWithOdds])
async def list_upcoming_matches(
    limit: int = Query(50, le=200),
    session: AsyncSession = Depends(get_async_session),
):
    """Матчи в линии (запланированы). Только те, у которых время начала ещё не прошло (или прошло не более 15 мин)."""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=UPCOMING_START_CUTOFF_MINUTES)
        q = (
            select(Match)
            .where(
                Match.status == MatchStatus.SCHEDULED.value,
                Match.start_time >= cutoff,
            )
            .options(
                selectinload(Match.league),
                selectinload(Match.home_player),
                selectinload(Match.away_player),
                selectinload(Match.scores),
                selectinload(Match.odds_snapshots),
                selectinload(Match.result).selectinload(MatchResult.winner),
            )
            .order_by(Match.start_time.asc())
            .limit(limit)
        )
        result = await session.execute(q)
        return result.scalars().all()
    except Exception as e:
        logger.exception("list_upcoming_matches failed: %s", e)
        raise


@router.get("/finished", response_model=FinishedMatchesResponse)
async def list_finished_matches(
    limit: int = Query(50, le=500),
    offset: int = Query(0, ge=0),
    date_from: str | None = Query(None, description="Начало периода YYYY-MM-DD (по start_time матча)"),
    date_to: str | None = Query(None, description="Конец периода YYYY-MM-DD включительно"),
    league_id: UUID | None = Query(None, description="Фильтр по лиге"),
    player_id: UUID | None = Query(None, description="Фильтр по участнику (хозяин или гость)"),
    session: AsyncSession = Depends(get_async_session),
):
    """Завершённые матчи (включая архив). Отменённые и отложенные не показываем. Фильтры по дате, лиге, игроку; пагинация."""
    conditions = [Match.status == MatchStatus.FINISHED.value]
    if date_from:
        try:
            start_dt = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            conditions.append(Match.start_time >= start_dt)
        except ValueError:
            pass
    if date_to:
        try:
            end_dt = datetime.strptime(date_to, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc
            )
            conditions.append(Match.start_time <= end_dt)
        except ValueError:
            pass
    if league_id is not None:
        conditions.append(Match.league_id == league_id)
    if player_id is not None:
        conditions.append(or_(Match.home_player_id == player_id, Match.away_player_id == player_id))

    count_q = select(func.count(Match.id)).where(and_(*conditions))
    total = (await session.execute(count_q)).scalar() or 0

    q = (
        select(Match)
        .where(and_(*conditions))
        .options(
            selectinload(Match.league),
            selectinload(Match.home_player),
            selectinload(Match.away_player),
            selectinload(Match.scores),
            selectinload(Match.result).selectinload(MatchResult.winner),
        )
        .order_by(Match.start_time.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(q)
    items = result.scalars().all()
    return FinishedMatchesResponse(total=total, items=items)


@router.get("/{match_id}/stored-recommendation")
async def get_stored_recommendation(
    match_id: UUID,
    session: AsyncSession = Depends(get_async_session),
):
    """Рекомендация, сохранённая из таблицы линии/лайва (прематч). Та же, что в колонке «Рекомендация»."""
    q = select(MatchRecommendation).where(MatchRecommendation.match_id == match_id)
    r = await session.execute(q)
    rec = r.scalar_one_or_none()
    return {"recommendation": rec.recommendation_text if rec else None}


@router.get("/{match_id}", response_model=MatchDetail)
async def get_match(
    match_id: UUID,
    session: AsyncSession = Depends(get_async_session),
):
    from fastapi import HTTPException

    q = (
        select(Match)
        .where(Match.id == match_id)
        .options(
            selectinload(Match.league),
            selectinload(Match.home_player),
            selectinload(Match.away_player),
            selectinload(Match.scores),
            selectinload(Match.odds_snapshots),
            selectinload(Match.result).selectinload(MatchResult.winner),
        )
    )
    result = await session.execute(q)
    match = result.scalar_one_or_none()
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")
    return match
