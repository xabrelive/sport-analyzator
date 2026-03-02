"""Fetch table tennis events and odds from BetsAPI and save to DB.

Режимы:
- full: раз в 5–10 мин — списки upcoming+inplay, view+odds (линия один раз, лайв только при изменении счёта).
- live: список inplay каждые 3 сек — счёт по сетам; коэффициенты запрашиваем сразу только по матчам, где изменился счёт.
"""
import asyncio
import logging
from typing import Any

from sqlalchemy import or_, select

from app.config import settings
from app.db.session import create_worker_engine_and_session
from app.models import Match, MatchScore, OddsSnapshot
from app.services.collectors.betsapi_collector import BetsApiCollector
from app.services.normalizer import Normalizer, _event_sets_scores
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _upcoming_provider_ids_with_odds(
    provider_match_ids: list[str],
    session_maker,
) -> set[str]:
    """Возвращает provider_match_id, по которым уже есть хотя бы один line-снимок (прематч)."""
    if not provider_match_ids:
        return set()
    async with session_maker() as session:
        stmt = (
            select(Match.provider_match_id)
            .where(
                Match.provider == "betsapi",
                Match.provider_match_id.in_(provider_match_ids),
            )
            .join(OddsSnapshot, OddsSnapshot.match_id == Match.id)
            .where(or_(OddsSnapshot.phase == "line", OddsSnapshot.phase.is_(None)))
            .distinct()
        )
        result = await session.execute(stmt)
        return set(r[0] for r in result.all())


async def _inplay_ids_with_score_change(
    events: list[dict[str, Any]],
    session_maker,
) -> list[str]:
    """Возвращает provider_match_id лайв-матчей, у которых счёт по сетам изменился относительно БД (или матч новый)."""
    inplay = [e for e in events if isinstance(e, dict) and e.get("_source") == "inplay"]
    if not inplay:
        return []
    inplay_ids = [str(e["id"]) for e in inplay if e.get("id") is not None]
    if not inplay_ids:
        return []

    async with session_maker() as session:
        # provider_match_id -> match_id
        stmt = select(Match.provider_match_id, Match.id).where(
            Match.provider == "betsapi",
            Match.provider_match_id.in_(inplay_ids),
        )
        rows = (await session.execute(stmt)).all()
        pid_to_mid = {str(pid): mid for pid, mid in rows}
        match_ids = list(set(pid_to_mid.values()))

        if not match_ids:
            return inplay_ids  # все матчи новые — запрашиваем odds по всем

        # match_id -> [(home_score, away_score), ...] по set_number
        stmt2 = (
            select(MatchScore.match_id, MatchScore.set_number, MatchScore.home_score, MatchScore.away_score)
            .where(MatchScore.match_id.in_(match_ids))
            .order_by(MatchScore.match_id, MatchScore.set_number)
        )
        rows2 = (await session.execute(stmt2)).all()
        scores_by_match: dict = {}
        for match_id, set_num, h, a in rows2:
            scores_by_match.setdefault(match_id, []).append((h, a))

    result: list[str] = []
    for event in inplay:
        eid = str(event.get("id", ""))
        if not eid:
            continue
        api_scores = _event_sets_scores(event)
        match_id = pid_to_mid.get(eid)
        if match_id is None:
            result.append(eid)
            continue
        db_scores = scores_by_match.get(match_id)
        if db_scores is None or db_scores != api_scores:
            result.append(eid)
    return result


async def _fetch_events_async(
    collector: BetsApiCollector,
    sid: int,
    include_ended: bool,
    mode: str,
    session_maker,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Логика запросов к API (без asyncio.run). Нужна для запуска в одном loop с normalize."""
    if mode == "live":
        # Список inplay (1 запрос), затем odds только по матчам с изменившимся счётом
        events = await collector.fetch(
            sport_id=sid,
            include_upcoming=False,
            include_inplay=True,
            include_ended=include_ended,
            fetch_event_view=False,
            fetch_event_odds=False,
            rate_limit_seconds=1.0,
        )
        inplay_ids = [str(e["id"]) for e in events if e.get("_source") == "inplay"]
        current_ids = set(inplay_ids)
        score_changed_ids = await _inplay_ids_with_score_change(events, session_maker)
        if score_changed_ids:
            events = await collector.fetch(
                sport_id=sid,
                include_upcoming=False,
                include_inplay=False,
                include_ended=False,
                fetch_event_view=False,
                fetch_event_odds=True,
                events_from_lists=events,
                event_ids_for_view=[],
                event_ids_for_odds=score_changed_ids,
                rate_limit_seconds=1.0,
            )
        return events, current_ids

    if mode == "live_odds":
        # Список inplay + event/odds по каждому — коэффициенты пишем в БД (формат v2 парсим в коллекторе)
        events = await collector.fetch(
            sport_id=sid,
            include_upcoming=False,
            include_inplay=True,
            include_ended=include_ended,
            fetch_event_view=False,
            fetch_event_odds=True,
            rate_limit_seconds=1.0,
        )
        inplay_ids = [str(e["id"]) for e in events if e.get("_source") == "inplay"]
        current_ids = set(inplay_ids)
        return events, current_ids

    # full: два этапа, линия реже
    events = await collector.fetch(
        sport_id=sid,
        include_upcoming=True,
        include_inplay=True,
        include_ended=include_ended,
        fetch_event_view=False,
        fetch_event_odds=False,
        rate_limit_seconds=1.0,
    )
    if not events:
        return [], set()

    upcoming_ids = [str(e["id"]) for e in events if e.get("_source") == "upcoming"]
    inplay_ids = [str(e["id"]) for e in events if e.get("_source") == "inplay"]
    current_ids = set(upcoming_ids) | set(inplay_ids)
    ids_for_view = upcoming_ids + inplay_ids
    upcoming_with_odds = await _upcoming_provider_ids_with_odds(upcoming_ids, session_maker)
    inplay_score_changed = await _inplay_ids_with_score_change(events, session_maker)
    ids_for_odds = inplay_score_changed + [eid for eid in upcoming_ids if eid not in upcoming_with_odds]

    events = await collector.fetch(
        sport_id=sid,
        include_upcoming=False,
        include_inplay=False,
        include_ended=False,
        fetch_event_view=True,
        fetch_event_odds=True,
        events_from_lists=events,
        event_ids_for_view=ids_for_view,
        event_ids_for_odds=ids_for_odds,
        rate_limit_seconds=1.0,
    )
    return events, current_ids


async def _fetch_and_normalize_betsapi_async(
    sport_id: int | None = None,
    mode: str = "full",
):
    """Fetch и normalize в одном event loop (избегаем RuntimeError в Celery)."""
    engine, session_maker = create_worker_engine_and_session()
    try:
        collector = BetsApiCollector()
        sid = sport_id if sport_id is not None else settings.betsapi_table_tennis_sport_id
        include_ended = False
        events, current_event_ids = await _fetch_events_async(collector, sid, include_ended, mode, session_maker)
        if not events:
            await _mark_stuck_scheduled_finished(session_maker)
            return []
        match_ids = await _normalize_betsapi_async(events, session_maker, current_event_ids=current_event_ids)
        # Матчи «в линии», у которых время начала давно прошло, но API не вернул inplay/ended — помечаем завершёнными
        stuck = await _mark_stuck_scheduled_finished(session_maker)
        if stuck:
            logger.info("Marked %s stuck scheduled match(es) as cancelled", stuck)
        return match_ids
    finally:
        await engine.dispose()


async def _normalize_betsapi_async(
    events: list[dict[str, Any]],
    session_maker,
    current_event_ids: set[str] | None = None,
) -> list:
    async with session_maker() as session:
        norm = Normalizer(session)
        return await norm.normalize_betsapi_response(events, current_event_ids=current_event_ids)


# Матчи в статусе «линия», у которых время начала прошло больше 5 минут и они не перешли в лайв — убираем из линии (статус «отменён»); если потом придут в лайве — нормалайзер сменит на live
STUCK_SCHEDULED_PAST_MINUTES = 5


async def _mark_stuck_scheduled_finished(session_maker, provider: str = "betsapi") -> int:
    """Помечает матчи SCHEDULED с start_time в прошлом (старт + 5 мин прошло) как CANCELLED. Возвращает количество обновлённых."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import update
    from app.models import Match, MatchStatus

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STUCK_SCHEDULED_PAST_MINUTES)
    async with session_maker() as session:
        r = await session.execute(
            update(Match)
            .where(
                Match.provider == provider,
                Match.status == MatchStatus.SCHEDULED.value,
                Match.start_time < cutoff,
            )
            .values(status=MatchStatus.CANCELLED.value)
        )
        await session.commit()
        return r.rowcount or 0


@celery_app.task(bind=True, name="app.worker.tasks.collect_betsapi.fetch_betsapi_table_tennis")
def fetch_betsapi_table_tennis_task(self, sport_id: int | None = None, mode: str = "full"):
    """mode: 'full' — линия+лайв (раз в 5–10 мин), 'live' — inplay + коэффициенты только при изменении счёта."""
    if not settings.betsapi_token:
        logger.warning("BETSAPI_TOKEN not set, skipping BetsAPI fetch")
        return {"collected": 0, "provider": "betsapi", "message": "token missing"}
    try:
        # Один event loop на всю задачу — иначе в Celery получаем "Future attached to a different loop"
        match_ids = asyncio.run(_fetch_and_normalize_betsapi_async(sport_id=sport_id, mode=mode))
        if not match_ids:
            return {"collected": 0, "provider": "betsapi", "message": "no events"}
        return {"collected": len(match_ids), "provider": "betsapi", "match_ids": [str(m) for m in match_ids]}
    except Exception as e:
        logger.exception("BetsAPI fetch failed: %s", e)
        raise


def _iter_days(day_from: str, day_to: str):
    """Генератор дней в формате YYYYMMDD от day_from до day_to включительно."""
    from datetime import datetime, timedelta, timezone
    start = datetime.strptime(day_from, "%Y%m%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(day_to, "%Y%m%d").replace(tzinfo=timezone.utc)
    if start > end:
        return
    d = start
    while d <= end:
        yield d.strftime("%Y%m%d")
        d += timedelta(days=1)


async def _run_load_betsapi_history_async(
    day_from: str,
    day_to: str,
    delay_seconds: float,
    sport_id: int,
    provider: str = "betsapi",
) -> dict[str, Any]:
    """Вся загрузка архива в одном event loop (один asyncio.run в задаче)."""
    import uuid
    from datetime import datetime, timezone
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert
    from app.models import BetsapiArchiveProgress

    engine, session_maker = create_worker_engine_and_session()
    try:
        collector = BetsApiCollector()
        total_events = 0
        total_created = 0
        days_processed = 0
        days_completed_new = 0

        async with session_maker() as session:
            r = await session.execute(
                select(
                    BetsapiArchiveProgress.day_yyyymmdd,
                    BetsapiArchiveProgress.last_processed_page,
                    BetsapiArchiveProgress.completed_at,
                ).where(
                    BetsapiArchiveProgress.provider == provider,
                    BetsapiArchiveProgress.day_yyyymmdd >= day_from,
                    BetsapiArchiveProgress.day_yyyymmdd <= day_to,
                )
            )
            rows = r.all()
        completed_days = {row[0] for row in rows if row[2] is not None}
        start_page_by_day = {row[0]: (row[1] or 0) + 1 for row in rows if row[2] is None}

        logger.info(
            "load_betsapi_history: completed_days=%s, start_page_by_day=%s, range %s..%s",
            len(completed_days), start_page_by_day, day_from, day_to,
        )

        for day in _iter_days(day_from, day_to):
            if day in completed_days:
                continue
            days_processed += 1
            page = start_page_by_day.get(day, 1)
            while True:
                events, _ = await collector.fetch_ended_by_day(
                    day_yyyymmdd=day,
                    page=page,
                    sport_id=sport_id,
                    rate_limit_seconds=0,
                )
                if not events:
                    async with session_maker() as session:
                        stmt = insert(BetsapiArchiveProgress).values(
                            id=uuid.uuid4(),
                            provider=provider,
                            day_yyyymmdd=day,
                            last_processed_page=page,
                            completed_at=datetime.now(timezone.utc),
                        ).on_conflict_do_update(
                            index_elements=["provider", "day_yyyymmdd"],
                            set_={"last_processed_page": page, "completed_at": datetime.now(timezone.utc)},
                        )
                        await session.execute(stmt)
                        await session.commit()
                    logger.info("load_betsapi_history: day %s completed (empty page %s)", day, page)
                    days_completed_new += 1
                    break
                total_events += len(events)
                match_ids = await _normalize_betsapi_async(events, session_maker, current_event_ids=None)
                total_created += len(match_ids)
                async with session_maker() as session:
                    stmt = insert(BetsapiArchiveProgress).values(
                        id=uuid.uuid4(),
                        provider=provider,
                        day_yyyymmdd=day,
                        last_processed_page=page,
                        completed_at=None,
                    ).on_conflict_do_update(
                        index_elements=["provider", "day_yyyymmdd"],
                        set_={"last_processed_page": page, "completed_at": None},
                    )
                    await session.execute(stmt)
                    await session.commit()
                logger.info("load_betsapi_history: day=%s page=%s events=%s match_ids=%s", day, page, len(events), len(match_ids))
                page += 1
                if delay_seconds > 0:
                    await asyncio.sleep(delay_seconds)
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)

        return {
            "ok": True,
            "day_from": day_from,
            "day_to": day_to,
            "days_processed": days_processed,
            "days_completed_new": days_completed_new,
            "total_events": total_events,
            "match_ids_processed": total_created,
        }
    finally:
        await engine.dispose()


@celery_app.task(bind=True, name="app.worker.tasks.collect_betsapi.load_betsapi_history")
def load_betsapi_history_task(
    self,
    day_from: str = "20160901",
    day_to: str | None = None,
    delay_seconds: float = 7.0,
    sport_id: int | None = None,
):
    """Загрузка архива завершённых матчей BetsAPI по дням (GET /v3/events/ended?day=YYYYMMDD&page=...).
    Раз в delay_seconds (по умолчанию 7 сек) один запрос. Матчи в Match + MatchScore + MatchResult.
    Если матч с таким provider_match_id уже есть в БД — пропускаем (без дубликатов).
    Дни, за которые все страницы обработаны (пустой ответ), записываются в betsapi_archive_progress."""
    from datetime import datetime, timezone
    logger.info(
        "load_betsapi_history started: day_from=%s day_to=%s delay_seconds=%s",
        day_from, day_to, delay_seconds,
    )
    if not settings.betsapi_token:
        logger.warning("load_betsapi_history: BETSAPI_TOKEN not set in worker environment")
        return {"ok": False, "error": "BETSAPI_TOKEN not set"}
    if day_to is None:
        day_to = datetime.now(timezone.utc).strftime("%Y%m%d")
    sid = sport_id if sport_id is not None else settings.betsapi_table_tennis_sport_id
    days_processed = 0
    total_events = 0
    try:
        result = asyncio.run(_run_load_betsapi_history_async(day_from, day_to, delay_seconds, sid))
        return result
    except Exception as e:
        logger.exception("load_betsapi_history failed: %s", e)
        return {"ok": False, "error": str(e), "days_processed": days_processed, "total_events": total_events}
