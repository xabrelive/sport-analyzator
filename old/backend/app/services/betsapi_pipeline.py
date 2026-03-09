"""
Единый пайплайн BetsAPI: получаем данные один раз и используем во всех сервисах.

Правила:
- Линия: upcoming → view → odds по матчам без line-коэффициентов. Кф пишем до перехода матча в лайв.
- Лайв: inplay → view (счёт/сеты/таймер). Кф запрашиваем один раз на старте матча и фиксируем (live_odds_fixed_at).
  После этого обновляем только ход матча (счёт, сеты), коэффициенты не трогаем.
- Пропал из лайва без результата: повтор через 15 мин, 1 ч, 2 ч (disappeared_retry).
- Архив: раз в 2 часа за текущий и предыдущий день.
- Лимит: 3600 запросов/час; распределяем между линией, лайвом, архивом и disappeared.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Match, MatchStatus
from app.models.match_result import MatchResult
from app.services.collectors.betsapi_collector import (
    BetsApiCollector,
    BetsApiRateLimitError,
    BetsapiEndedRequestError,
)

logger = logging.getLogger(__name__)

TABLE_TENNIS_SPORT_ID = 92
EVENT_VIEW_BATCH_SIZE = 10
RATE_LIMIT_SECONDS = 1.0


async def _sleep_rate_limit() -> None:
    await asyncio.sleep(max(0.5, RATE_LIMIT_SECONDS))


def _iter_days(day_from: str, day_to: str):
    start = datetime.strptime(day_from, "%Y%m%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(day_to, "%Y%m%d").replace(tzinfo=timezone.utc)
    if start > end:
        return
    d = start
    while d <= end:
        yield d.strftime("%Y%m%d")
        d += timedelta(days=1)


async def fetch_line_data(
    collector: BetsApiCollector,
    session_maker,
) -> tuple[list[dict[str, Any]], set[str]]:
    """
    Линия: upcoming → view → odds только для матчей, у которых ещё нет line-коэффициентов в БД.
    Возвращает (events, current_upcoming_ids).
    """
    from app.models import OddsSnapshot
    from sqlalchemy import or_

    sid = settings.betsapi_table_tennis_sport_id
    token = (settings.betsapi_token or "").strip()
    if not token:
        logger.warning("BetsAPI line: BETSAPI_TOKEN не задан — линия не запрашивается. Задайте BETSAPI_TOKEN в .env")
        return [], set()

    # 1) Список upcoming
    events = await collector.fetch(
        sport_id=sid,
        include_upcoming=True,
        include_inplay=False,
        include_ended=False,
        fetch_event_view=False,
        fetch_event_odds=False,
        rate_limit_seconds=RATE_LIMIT_SECONDS,
    )
    await _sleep_rate_limit()

    upcoming = [e for e in events if isinstance(e, dict) and e.get("_source") == "upcoming"]
    upcoming_ids = [str(e["id"]) for e in upcoming if e.get("id") is not None]
    if not upcoming_ids:
        logger.info("BetsAPI line: API вернул 0 предстоящих матчей (sport_id=%s)", sid)
        return events, set(upcoming_ids)

    # Кто уже имеет line-коэффициенты в БД
    async with session_maker() as session:
        stmt = (
            select(Match.provider_match_id)
            .where(
                Match.provider == "betsapi",
                Match.provider_match_id.in_(upcoming_ids),
            )
            .join(OddsSnapshot, OddsSnapshot.match_id == Match.id)
            .where(or_(OddsSnapshot.phase == "line", OddsSnapshot.phase.is_(None)))
            .distinct()
        )
        result = await session.execute(stmt)
        ids_with_line_odds = set(r[0] for r in result.all())

    for e in events:
        if e.get("_source") == "upcoming" and str(e.get("id", "")) in ids_with_line_odds:
            e["_line_odds_in_db"] = True

    ids_for_odds = [eid for eid in upcoming_ids if eid not in ids_with_line_odds]
    # Запрашиваем кф по всем матчам без кф, без жёсткого лимита — чтобы кф появлялись сразу и мы не пропускали матчи.
    # Внешний лимит (betsapi_line_max_odds_requests_per_run) только страхует от перегрузки при 500+ upcoming.
    max_odds = max(1, getattr(settings, "betsapi_line_max_odds_requests_per_run", 400))
    requested_count = len(ids_for_odds)
    ids_for_odds = ids_for_odds[:max_odds]
    if ids_for_odds:
        logger.info(
            "BetsAPI line: requesting odds for %s matches (already have: %s, upcoming total: %s%s)",
            len(ids_for_odds),
            len(ids_with_line_odds),
            len(upcoming_ids),
            f", capped from {requested_count}" if requested_count > max_odds else "",
        )

    # 2) View по всем upcoming
    if upcoming_ids:
        events = await collector.fetch(
            sport_id=sid,
            include_upcoming=False,
            include_inplay=False,
            include_ended=False,
            fetch_event_view=True,
            fetch_event_odds=False,
            events_from_lists=events,
            event_ids_for_view=upcoming_ids,
            event_ids_for_odds=[],
            rate_limit_seconds=RATE_LIMIT_SECONDS,
        )
        await _sleep_rate_limit()

    # 3) Odds только по матчам без line-коэффициентов
    if ids_for_odds:
        events = await collector.fetch(
            sport_id=sid,
            include_upcoming=False,
            include_inplay=False,
            include_ended=False,
            fetch_event_view=False,
            fetch_event_odds=True,
            events_from_lists=events,
            event_ids_for_view=[],
            event_ids_for_odds=ids_for_odds,
            rate_limit_seconds=RATE_LIMIT_SECONDS,
        )

    return events, set(upcoming_ids)


async def fetch_live_data(
    collector: BetsApiCollector,
    session_maker,
) -> tuple[list[dict[str, Any]], set[str]]:
    """
    Лайв: inplay → view (счёт, сеты, таймер) по всем inplay.
    Odds только по матчам, у которых ещё не зафиксированы кф на старте (нет live_odds_fixed_at).
    Возвращает (events, current_inplay_ids).
    """
    sid = settings.betsapi_table_tennis_sport_id
    if not settings.betsapi_token:
        return [], set()

    # 1) Список inplay
    events = await collector.fetch(
        sport_id=sid,
        include_upcoming=False,
        include_inplay=True,
        include_ended=False,
        fetch_event_view=False,
        fetch_event_odds=False,
        rate_limit_seconds=RATE_LIMIT_SECONDS,
    )
    await _sleep_rate_limit()

    inplay = [e for e in events if isinstance(e, dict) and e.get("_source") == "inplay"]
    inplay_ids = [str(e["id"]) for e in inplay if e.get("id") is not None]
    if not inplay_ids:
        return events, set(inplay_ids)

    # Кто уже имеет зафиксированные лайв-кф (на старте матча)
    async with session_maker() as session:
        stmt = select(Match.provider_match_id).where(
            Match.provider == "betsapi",
            Match.provider_match_id.in_(inplay_ids),
            Match.live_odds_fixed_at.isnot(None),
        )
        result = await session.execute(stmt)
        ids_odds_fixed = set(r[0] for r in result.all())

    ids_for_odds = [eid for eid in inplay_ids if eid not in ids_odds_fixed]

    # 2) View по всем inplay (счёт, сеты, таймер)
    events = await collector.fetch(
        sport_id=sid,
        include_upcoming=False,
        include_inplay=False,
        include_ended=False,
        fetch_event_view=True,
        fetch_event_odds=bool(ids_for_odds),
        events_from_lists=events,
        event_ids_for_view=inplay_ids,
        event_ids_for_odds=ids_for_odds,
        rate_limit_seconds=RATE_LIMIT_SECONDS,
    )

    return events, set(inplay_ids)


async def fetch_disappeared_retry(
    collector: BetsApiCollector,
    session_maker,
    batch_size: int = 10,
) -> tuple[list[dict[str, Any]], int]:
    """
    Матчи в статусе LIVE, которых нет в текущем inplay и нет результата.
    Повторные запросы view: 1-й раз через 15 мин, 2-й через 1 ч, 3-й через 2 ч.
    Возвращает (events для нормализации, количество обработанных).
    """
    now = datetime.now(timezone.utc)
    delays = getattr(settings, "disappeared_retry_delays_seconds", (15 * 60, 3600, 7200))
    max_attempts = getattr(settings, "disappeared_retry_max_attempts", 3)

    async with session_maker() as session:
        # Матчи LIVE без результата, по которым пора повторить запрос
        stmt = (
            select(Match)
            .where(
                Match.provider == "betsapi",
                Match.status == MatchStatus.LIVE.value,
                Match.disappeared_retry_count < max_attempts,
            )
            .outerjoin(MatchResult, Match.id == MatchResult.match_id)
            .where(MatchResult.id.is_(None))
        )
        # next_disappeared_retry_at is null (ещё не ставили) OR next_disappeared_retry_at <= now
        from sqlalchemy import or_
        stmt = stmt.where(
            or_(
                Match.next_disappeared_retry_at.is_(None),
                Match.next_disappeared_retry_at <= now,
            )
        )
        stmt = stmt.order_by(Match.next_disappeared_retry_at.asc().nullsfirst()).limit(batch_size)
        result = await session.execute(stmt)
        candidates = result.scalars().unique().all()

    if not candidates:
        return [], 0

    events_out: list[dict[str, Any]] = []
    sid = settings.betsapi_table_tennis_sport_id

    for match in candidates:
        pid = match.provider_match_id
        try:
            stubs = [{"id": pid, "_source": "inplay"}]
            events = await collector.fetch(
                sport_id=sid,
                include_upcoming=False,
                include_inplay=False,
                include_ended=False,
                fetch_event_view=True,
                fetch_event_odds=False,
                events_from_lists=stubs,
                event_ids_for_view=[pid],
                event_ids_for_odds=[],
                rate_limit_seconds=RATE_LIMIT_SECONDS,
            )
            await _sleep_rate_limit()
            if events:
                events_out.extend(events)

            # Обновить следующую попытку
            attempt = match.disappeared_retry_count + 1
            delay_sec = delays[attempt - 1] if attempt <= len(delays) else delays[-1]
            next_at = now + timedelta(seconds=delay_sec)
            async with session_maker() as session:
                await session.execute(
                    update(Match)
                    .where(Match.id == match.id)
                    .values(
                        disappeared_retry_count=attempt,
                        next_disappeared_retry_at=next_at,
                    )
                )
                await session.commit()
        except (BetsApiRateLimitError, BetsapiEndedRequestError, Exception) as e:
            logger.warning("Disappeared retry fetch failed for %s: %s", pid, e)
            # Всё равно увеличиваем счётчик и ставим следующую попытку
            attempt = match.disappeared_retry_count + 1
            delay_sec = delays[attempt - 1] if attempt <= len(delays) else delays[-1]
            next_at = now + timedelta(seconds=delay_sec)
            async with session_maker() as session:
                await session.execute(
                    update(Match)
                    .where(Match.id == match.id)
                    .values(
                        disappeared_retry_count=attempt,
                        next_disappeared_retry_at=next_at,
                    )
                )
                await session.commit()

    return events_out, len(candidates)


async def mark_disappeared_matches(
    session: AsyncSession,
    current_inplay_ids: set[str],
) -> int:
    """
    Матчи LIVE, которых нет в current_inplay_ids и нет результата:
    выставляем next_disappeared_retry_at (первая попытка через 15 мин), если ещё не выставлено.
    Возвращает количество обновлённых.
    """
    from sqlalchemy import exists

    if not current_inplay_ids:
        return 0

    now = datetime.now(timezone.utc)
    first_delay = 15 * 60  # 15 мин
    next_at = now + timedelta(seconds=first_delay)

    has_no_result = ~exists(
        select(MatchResult.match_id).where(MatchResult.match_id == Match.id)
    )
    stmt = (
        update(Match)
        .where(
            Match.provider == "betsapi",
            Match.status == MatchStatus.LIVE.value,
            ~Match.provider_match_id.in_(current_inplay_ids),
            Match.next_disappeared_retry_at.is_(None),
            Match.disappeared_retry_count == 0,
            has_no_result,
        )
        .values(next_disappeared_retry_at=next_at)
    )
    result = await session.execute(stmt)
    return result.rowcount or 0
