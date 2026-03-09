"""Matches API."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select, func, exists, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy.orm.attributes import set_committed_value

import httpx

from app.db.session import get_async_session
from app.config import settings
from app.api.v1.admin import require_admin
from app.models import Match, MatchStatus, BetsapiArchiveProgress
from app.models.match_result import MatchResult
from app.models.match_recommendation import MatchRecommendation
from app.models.odds_snapshot import OddsSnapshot
from app.schemas.match import MatchDetail, MatchList, MatchListWithOdds, MatchListWithResult, FinishedMatchesResponse
from app.worker.tasks.collect_betsapi import (
    load_betsapi_history_task,
    backfill_missing_results_task,
    precompute_recommendation_for_match_task,
    backfill_line_odds_task,
)
from app.services.normalizer import Normalizer


class MatchesOverviewResponse(BaseModel):
    """Лайв и линия в одном ответе — один запрос вместо двух."""
    live: list[MatchListWithOdds] = Field(default_factory=list, description="Матчи в лайве + недавно завершённые")
    upcoming: list[MatchListWithOdds] = Field(default_factory=list, description="Матчи в линии (до начала)")


router = APIRouter()
logger = logging.getLogger(__name__)

LIVE_RECENTLY_FINISHED_MINUTES = 5
# Линия: только матчи, которые ещё НЕ начались (start_time > now). Раньше был буфер 15 мин — из-за этого в линии попадали матчи уже в лайве.
LINE_ONLY_FUTURE = True  # строго будущие; если False — показывать и те, что «только что начались» (start_time >= now - 1 min)
UPCOMING_START_CUTOFF_MINUTES = 0 if LINE_ONLY_FUTURE else 1

# Минимальный коэффициент, при котором рекомендация считается «играбельной».
MIN_RECOMMENDATION_ODDS = 1.4


class LoadHistoryRequest(BaseModel):
    """Параметры ручной загрузки архива завершённых матчей BetsAPI."""
    day_from: str = Field(default="20160901", description="Начальная дата YYYYMMDD (min 20160901)")
    day_to: str | None = Field(default=None, description="Конечная дата YYYYMMDD, по умолчанию сегодня")
    delay_seconds: float = Field(default=1.0, ge=0, le=60, description="Пауза между запросами к API (сек)")
    resume_from_progress: bool = Field(
        default=True,
        description="Продолжить с незавершённой даты/следующей после последней завершённой в диапазоне",
    )


class LoadHistoryResponse(BaseModel):
    task_id: str
    message: str


class BackfillResultsResponse(BaseModel):
    task_id: str
    message: str


class ResetProgressRequest(BaseModel):
    day_from: str = Field(description="Начало диапазона YYYYMMDD")
    day_to: str = Field(description="Конец диапазона YYYYMMDD")
    reset_single_page_only: bool = Field(
        default=True,
        description="Сбросить только дни с last_processed_page=1 (пересобрать «одностраничные» дни)",
    )


class ResetProgressResponse(BaseModel):
    reset_days: list[str] = Field(description="Дни, для которых сброшен прогресс")
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
    single_page_days: list[str] = Field(
        default_factory=list,
        description="Дни, помеченные завершёнными с last_processed_page=1 (кандидаты на пересборку)",
    )


class LineStatusResponse(BaseModel):
    """Диагностика: запрашивается ли линия, почему может быть пустой."""
    scheduler_enabled: bool = Field(description="ENABLE_SCHEDULED_COLLECTORS — задача линии в расписании Beat")
    token_set: bool = Field(description="BETSAPI_TOKEN задан")
    upcoming_in_db: int = Field(description="Матчей в БД (scheduled/pending_odds, start_time > now)")
    line_rate_limited_ttl_sec: int | None = Field(default=None, description="Пауза после 429 (сек до возобновления)")
    debug_hint: str | None = Field(default=None, description="Подсказка по отладке при пустой линии")


@router.get("/line-status", response_model=LineStatusResponse)
async def get_line_status(session: AsyncSession = Depends(get_async_session)):
    """Диагностика линии: включён ли планировщик, задан ли токен, сколько матчей в БД, пауза после 429."""
    now = datetime.now(timezone.utc)
    if LINE_ONLY_FUTURE:
        upcoming_start_filter = Match.start_time > now
    else:
        upcoming_start_filter = Match.start_time >= now - timedelta(minutes=UPCOMING_START_CUTOFF_MINUTES)
    scheduler_enabled = getattr(settings, "enable_scheduled_collectors", False)
    token_set = bool((settings.betsapi_token or "").strip())
    q = select(func.count(Match.id)).where(
        or_(
            Match.status == MatchStatus.SCHEDULED.value,
            Match.status == MatchStatus.PENDING_ODDS.value,
        ),
        upcoming_start_filter,
    )
    upcoming_in_db = (await session.execute(q)).scalar() or 0
    line_rate_limited_ttl_sec: int | None = None
    try:
        from redis.asyncio import from_url as redis_from_url
        r = redis_from_url(settings.redis_url, decode_responses=True)
        try:
            ttl = await r.ttl("betsapi:line_rate_limited")
            if ttl > 0:
                line_rate_limited_ttl_sec = ttl
        finally:
            await r.aclose()
    except Exception:
        pass
    debug_hint: str | None = None
    if upcoming_in_db == 0 and token_set and scheduler_enabled:
        debug_hint = (
            "Запустите задачу линии вручную и смотрите логи celery_betsapi_worker: "
            "«BetsAPI events/upcoming» (пришли ли события), «BetsAPI line: got N events», «normalize_betsapi: events=...» (сколько сохранено). "
            "Команда: docker compose run --rm celery_betsapi_worker uv run celery -A app.worker.celery_app call app.worker.tasks.collect_betsapi.fetch_betsapi_table_tennis_task --kwargs='{\"mode\": \"line\"}'"
        )
    return LineStatusResponse(
        scheduler_enabled=scheduler_enabled,
        token_set=token_set,
        upcoming_in_db=upcoming_in_db,
        line_rate_limited_ttl_sec=line_rate_limited_ttl_sec,
        debug_hint=debug_hint,
    )


def _days_in_range(day_from: str, day_to: str) -> list[str]:
    start = datetime.strptime(day_from, "%Y%m%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(day_to, "%Y%m%d").replace(tzinfo=timezone.utc)
    out: list[str] = []
    d = start
    while d <= end:
        out.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    return out


# Рынки «победитель» — для лайва достаточно только их в списке (ускоряет запрос). 1_1 = v4 prematch.
WINNER_MARKETS = ("92_1", "winner", "win", "1_1")


async def _attach_latest_odds_snapshots(session: AsyncSession, matches: list[Match]) -> None:
    """Attach latest odds snapshot per (market, selection, phase) for each match."""
    if not matches:
        return
    match_ids = [m.id for m in matches]
    ranked = (
        select(
            OddsSnapshot.id.label("snapshot_id"),
            func.row_number().over(
                partition_by=(
                    OddsSnapshot.match_id,
                    OddsSnapshot.market,
                    OddsSnapshot.selection,
                    OddsSnapshot.phase,
                ),
                order_by=func.coalesce(OddsSnapshot.snapshot_time, OddsSnapshot.timestamp).desc(),
            ).label("rn"),
        )
        .where(OddsSnapshot.match_id.in_(match_ids))
        .subquery()
    )
    latest_q = (
        select(OddsSnapshot)
        .join(ranked, ranked.c.snapshot_id == OddsSnapshot.id)
        .where(ranked.c.rn == 1)
    )
    latest = (await session.execute(latest_q)).scalars().all()
    grouped: dict[UUID, list[OddsSnapshot]] = {}
    for item in latest:
        grouped.setdefault(item.match_id, []).append(item)
    for match in matches:
        set_committed_value(match, "odds_snapshots", grouped.get(match.id, []))


async def _attach_live_winner_odds_only(session: AsyncSession, matches: list[Match]) -> None:
    """Для лайва: только рынок победителя (92_1/winner/win), earliest по времени — меньше данных и быстрее запрос."""
    if not matches:
        return
    match_ids = [m.id for m in matches]
    ranked = (
        select(
            OddsSnapshot.id.label("snapshot_id"),
            func.row_number().over(
                partition_by=(
                    OddsSnapshot.match_id,
                    OddsSnapshot.market,
                    OddsSnapshot.selection,
                    OddsSnapshot.phase,
                ),
                order_by=func.coalesce(OddsSnapshot.snapshot_time, OddsSnapshot.timestamp).asc(),
            ).label("rn"),
        )
        .where(
            OddsSnapshot.match_id.in_(match_ids),
            OddsSnapshot.market.in_(WINNER_MARKETS),
        )
        .subquery()
    )
    q = (
        select(OddsSnapshot)
        .join(ranked, ranked.c.snapshot_id == OddsSnapshot.id)
        .where(ranked.c.rn == 1)
    )
    rows = (await session.execute(q)).scalars().all()
    grouped: dict[UUID, list[OddsSnapshot]] = {}
    for item in rows:
        grouped.setdefault(item.match_id, []).append(item)
    for match in matches:
        set_committed_value(match, "odds_snapshots", grouped.get(match.id, []))


async def _attach_earliest_odds_snapshots_for_live(session: AsyncSession, match: Match) -> None:
    """Для лайв-матча оставляет только снимки на старте (earliest по времени) — кф в лайве не обновляются."""
    if not match.id or (match.status or "").strip().lower() != MatchStatus.LIVE.value:
        return
    ranked = (
        select(
            OddsSnapshot.id.label("snapshot_id"),
            func.row_number().over(
                partition_by=(
                    OddsSnapshot.market,
                    OddsSnapshot.selection,
                    OddsSnapshot.phase,
                ),
                order_by=func.coalesce(OddsSnapshot.snapshot_time, OddsSnapshot.timestamp).asc(),
            ).label("rn"),
        )
        .where(OddsSnapshot.match_id == match.id)
        .subquery()
    )
    earliest_q = (
        select(OddsSnapshot)
        .join(ranked, ranked.c.snapshot_id == OddsSnapshot.id)
        .where(ranked.c.rn == 1)
    )
    earliest = (await session.execute(earliest_q)).scalars().all()
    set_committed_value(match, "odds_snapshots", list(earliest))


async def _refresh_live_from_betsapi(session: AsyncSession) -> int:
    """
    Fallback: если в БД нет лайв-матчей, один раз подтягиваем события из BetsAPI /events/inplay
    и нормализуем их напрямую, без очереди Celery.
    """
    token = (settings.betsapi_token or "").strip()
    if not token:
        return 0
    sid = getattr(settings, "betsapi_table_tennis_sport_id", 92)
    base = "https://api.b365api.com/v3"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{base}/events/inplay", params={"sport_id": sid, "token": token})
        if not r.is_success:
            logger.warning("BetsAPI live fallback: HTTP %s body=%s", r.status_code, (r.text or "")[:200])
            return 0
        data = r.json() or {}
    except Exception as e:
        logger.warning("BetsAPI live fallback request failed: %s", e)
        return 0

    results_raw = data.get("results") or data.get("events") or data.get("data")
    if not isinstance(results_raw, list) or not results_raw:
        return 0

    events: list[dict] = []
    current_ids: set[str] = set()
    for ev in results_raw:
        if not isinstance(ev, dict):
            continue
        e = dict(ev)
        e["_source"] = "inplay"
        eid = e.get("id") or e.get("event_id")
        if eid is None:
            continue
        eid_str = str(eid)
        current_ids.add(eid_str)
        events.append(e)
    if not events:
        return 0

    norm = Normalizer(session)
    try:
        match_ids = await norm.normalize_betsapi_response(events, current_event_ids=current_ids)
        # Гарантируем, что все текущие inplay‑матчи помечены как LIVE, а не застряли
        # в scheduled/pending_odds (как бывает при рассинхроне пайплайнов линии/лайва).
        from sqlalchemy import update
        from app.models import MatchStatus as _MS

        if current_ids:
            try:
                stmt = (
                    update(Match)
                    .where(
                        Match.provider == "betsapi",
                        Match.provider_match_id.in_(list(current_ids)),
                        Match.status.in_([_MS.SCHEDULED.value, _MS.PENDING_ODDS.value]),
                    )
                    .values(status=_MS.LIVE.value)
                )
                await session.execute(stmt)
                await session.commit()
            except Exception as e2:
                logger.warning("live fallback: failed to force LIVE status for inplay matches: %s", e2)
        return len(match_ids)
    except Exception as e:
        logger.warning("BetsAPI live fallback normalize failed: %s", e)
        return 0


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
    Только сохранённые прогнозы (те же, что в статистике).
    Расчёт выполняется автоматически воркером для матчей линии/лайва (после сбора кф); фронт запрашивает по id матчей с коэффициентами и отображает в таблице.
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
    # Сначала загружаем сохранённые прогнозы — в таблице показываем то же, что в статистике.
    # Игнорируем прогнозы с заведомо низким коэффициентом (ниже MIN_RECOMMENDATION_ODDS).
    stored_q = (
        select(
            MatchRecommendation.match_id,
            MatchRecommendation.recommendation_text,
            MatchRecommendation.odds_at_recommendation,
        )
        .where(MatchRecommendation.match_id.in_(ids))
        .where(
            (MatchRecommendation.odds_at_recommendation.is_(None))
            | (MatchRecommendation.odds_at_recommendation >= MIN_RECOMMENDATION_ODDS)
        )
    )
    stored_r = await session.execute(stored_q)
    stored = {str(row[0]): row[1] for row in stored_r.all()}
    for mid in ids:
        if str(mid) in stored and stored[str(mid)]:
            out[str(mid)] = stored[str(mid)]
            continue
        out[str(mid)] = None
    missing = [mid for mid in ids if out.get(str(mid)) is None]
    # Для лайв/линии без предрасчёта — ставим расчёт в очередь, чтобы при следующем запросе прогноз появился.
    if missing and (settings.betsapi_token or "").strip():
        live_or_scheduled = (
            select(Match.id)
            .where(
                Match.id.in_(missing),
                Match.status.in_([MatchStatus.LIVE.value, MatchStatus.SCHEDULED.value]),
            )
        )
        r_need = await session.execute(live_or_scheduled)
        need_rec = [str(row[0]) for row in r_need.all()]
        for mid_str in need_rec[:15]:  # не более 15 за запрос
            try:
                precompute_recommendation_for_match_task.delay(mid_str)
            except Exception as e:
                logger.debug("queue precompute for match %s: %s", mid_str, e)
        if need_rec:
            logger.info("matches/recommendations: queued precompute for %s live/scheduled match(es) without recommendation", len(need_rec[:15]))
    missing_count = len(missing)
    if missing_count:
        logger.info("matches/recommendations: %s match(es) have no stored recommendation", missing_count)
    return out


@router.post("/load-history", response_model=LoadHistoryResponse)
async def load_history(
    body: LoadHistoryRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Ручной запуск загрузки архива BetsAPI (GET /v3/events/ended по дням).
    Задача выполняется в Celery: раз в delay_seconds запрос по страницам, с 2016 года.
    Матчи пишутся в Match + MatchScore + MatchResult; если матч с таким provider_match_id уже есть — пропускаем."""
    day_to = body.day_to or datetime.now(timezone.utc).strftime("%Y%m%d")
    day_from = body.day_from

    if body.resume_from_progress:
        # Первый день в диапазоне, который нужно догрузить: нет записи или запись с completed_at=NULL.
        all_days = _days_in_range(day_from, day_to)
        r = await session.execute(
            select(
                BetsapiArchiveProgress.day_yyyymmdd,
                BetsapiArchiveProgress.completed_at,
            ).where(
                BetsapiArchiveProgress.provider == "betsapi",
                BetsapiArchiveProgress.day_yyyymmdd >= day_from,
                BetsapiArchiveProgress.day_yyyymmdd <= day_to,
            )
        )
        rows = r.all()
        completed_set = {row[0] for row in rows if row[1] is not None}
        not_completed = [d for d in all_days if d not in completed_set]
        if not_completed:
            day_from = not_completed[0]

    task = load_betsapi_history_task.apply_async(
        kwargs={
            "day_from": day_from,
            "day_to": day_to,
            "delay_seconds": body.delay_seconds,
        },
        queue="history",
    )
    return LoadHistoryResponse(
        task_id=task.id,
        message=f"Задача загрузки архива запущена с day_from={day_from}, day_to={day_to}. "
                "Результат смотрите в логах Celery или по task_id.",
    )


@router.post("/backfill-results", response_model=BackfillResultsResponse)
async def backfill_results(
    match_ids: str | None = Query(None, description="UUID матчей через запятую для догрузки только этих результатов; пусто — все подходящие"),
    _: bool = Depends(require_admin),
):
    """Ручной запуск догрузки результатов по матчам без результата (только для админа).

    1) Создание MatchResult из MatchScore для всех finished без результата.
    2) Сброс счётчика попыток у зависших матчей (старт > 7 дней назад).
    3) Дозапрос events/ended и event/view у BetsAPI по матчам без результата.
    Если передан match_ids — обрабатываются только эти матчи."""
    from uuid import UUID
    ids_arg: list[str] | None = None
    if match_ids and (match_ids := match_ids.strip()):
        ids_arg = [x.strip() for x in match_ids.split(",") if x.strip()]
        try:
            [UUID(mid) for mid in ids_arg]
        except ValueError:
            raise HTTPException(status_code=400, detail="match_ids: неверный формат UUID")
    task = backfill_missing_results_task.apply_async(queue="betsapi_collect", kwargs={"match_ids": ids_arg})
    return BackfillResultsResponse(
        task_id=task.id,
        message="Задача догрузки результатов запущена." + (" Обрабатываются указанные матчи." if ids_arg else " Результат в логах Celery."),
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
    single_page_days = sorted(
        d for d in completed_set
        if by_day[d][0] == 1
    )
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
        single_page_days=single_page_days,
    )


@router.post("/load-history/reset-progress", response_model=ResetProgressResponse)
async def reset_archive_progress(
    body: ResetProgressRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Сбросить прогресс загрузки архива по указанным дням, чтобы пересобрать данные.
    По умолчанию сбрасываются только дни с last_processed_page=1 (завершённые одной страницей).
    После сброса запустите POST /matches/load-history с тем же day_from/day_to и resume_from_progress=true."""
    day_from = body.day_from
    day_to = body.day_to
    if body.reset_single_page_only:
        r = await session.execute(
            select(BetsapiArchiveProgress.day_yyyymmdd).where(
                BetsapiArchiveProgress.provider == "betsapi",
                BetsapiArchiveProgress.day_yyyymmdd >= day_from,
                BetsapiArchiveProgress.day_yyyymmdd <= day_to,
                BetsapiArchiveProgress.last_processed_page == 1,
                BetsapiArchiveProgress.completed_at.is_not(None),
            )
        )
        to_reset = sorted(r.scalars().all())
    else:
        r = await session.execute(
            select(BetsapiArchiveProgress.day_yyyymmdd).where(
                BetsapiArchiveProgress.provider == "betsapi",
                BetsapiArchiveProgress.day_yyyymmdd >= day_from,
                BetsapiArchiveProgress.day_yyyymmdd <= day_to,
            )
        )
        to_reset = sorted(r.scalars().all())
    if not to_reset:
        return ResetProgressResponse(
            reset_days=[],
            message="Нет дней для сброса в указанном диапазоне.",
        )
    stmt = (
        update(BetsapiArchiveProgress)
        .where(
            BetsapiArchiveProgress.provider == "betsapi",
            BetsapiArchiveProgress.day_yyyymmdd.in_(to_reset),
        )
        .values(completed_at=None, last_processed_page=None)
    )
    await session.execute(stmt)
    await session.commit()
    logger.info("reset_archive_progress: сброшено %s дней: %s", len(to_reset), to_reset[:10])
    return ResetProgressResponse(
        reset_days=to_reset,
        message=f"Сброшен прогресс по {len(to_reset)} дням. Запустите POST /matches/load-history с day_from={day_from}, day_to={day_to}, resume_from_progress=true.",
    )


def _live_where():
    now = datetime.now(timezone.utc)
    live_cutoff = now - timedelta(minutes=LIVE_RECENTLY_FINISHED_MINUTES)
    return (
        Match.status.notin_([MatchStatus.CANCELLED.value, MatchStatus.POSTPONED.value]),
        or_(
            and_(
                Match.status == MatchStatus.LIVE.value,
                Match.updated_at >= live_cutoff,
            ),
            and_(
                Match.status == MatchStatus.FINISHED.value,
                Match.result.has(MatchResult.finished_at >= live_cutoff),
            ),
        ),
    )


@router.get("/live", response_model=MatchesOverviewResponse)
async def list_matches_live(
    limit: int = Query(200, ge=1, le=200, description="Макс. матчей в лайве"),
    session: AsyncSession = Depends(get_async_session),
):
    """Быстрый эндпоинт только для лайва: один запрос с JOIN, коэффициенты только по победителю. Использовать вместо overview при limit_upcoming=0."""
    now = datetime.now(timezone.utc)
    live_cutoff = now - timedelta(minutes=LIVE_RECENTLY_FINISHED_MINUTES)
    status_cond, time_cond = _live_where()
    q = (
        select(Match)
        .where(status_cond, time_cond)
        .options(
            joinedload(Match.league),
            joinedload(Match.home_player),
            joinedload(Match.away_player),
            joinedload(Match.scores),
            joinedload(Match.result).joinedload(MatchResult.winner),
        )
        .order_by(Match.start_time.desc())
        .limit(limit)
    )
    res = await session.execute(q)
    live_matches = list(res.unique().scalars().all())
    if not live_matches:
        created = await _refresh_live_from_betsapi(session)
        if created:
            res2 = await session.execute(q)
            live_matches = list(res2.unique().scalars().all())
    await _attach_live_winner_odds_only(session, live_matches)
    return MatchesOverviewResponse(live=live_matches, upcoming=[])


@router.get("/overview", response_model=MatchesOverviewResponse)
async def list_matches_overview(
    limit_live: int = Query(100, ge=0, le=200, description="Макс. матчей в лайве (0 — не запрашивать)"),
    limit_upcoming: int = Query(100, ge=0, le=200, description="Макс. матчей в линии (0 — не запрашивать)"),
    session: AsyncSession = Depends(get_async_session),
):
    """Лайв и линия в одном запросе. При запросе только лайва (limit_upcoming=0) используется быстрый путь."""
    try:
        now = datetime.now(timezone.utc)
        live_cutoff = now - timedelta(minutes=LIVE_RECENTLY_FINISHED_MINUTES)

        # Быстрый путь: только лайв — один запрос с joinedload и лёгкие кф (только победитель).
        if limit_live > 0 and limit_upcoming == 0:
            status_cond, time_cond = _live_where()
            q_live = (
                select(Match)
                .where(status_cond, time_cond)
                .options(
                    joinedload(Match.league),
                    joinedload(Match.home_player),
                    joinedload(Match.away_player),
                    joinedload(Match.scores),
                    joinedload(Match.result).joinedload(MatchResult.winner),
                )
                .order_by(Match.start_time.desc())
                .limit(limit_live)
            )
            res = await session.execute(q_live)
            live_matches = list(res.unique().scalars().all())
            if not live_matches:
                created = await _refresh_live_from_betsapi(session)
                if created:
                    res2 = await session.execute(q_live)
                    live_matches = list(res2.unique().scalars().all())
            await _attach_live_winner_odds_only(session, live_matches)
            return MatchesOverviewResponse(live=live_matches, upcoming=[])

        def _live_query():
            return (
                select(Match)
                .where(
                    Match.status.notin_([MatchStatus.CANCELLED.value, MatchStatus.POSTPONED.value]),
                    or_(
                        and_(
                            Match.status == MatchStatus.LIVE.value,
                            Match.updated_at >= live_cutoff,
                        ),
                        and_(
                            Match.status == MatchStatus.FINISHED.value,
                            Match.result.has(MatchResult.finished_at >= live_cutoff),
                        ),
                    ),
                )
                .options(
                    selectinload(Match.league),
                    selectinload(Match.home_player),
                    selectinload(Match.away_player),
                    selectinload(Match.scores),
                    selectinload(Match.result).selectinload(MatchResult.winner),
                )
                .order_by(Match.start_time.desc())
                .limit(limit_live)
            )

        live_matches: list[Match] = []
        upcoming_matches: list[Match] = []
        now_for_line = datetime.now(timezone.utc)
        if LINE_ONLY_FUTURE:
            upcoming_start_filter = Match.start_time > now_for_line
        else:
            upcoming_start_filter = Match.start_time >= now_for_line - timedelta(minutes=UPCOMING_START_CUTOFF_MINUTES)
        status_ok = or_(
            Match.status == MatchStatus.SCHEDULED.value,
            Match.status == MatchStatus.PENDING_ODDS.value,
        )
        q_upcoming = (
            select(Match)
            .where(status_ok, upcoming_start_filter)
            .options(
                selectinload(Match.league),
                selectinload(Match.home_player),
                selectinload(Match.away_player),
                selectinload(Match.scores),
                selectinload(Match.result).selectinload(MatchResult.winner),
            )
            .order_by(Match.start_time.asc())
            .limit(limit_upcoming)
        ) if limit_upcoming > 0 else None

        if limit_live > 0 and limit_upcoming > 0:
            res_live, res_upcoming = await asyncio.gather(
                session.execute(_live_query()),
                session.execute(q_upcoming),
            )
            live_matches = list(res_live.scalars().all())
            upcoming_matches = list(res_upcoming.scalars().all())
        else:
            if limit_live > 0:
                res_live = await session.execute(_live_query())
                live_matches = list(res_live.scalars().all())
            if limit_upcoming > 0:
                res_upcoming = await session.execute(q_upcoming)
                upcoming_matches = list(res_upcoming.scalars().all())

        if limit_live > 0 and not live_matches:
            created = await _refresh_live_from_betsapi(session)
            if created:
                res_live = await session.execute(_live_query())
                live_matches = list(res_live.scalars().all())

        async def _attach_live():
            await _attach_latest_odds_snapshots(session, live_matches)
        async def _attach_upcoming():
            await _attach_latest_odds_snapshots(session, upcoming_matches)

        if limit_live > 0 and limit_upcoming > 0:
            await asyncio.gather(_attach_live(), _attach_upcoming())
        else:
            if limit_live > 0:
                await _attach_latest_odds_snapshots(session, live_matches)
            if limit_upcoming > 0:
                await _attach_latest_odds_snapshots(session, upcoming_matches)

        if limit_upcoming > 0:
            if not upcoming_matches:
                count_line_in_db = await session.execute(
                    select(func.count(Match.id)).where(
                        or_(
                            Match.status == MatchStatus.SCHEDULED.value,
                            Match.status == MatchStatus.PENDING_ODDS.value,
                        )
                    )
                )
                total_line = count_line_in_db.scalar() or 0
                logger.info(
                    "matches/overview: 0 upcoming (line). DB has %s scheduled/pending_odds total. Check BETSAPI_TOKEN, ENABLE_SCHEDULED_COLLECTORS and Celery line task.",
                    total_line,
                )
            for m in upcoming_matches:
                snapshots = getattr(m, "odds_snapshots", None) or []
                line_only = [s for s in snapshots if getattr(s, "phase", None) in (None, "line")]
                set_committed_value(m, "odds_snapshots", line_only)
            without_odds = sum(1 for m in upcoming_matches if not (getattr(m, "odds_snapshots", None) and len(getattr(m, "odds_snapshots", [])) > 0))
            if without_odds >= 3 and (settings.betsapi_token or "").strip():
                try:
                    from redis import Redis
                    r = Redis.from_url(settings.redis_url, decode_responses=True)
                    if r.set("line_odds_backfill_trigger", "1", ex=60, nx=True):
                        backfill_line_odds_task.delay()
                        logger.info("matches/overview: triggered line odds backfill (%s upcoming without odds)", without_odds)
                    r.close()
                except Exception as e:
                    logger.debug("matches/overview: trigger line odds backfill: %s", e)

        return MatchesOverviewResponse(live=live_matches, upcoming=upcoming_matches)
    except Exception as e:
        logger.exception("list_matches_overview failed: %s", e)
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
    """Прогноз, сохранённый из таблицы линии/лайва (прематч). Тот же, что в колонке «Прогноз»."""
    q = select(MatchRecommendation).where(MatchRecommendation.match_id == match_id)
    r = await session.execute(q)
    rec = r.scalar_one_or_none()
    return {"recommendation": rec.recommendation_text if rec else None}


@router.post("/{match_id}/ensure-recommendation")
async def ensure_recommendation(
    match_id: UUID,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Запустить расчёт и сохранение прогноза для матча, если его ещё нет.
    Прогноз создаётся фоновой задачей; после вызова стоит обновить страницу или повторно запросить stored-recommendation через 3–5 сек.
    """
    from fastapi import HTTPException
    q_match = select(Match).where(Match.id == match_id)
    r_match = await session.execute(q_match)
    match = r_match.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if match.status not in ("scheduled", "live"):
        raise HTTPException(status_code=400, detail="Recommendation only for scheduled or live matches")
    if not match.home_player_id or not match.away_player_id:
        raise HTTPException(status_code=400, detail="Match has no players")
    q_rec = select(MatchRecommendation).where(MatchRecommendation.match_id == match_id)
    r_rec = await session.execute(q_rec)
    rec = r_rec.scalar_one_or_none()
    if rec:
        return {"recommendation": rec.recommendation_text, "already": True}
    precompute_recommendation_for_match_task.delay(str(match_id))
    return {"queued": True, "message": "Recommendation generation started"}


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
    if (match.status or "").strip().lower() == MatchStatus.LIVE.value:
        await _attach_earliest_odds_snapshots_for_live(session, match)
    return match
