"""Fetch table tennis events and odds from BetsAPI and save to DB.

Единый пайплайн:
- line: upcoming → view → odds только где ещё нет line-кф. Кф пишем до перехода в лайв.
- live: inplay → view (счёт/сеты). Кф один раз на старте матча, дальше не обновляем.
- disappeared: матчи LIVE без результата, пропавшие из inplay — повтор через 15 мин, 1 ч, 2 ч.
- archive: раз в 2 ч за текущий и предыдущий день.

Рекомендации (расчёт и сохранение):
- После каждого цикла line и live вызывается _precompute_match_recommendations_async(match_ids).
- Дополнительно задача precompute_active_recommendations по расписанию добивает матчи без рекомендации (линия/лайв).
- Сохраняем одну запись в match_recommendations на матч, не обновляем. Таблица линии/лайва и статистика читают только из неё.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from redis.asyncio import from_url as redis_from_url
from redis import Redis as SyncRedis
from sqlalchemy import and_, or_, select, text, update

from app.config import settings
from app.db.session import create_worker_engine_and_session
from app.models import Match, MatchScore, MatchStatus, OddsSnapshot
from app.models.match_result import MatchResult
from app.models.match_recommendation import MatchRecommendation
from app.services.collectors.betsapi_collector import BetsApiCollector, BetsApiRateLimitError, BetsapiEndedRequestError
from app.services.betsapi_pipeline import (
    fetch_line_data,
    fetch_live_data,
    fetch_disappeared_retry,
    mark_disappeared_matches,
)
from app.services.normalizer import Normalizer
from app.services.player_stats_service import compute_player_stats, get_stats_for_recommendation
from app.services.analytics_service import first_recommendation_text_and_confidence
from app.worker.celery_app import celery_app
from app.ws.events import publish_matches_updated

logger = logging.getLogger(__name__)

# Минимальный коэффициент для сохранения рекомендации в таблицу линии/лайва.
# По требованию оставляем исходы только с кф не ниже 1.4.
MIN_RECOMMENDATION_ODDS = 1.4

MAX_ENDED_REQUEST_RETRIES = 3
ENDED_RETRY_SLEEP_RATE_LIMIT = 60
ENDED_RETRY_SLEEP_OTHER = 15


def _recommendation_side(text: str) -> str | None:
    if not text:
        return None
    t = text.lower()
    if "п1" in t:
        return "home"
    if "п2" in t:
        return "away"
    return None


async def _get_recommendation_stats(session, match) -> tuple:
    """Обёртка над get_stats_for_recommendation с настройками из config."""
    league_id = getattr(match, "league_id", None)
    return await get_stats_for_recommendation(
        session,
        match.home_player_id,
        match.away_player_id,
        league_id,
        lookback_days=settings.recommendation_lookback_days,
        prefer_recent_days=getattr(settings, "recommendation_prefer_recent_days", None),
        min_matches_in_league=getattr(settings, "recommendation_min_matches_in_league", 3),
    )


async def _precompute_match_recommendations_async(
    session_maker,
    match_ids: list,
) -> int:
    """
    Сохраняет рекомендации в БД (одна запись на матч, не обновляется).
    Вызывается автоматически после каждого цикла линии и лайва, а также задачей precompute_active_recommendations.
    Для матчей с коэффициентами: сохраняем, если кф >= MIN_RECOMMENDATION_ODDS; иначе не сохраняем.
    Без кф сохраняем с odds_at_recommendation=None. Таблица линии/лайва и статистика читают только из этой таблицы.
    """
    if not match_ids:
        return 0
    created = 0
    async with session_maker() as session:
        # Уже рассчитанные матчи не пересчитываем: только добавляем новые записи, никогда не обновляем.
        existing_q = select(MatchRecommendation.match_id).where(MatchRecommendation.match_id.in_(match_ids))
        existing_rows = (await session.execute(existing_q)).all()
        existing_ids = {row[0] for row in existing_rows}

        matches_q = select(Match).where(Match.id.in_(match_ids))
        matches = (await session.execute(matches_q)).scalars().all()
        for match in matches:
            if match.id in existing_ids:
                continue
            if match.status not in ("scheduled", "live"):
                continue
            if not match.home_player_id or not match.away_player_id:
                continue
            stats_home, stats_away = await _get_recommendation_stats(session, match)
            if not stats_home or not stats_away:
                continue

            # Тонкая настройка алгоритма для лиг с повышенной волатильностью результатов.
            # По данным статистики сейчас в Czech Liga Pro и Setka Cup высокий % неугаданных,
            # поэтому:
            # - повышаем порог уверенности для победы в матче;
            # - требуем больше матчей в истории для рекомендаций по матчу;
            # - приоритетно используем прогнозы по сетам, если они достаточно уверенные.
            league_name = (getattr(getattr(match, "league", None), "name", None) or "").lower()
            is_high_variance_league = any(
                key in league_name for key in ("czech liga pro", "setka cup")
            )

            base_kwargs: dict = {}
            if is_high_variance_league:
                base_kwargs = {
                    "min_matches": 5,
                    "threshold": 0.76,
                    "threshold_match": 0.82,
                    "min_matches_for_match": 10,
                }

            rec, confidence_pct = first_recommendation_text_and_confidence(
                stats_home,
                stats_away,
                **base_kwargs,
            )

            # Для проблемных лиг дополнительно пробуем найти более надёжный прогноз по сетам,
            # если изначально выбрана «победа в матче».
            if rec and is_high_variance_league and "победа в матче" in rec.lower():
                rec_sets, conf_sets = first_recommendation_text_and_confidence(
                    stats_home,
                    stats_away,
                    min_matches=base_kwargs.get("min_matches", 3),
                    threshold=base_kwargs.get("threshold", None),
                    # Практически выключаем рекомендации по матчу: оставляем только сетовые.
                    threshold_match=1.0,
                    min_matches_for_match=9999,
                )
                if rec_sets:
                    rec, confidence_pct = rec_sets, conf_sets

            if not rec:
                continue

            odds_val: float | None = None
            side = _recommendation_side(rec)
            if side is not None:
                odds_q = (
                    select(OddsSnapshot)
                    .where(
                        OddsSnapshot.match_id == match.id,
                        OddsSnapshot.market.in_(["winner", "92_1", "win"]),
                    )
                    .order_by(
                        OddsSnapshot.snapshot_time.asc().nullslast(),
                        OddsSnapshot.timestamp.asc().nullslast(),
                    )
                    .limit(50)
                )
                snaps = (await session.execute(odds_q)).scalars().all()
                for s in snaps:
                    sel = (s.selection or "").lower()
                    if side == "home" and sel in ("home", "1"):
                        odds_val = float(s.odds)
                        break
                    if side == "away" and sel in ("away", "2"):
                        odds_val = float(s.odds)
                        break

            # Если есть известный коэффициент и он ниже минимального порога — такую рекомендацию пропускаем.
            if odds_val is not None and odds_val < MIN_RECOMMENDATION_ODDS:
                continue

            session.add(
                MatchRecommendation(
                    match_id=match.id,
                    recommendation_text=rec,
                    odds_at_recommendation=odds_val,
                    confidence_pct=confidence_pct,
                )
            )
            created += 1

        if created:
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    return created


async def _run_recommendations_backfill_async(
    active_limit: int,
) -> dict[str, int]:
    """Добивает отсутствующие рекомендации только по матчам в линии или лайве (не по завершённым)."""
    engine, session_maker = create_worker_engine_and_session()
    try:
        async with session_maker() as session:
            q = (
                select(Match.id)
                .where(Match.status.in_(["scheduled", "live"]))
                .order_by(Match.updated_at.desc())
                .limit(max(1, active_limit))
            )
            candidate_ids = [r[0] for r in (await session.execute(q)).all()]
            if not candidate_ids:
                return {"candidates": 0, "missing_before": 0, "created": 0}
            existing_q = select(MatchRecommendation.match_id).where(MatchRecommendation.match_id.in_(candidate_ids))
            existing_rows = (await session.execute(existing_q)).all()
            existing_ids = {row[0] for row in existing_rows}

        missing = [mid for mid in candidate_ids if mid not in existing_ids]
        created = await _precompute_match_recommendations_async(session_maker, missing)
        return {"candidates": len(candidate_ids), "missing_before": len(missing), "created": created}
    finally:
        await engine.dispose()


async def _wait_for_normalize_queue_capacity(
    redis_client,
    *,
    queue_name: str,
    max_depth: int,
    sleep_seconds: float,
) -> None:
    """Backpressure для истории: ждём, пока очередь normalize разгрузится."""
    if max_depth <= 0:
        return
    checks = 0
    safe_sleep = max(0.1, sleep_seconds)
    while True:
        depth = await redis_client.llen(queue_name)
        if depth < max_depth:
            return
        checks += 1
        if checks == 1 or checks % 10 == 0:
            logger.info(
                "History backpressure: queue=%s depth=%s limit=%s, waiting %.1fs",
                queue_name,
                depth,
                max_depth,
                safe_sleep,
            )
        await asyncio.sleep(safe_sleep)


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


async def _inplay_provider_ids_odds_fixed(
    provider_match_ids: list[str],
    session_maker,
) -> set[str]:
    """Возвращает provider_match_id лайв-матчей, у которых уже зафиксированы кф на старте (live_odds_fixed_at). По ним больше не запрашиваем odds."""
    if not provider_match_ids:
        return set()
    async with session_maker() as session:
        stmt = select(Match.provider_match_id).where(
            Match.provider == "betsapi",
            Match.provider_match_id.in_(provider_match_ids),
            Match.live_odds_fixed_at.isnot(None),
        )
        result = await session.execute(stmt)
        return set(r[0] for r in result.all())


def _count_completed_sets(
    scores: list[tuple[int, int]],
    points_per_set: int = 11,
    win_by: int = 2,
) -> int:
    """Число завершённых сетов по списку (home_score, away_score)."""
    n = 0
    for h, a in scores:
        if max(h, a) >= points_per_set and abs(h - a) >= win_by:
            n += 1
    return n


async def _inplay_ids_where_set_just_ended(
    events: list[dict[str, Any]],
    session_maker,
) -> list[str]:
    """Возвращает provider_match_id лайв-матчей, у которых только что завершился сет (или матч новый).
    Сейчас не используется: кф по лайву запрашиваем один раз при появлении в inplay (live_odds_fixed_at)."""
    inplay = [e for e in events if isinstance(e, dict) and e.get("_source") == "inplay"]
    if not inplay:
        return []
    inplay_ids = [str(e["id"]) for e in inplay if e.get("id") is not None]
    if not inplay_ids:
        return []

    async with session_maker() as session:
        stmt = select(Match.provider_match_id, Match.id).where(
            Match.provider == "betsapi",
            Match.provider_match_id.in_(inplay_ids),
        )
        rows = (await session.execute(stmt)).all()
        pid_to_mid = {str(pid): mid for pid, mid in rows}
        match_ids = list(set(pid_to_mid.values()))

        if not match_ids:
            return inplay_ids  # все матчи новые — запрашиваем odds по всем

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
        if db_scores is None:
            result.append(eid)
            continue
        # Запрашиваем odds только когда завершился ещё один сет.
        api_completed = _count_completed_sets(api_scores)
        db_completed = _count_completed_sets(db_scores)
        if api_completed > db_completed:
            result.append(eid)
    return result


async def _fetch_events_async(
    collector: BetsApiCollector,
    sid: int,
    include_ended: bool,
    mode: str,
    session_maker,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Использует единый пайплайн: данные получаем один раз и передаём в нормалайзер."""
    if mode == "line":
        events, current_ids = await fetch_line_data(collector, session_maker)
        return events, current_ids

    if mode == "live":
        events, current_ids = await fetch_live_data(collector, session_maker)
        return events, current_ids

    # full: ручной режим — линия + лайв в одном цикле (для диагностики). Кф по лайву — только если ещё не зафиксированы (нет live_odds_fixed_at).
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
    inplay_odds_fixed = await _inplay_provider_ids_odds_fixed(inplay_ids, session_maker)
    # По лайву запрашиваем odds только по матчам без live_odds_fixed_at (один раз на старт)
    ids_for_odds = [eid for eid in inplay_ids if eid not in inplay_odds_fixed] + [
        eid for eid in upcoming_ids if eid not in upcoming_with_odds
    ]
    for e in events:
        if e.get("_source") == "upcoming" and str(e.get("id")) in upcoming_with_odds:
            e["_line_odds_in_db"] = True
    events = await collector.fetch(
        sport_id=sid,
        include_upcoming=False,
        include_inplay=False,
        include_ended=False,
        fetch_event_view=True,
        fetch_event_odds=True,
        events_from_lists=events,
        event_ids_for_view=ids_for_view,
        event_ids_for_odds=ids_for_odds[:50],
        rate_limit_seconds=1.0,
    )
    return events, current_ids


async def _fetch_and_normalize_betsapi_async(
    sport_id: int | None = None,
    mode: str = "full",
) -> tuple[list, bool, bool]:
    """Fetch + normalize в одном event loop.

    Возвращает (match_ids, skipped, rate_limited).
    rate_limited=True только при 429 для mode=line (лимит в час); следующий тик beat запросит линию после паузы."""
    engine, session_maker = create_worker_engine_and_session()
    events: list = []
    current_event_ids: set = set()
    try:
        # Для live — без advisory‑lock
        if mode == "live":
            collector = BetsApiCollector()
            sid = sport_id if sport_id is not None else settings.betsapi_table_tennis_sport_id
            include_ended = False
            try:
                events, current_event_ids = await _fetch_events_async(
                    collector, sid, include_ended, mode, session_maker
                )
            except BetsApiRateLimitError as e:
                logger.warning("BetsAPI live rate-limited: %s", e)
                return ([], False, False)
            if not events:
                await _cleanup_betsapi_statuses_async(session_maker)
                logger.info("BetsAPI live: upstream returned 0 inplay events")
                return ([], False, False)

            match_ids = await _normalize_betsapi_async(
                events,
                session_maker,
                current_event_ids=current_event_ids,
            )
            # Убедимся, что все текущие inplay‑матчи в БД имеют статус LIVE,
            # а не застряли в scheduled/pending_odds.
            try:
                forced_live = await _ensure_inplay_marked_live(session_maker, current_event_ids)
                if forced_live:
                    logger.info("Forced LIVE status for %s inplay match(es) from BetsAPI", forced_live)
            except Exception as e:
                logger.warning("ensure_inplay_marked_live failed: %s", e)
            async with session_maker() as session:
                marked = await mark_disappeared_matches(session, current_event_ids)
                await session.commit()
                if marked:
                    logger.info("Marked %s disappeared live match(es) for retry", marked)
            if match_ids:
                try:
                    created_recs = await _precompute_match_recommendations_async(session_maker, match_ids)
                    if created_recs:
                        logger.info("Precomputed and stored %s recommendation(s)", created_recs)
                except Exception as e:
                    logger.warning("Failed to precompute match recommendations: %s", e)
                await publish_matches_updated([str(mid) for mid in match_ids], mode=mode)

            stuck, stale_live = await _cleanup_betsapi_statuses_async(session_maker)
            if stuck:
                logger.info("Marked %s stuck scheduled match(es) as cancelled", stuck)
            if stale_live:
                logger.info("Marked %s stale live match(es) as finished", stale_live)
            return (match_ids, False, False)

        # Упрощённый режим линии (отключён): раньше брал только список upcoming без odds.
        # Сейчас всегда используем единый пайплайн ниже (fetch_line_data) с view+odds.
        if False and mode == "line":
            lock_key = 920002
            async with engine.begin() as lock_conn:
                lock_ok = (
                    await lock_conn.execute(
                        text("SELECT pg_try_advisory_xact_lock(:key)"),
                        {"key": lock_key},
                    )
                ).scalar()
                if not lock_ok:
                    logger.info("Skip BetsAPI line fetch: previous run still in progress")
                    return ([], True, False)

                collector = BetsApiCollector()
                sid = sport_id if sport_id is not None else settings.betsapi_table_tennis_sport_id
                try:
                    events = await collector.fetch(
                        sport_id=sid,
                        include_upcoming=True,
                        include_inplay=False,
                        include_ended=False,
                        fetch_event_view=False,
                        fetch_event_odds=False,
                        rate_limit_seconds=1.0,
                    )
                except BetsApiRateLimitError as e:
                    logger.warning("BetsAPI line rate-limited (simple): %s", e)
                    try:
                        r = redis_from_url(settings.redis_url, decode_responses=True)
                        await r.set(REDIS_KEY_LINE_RATE_LIMITED, "1", ex=LINE_RATE_LIMIT_COOLDOWN_SECONDS)
                        await r.aclose()
                        logger.info(
                            "BetsAPI line (simple): 429 cooldown set %ss. Line will resume at next schedule after cooldown.",
                            LINE_RATE_LIMIT_COOLDOWN_SECONDS,
                        )
                    except Exception as re:
                        logger.warning("Failed to set simple line rate limit cooldown in Redis: %s", re)
                    return ([], False, True)

            # Блокировка снята здесь
            if not events:
                logger.info("BetsAPI line (simple): upstream returned 0 upcoming events")
                await _clear_line_rate_limit_cooldown()
                return ([], False, False)

            logger.info("BetsAPI line (simple): got %s upcoming events, normalizing", len(events))
            # current_event_ids не используем: линия не помечает LIVE-матчи как пропавшие.
            match_ids = await _normalize_betsapi_async(
                events,
                session_maker,
                current_event_ids=None,
            )
            if match_ids:
                # Рекомендации могут быть тяжёлыми, поэтому считаем их best-effort: не даём им уронить линию.
                try:
                    created_recs = await _precompute_match_recommendations_async(session_maker, match_ids)
                    if created_recs:
                        logger.info("Line (simple): precomputed and stored %s recommendation(s)", created_recs)
                except Exception as e:
                    logger.warning("Line (simple): failed to precompute match recommendations: %s", e)
                await publish_matches_updated([str(mid) for mid in match_ids], mode=mode)

            await _clear_line_rate_limit_cooldown()
            return (match_ids, False, False)

        # Общий режим (line/full) без advisory‑lock: единый пайплайн с view+odds.
        collector = BetsApiCollector()
        sid = sport_id if sport_id is not None else settings.betsapi_table_tennis_sport_id
        include_ended = False
        try:
            events, current_event_ids = await _fetch_events_async(
                collector, sid, include_ended, mode, session_maker
            )
        except BetsApiRateLimitError as e:
            logger.warning("BetsAPI %s rate-limited: %s", mode, e)
            # Для линии ставим паузу в Redis; следующий тик beat после паузы снова запросит линию
            if mode == "line":
                try:
                    r = redis_from_url(settings.redis_url, decode_responses=True)
                    await r.set(REDIS_KEY_LINE_RATE_LIMITED, "1", ex=LINE_RATE_LIMIT_COOLDOWN_SECONDS)
                    await r.aclose()
                    logger.info(
                        "BetsAPI line: 429 cooldown set %ss. Line will resume at next schedule after cooldown.",
                        LINE_RATE_LIMIT_COOLDOWN_SECONDS,
                    )
                except Exception as re:
                    logger.warning("Failed to set line rate limit cooldown in Redis: %s", re)
            return ([], False, mode == "line")

        if not events:
            await _cleanup_betsapi_statuses_async(session_maker)
            if mode == "line":
                logger.info("BetsAPI line: upstream returned 0 upcoming events")
                await _clear_line_rate_limit_cooldown()
            return ([], False, False)

        if mode == "line":
            logger.info("BetsAPI line: got %s events, normalizing", len(events))
        # В режиме line current_event_ids = id из линии (upcoming); для логики «пропал из inplay»
        # передаём только в live. В line не помечаем LIVE-матчи как пропавшие.
        normalize_current_ids = None if mode == "line" else current_event_ids
        match_ids = await _normalize_betsapi_async(
            events,
            session_maker,
            current_event_ids=normalize_current_ids,
        )
        if match_ids:
            try:
                created_recs = await _precompute_match_recommendations_async(session_maker, match_ids)
                if created_recs:
                    logger.info("Precomputed and stored %s recommendation(s)", created_recs)
            except Exception as e:
                logger.warning("Failed to precompute match recommendations: %s", e)
        if match_ids:
            await publish_matches_updated([str(mid) for mid in match_ids], mode=mode)
        stuck, stale_live = await _cleanup_betsapi_statuses_async(session_maker)
        if stuck:
            logger.info("Marked %s stuck scheduled match(es) as cancelled", stuck)
        if stale_live:
            logger.info("Marked %s stale live match(es) as finished", stale_live)
        if mode == "line":
            await _clear_line_rate_limit_cooldown()
        return (match_ids, False, False)
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


async def _run_line_odds_backfill_async(batch_size: int = 50) -> dict[str, Any]:
    """Догружает коэффициенты линии по матчам, у которых ещё нет line OddsSnapshot.

    Выбирает матчи BetsAPI в статусе scheduled/pending_odds без снимков с phase in ('line', NULL),
    запрашивает view + odds, нормализует и сохраняет. Можно вызывать по расписанию или после run_line_once.
    batch_size берётся из settings.line_odds_backfill_batch_size (по умолчанию 100).
    """
    from sqlalchemy import exists

    engine, session_maker = create_worker_engine_and_session()
    try:
        has_line_odds = (
            select(1)
            .select_from(OddsSnapshot)
            .where(
                OddsSnapshot.match_id == Match.id,
                or_(OddsSnapshot.phase == "line", OddsSnapshot.phase.is_(None)),
            )
        )
        q = (
            select(Match.id, Match.provider_match_id)
            .where(
                Match.provider == "betsapi",
                Match.status.in_([MatchStatus.SCHEDULED.value, MatchStatus.PENDING_ODDS.value]),
                ~exists(has_line_odds),
            )
            .order_by(Match.start_time.asc())
            .limit(max(1, batch_size))
        )
        async with session_maker() as session:
            rows = (await session.execute(q)).all()
        if not rows:
            return {"processed": 0, "normalized": 0, "match_ids": []}

        provider_match_ids = [str(r[1]) for r in rows]
        stubs = [{"id": pid, "_source": "upcoming"} for pid in provider_match_ids]
        collector = BetsApiCollector()
        sid = settings.betsapi_table_tennis_sport_id
        events = await collector.fetch(
            sport_id=sid,
            include_upcoming=False,
            include_inplay=False,
            include_ended=False,
            fetch_event_view=True,
            fetch_event_odds=True,
            events_from_lists=stubs,
            event_ids_for_view=provider_match_ids,
            event_ids_for_odds=provider_match_ids,
            rate_limit_seconds=1.0,
        )
        if not events:
            return {"processed": len(provider_match_ids), "normalized": 0, "match_ids": []}
        match_ids = await _normalize_betsapi_async(events, session_maker, current_event_ids=None)
        if match_ids:
            try:
                created_recs = await _precompute_match_recommendations_async(session_maker, match_ids)
                if created_recs:
                    logger.info("Line odds backfill: precomputed %s recommendation(s)", created_recs)
            except Exception as e:
                logger.warning("Line odds backfill: precompute recommendations failed: %s", e)
            await publish_matches_updated([str(mid) for mid in match_ids], mode="line")
        return {
            "processed": len(provider_match_ids),
            "normalized": len(match_ids),
            "match_ids": [str(m) for m in match_ids],
        }
    finally:
        await engine.dispose()


# Матч в линии переводим в cancelled только если:
# 1) его start_time давно в прошлом;
# 2) и по нему давно нет обновлений.
# Это защищает от кейса, когда провайдер отдаёт "старое" время старта,
# но продолжает обновлять карточку матча в реальном времени.
STUCK_SCHEDULED_PAST_MINUTES = 5
STUCK_SCHEDULED_NO_UPDATES_MINUTES = 20
STALE_LIVE_PAST_MINUTES = 15


async def _mark_stuck_scheduled_finished(session_maker, provider: str = "betsapi") -> int:
    """Помечает матчи SCHEDULED с start_time в прошлом (старт + 5 мин прошло) как CANCELLED. Возвращает количество обновлённых."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import update
    from app.models import Match, MatchStatus

    now_utc = datetime.now(timezone.utc)
    start_cutoff = now_utc - timedelta(minutes=STUCK_SCHEDULED_PAST_MINUTES)
    updates_cutoff = now_utc - timedelta(minutes=STUCK_SCHEDULED_NO_UPDATES_MINUTES)
    async with session_maker() as session:
        r = await session.execute(
            update(Match)
            .where(
                Match.provider == provider,
                Match.status == MatchStatus.SCHEDULED.value,
                Match.start_time < start_cutoff,
                Match.updated_at < updates_cutoff,
            )
            .values(status=MatchStatus.CANCELLED.value)
        )
        await session.commit()
        return r.rowcount or 0


async def _mark_stale_live_finished(session_maker, provider: str = "betsapi") -> int:
    """Если live-матч давно не обновлялся, переводим его в FINISHED.

    Это защищает выдачу /live от «вечных» матчей при сбоях/устаревших данных провайдера.
    """
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import update
    from app.models import Match, MatchStatus

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_LIVE_PAST_MINUTES)
    async with session_maker() as session:
        r = await session.execute(
            update(Match)
            .where(
                Match.provider == provider,
                Match.status == MatchStatus.LIVE.value,
                Match.updated_at < cutoff,
            )
            .values(status=MatchStatus.FINISHED.value)
        )
        await session.commit()
        return r.rowcount or 0


async def _ensure_inplay_marked_live(session_maker, current_event_ids: set[str], provider: str = "betsapi") -> int:
    """
    Гарантирует, что все текущие inplay‑матчи из BetsAPI помечены в БД как LIVE.
    Если матч остался в статусе scheduled/pending_odds, но есть в списке inplay,
    переводим его в LIVE, чтобы лайв‑страница отображала актуальные матчи.
    """
    if not current_event_ids:
        return 0
    from sqlalchemy import update
    from app.models import Match, MatchStatus

    async with session_maker() as session:
        r = await session.execute(
            update(Match)
            .where(
                Match.provider == provider,
                Match.provider_match_id.in_(list(current_event_ids)),
                Match.status.in_([MatchStatus.SCHEDULED.value, MatchStatus.PENDING_ODDS.value]),
            )
            .values(status=MatchStatus.LIVE.value)
        )
        await session.commit()
        return r.rowcount or 0


async def _cleanup_betsapi_statuses_async(session_maker) -> tuple[int, int]:
    """Подчистка статусов в одном event loop (без loop-mismatch)."""
    stuck = await _mark_stuck_scheduled_finished(session_maker)
    stale_live = await _mark_stale_live_finished(session_maker)
    return stuck, stale_live


# Отложенный повтор при пропуске line/live из‑за блокировки (сек)
LINE_SKIP_RETRY_COUNTDOWN = 90
LIVE_SKIP_RETRY_COUNTDOWN = 30
# При 429 (лимит в час): пауза перед следующими запросами линии (55 мин), затем beat снова запросит линию
LINE_RATE_LIMIT_COOLDOWN_SECONDS = 3300
REDIS_KEY_LINE_RATE_LIMITED = "betsapi:line_rate_limited"


async def _clear_line_rate_limit_cooldown() -> None:
    """Сбрасывает паузу линии после 429, чтобы следующие тики снова запрашивали линию."""
    try:
        r = redis_from_url(settings.redis_url, decode_responses=True)
        await r.delete(REDIS_KEY_LINE_RATE_LIMITED)
        await r.aclose()
    except Exception as e:
        logger.debug("Clear line cooldown: %s", e)


@celery_app.task(bind=True, name="app.worker.tasks.collect_betsapi.fetch_betsapi_table_tennis")
def fetch_betsapi_table_tennis_task(self, sport_id: int | None = None, mode: str = "full"):
    """mode:
    - line: upcoming -> view -> odds (line)
    - live: inplay -> odds only on score change
    - full: service mode (upcoming+inplay)
    """
    if not settings.betsapi_token:
        logger.warning("BETSAPI_TOKEN not set, skipping BetsAPI fetch")
        return {"collected": 0, "provider": "betsapi", "message": "token missing"}
    if mode == "line":
        try:
            r = SyncRedis.from_url(settings.redis_url, decode_responses=True)
            if r.get(REDIS_KEY_LINE_RATE_LIMITED):
                ttl = r.ttl(REDIS_KEY_LINE_RATE_LIMITED)
                logger.info(
                    "BetsAPI line: skip (rate limit cooldown, resuming in %ss). Line will be requested again automatically.",
                    ttl if ttl > 0 else LINE_RATE_LIMIT_COOLDOWN_SECONDS,
                )
                return {"collected": 0, "provider": "betsapi", "rate_limited_cooldown": True, "resume_in_sec": ttl or LINE_RATE_LIMIT_COOLDOWN_SECONDS}
        except Exception as e:
            logger.debug("Line cooldown check: %s", e)
    try:
        logger.info("BetsAPI fetch started mode=%s sport_id=%s", mode, sport_id)
        result = asyncio.run(_fetch_and_normalize_betsapi_async(sport_id=sport_id, mode=mode))
        match_ids, skipped, rate_limited = result
        if skipped:
            countdown = LINE_SKIP_RETRY_COUNTDOWN if mode == "line" else LIVE_SKIP_RETRY_COUNTDOWN
            fetch_betsapi_table_tennis_task.apply_async(
                kwargs={"sport_id": sport_id, "mode": mode},
                countdown=countdown,
                queue="betsapi_collect",
            )
            logger.info("BetsAPI %s skipped (lock), retry in %ss", mode, countdown)
            return {"collected": 0, "provider": "betsapi", "skipped": True, "retry_in": countdown}
        if rate_limited and mode == "line":
            logger.info("BetsAPI line: 429 cooldown active. Next line fetch at next schedule after cooldown.")
            return {"collected": 0, "provider": "betsapi", "rate_limited": True, "message": "cooldown set, line resumes automatically"}
        if not match_ids:
            logger.info("BetsAPI fetch finished mode=%s collected=0", mode)
            return {"collected": 0, "provider": "betsapi", "message": "no events"}
        logger.info("BetsAPI fetch finished mode=%s collected=%s", mode, len(match_ids))
        return {"collected": len(match_ids), "provider": "betsapi", "match_ids": [str(m) for m in match_ids]}
    except Exception as e:
        logger.exception("BetsAPI fetch failed: %s", e)
        raise self.retry(exc=e, countdown=5, max_retries=3)


@celery_app.task(bind=True, name="app.worker.tasks.collect_betsapi.precompute_active_recommendations")
def precompute_active_recommendations_task(self):
    """Авто-backfill недостающих рекомендаций для актуального пула матчей."""
    try:
        result = asyncio.run(
            _run_recommendations_backfill_async(
                active_limit=settings.recommendations_backfill_active_limit,
            )
        )
        if result.get("created"):
            logger.info(
                "Recommendations backfill: candidates=%s missing_before=%s created=%s",
                result.get("candidates"),
                result.get("missing_before"),
                result.get("created"),
            )
        return {"ok": True, **result}
    except Exception as e:
        logger.exception("Recommendations backfill failed: %s", e)
        raise self.retry(exc=e, countdown=10, max_retries=3)


@celery_app.task(bind=True, name="app.worker.tasks.collect_betsapi.precompute_recommendation_for_match")
def precompute_recommendation_for_match_task(self, match_id: str):
    """Рассчитать и сохранить прогноз для одного матча (если ещё нет записи). Вызывается из API при открытии карточки матча без прогноза."""
    import uuid
    try:
        mid = uuid.UUID(match_id)
    except (ValueError, TypeError):
        logger.warning("precompute_recommendation_for_match: invalid match_id=%s", match_id)
        return {"ok": False, "created": 0, "error": "invalid match_id"}
    engine, session_maker = create_worker_engine_and_session()
    try:
        created = asyncio.run(_precompute_match_recommendations_async(session_maker, [mid]))
        if created:
            logger.info("Precomputed recommendation for match %s", match_id)
        return {"ok": True, "created": created}
    except Exception as e:
        logger.exception("Precompute recommendation for match %s failed: %s", match_id, e)
        raise self.retry(exc=e, countdown=5, max_retries=2)
    finally:
        engine.dispose()


# Расписание попыток догрузки результата:
# 1-я — сразу после начала матча (как только матч «прошёл» по start_time),
# 2-я — через 7 часов от начала, 3-я — через 24 часа (не более 3 запросов на матч).
RESULT_BACKFILL_DELAY_HOURS = (0, 7, 24)
MAX_RESULT_FETCH_ATTEMPTS = 3
# Зависшие матчи без результата старше N дней — сбрасываем счётчик попыток, чтобы дозапросить снова.
STUCK_RESET_DAYS = 7
STUCK_RESET_BATCH = 50


async def _reset_stuck_result_attempts(session_maker, limit: int = STUCK_RESET_BATCH) -> int:
    """Сбрасывает result_fetch_attempts в 0 для старых матчей без результата (зависшие), чтобы их снова дозапросили."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=STUCK_RESET_DAYS)
    async with session_maker() as session:
        q = (
            select(Match.id)
            .select_from(Match)
            .outerjoin(MatchResult, Match.id == MatchResult.match_id)
            .where(
                Match.provider == "betsapi",
                Match.result_fetch_attempts >= MAX_RESULT_FETCH_ATTEMPTS,
                Match.start_time < cutoff,
                or_(
                    MatchResult.id.is_(None),
                    MatchResult.winner_id.is_(None),
                    MatchResult.final_score.is_(None),
                    MatchResult.final_score.in_(["0:0", "0-0"]),
                ),
            )
            .limit(limit)
        )
        # scalars().all() возвращает список UUID, а не кортежей.
        match_ids = (await session.execute(q)).scalars().all()
        if not match_ids:
            return 0
        await session.execute(
            update(Match)
            .where(Match.id.in_(match_ids))
            .values(result_fetch_attempts=0, last_result_fetch_at=None)
        )
        await session.commit()
        logger.info("Result backfill: reset attempts for %s stuck match(es) (no result, start > %s days ago)", len(match_ids), STUCK_RESET_DAYS)
        return len(match_ids)


async def _run_result_backfill_async(
    batch_size: int = 10,
    match_ids: list | None = None,
) -> dict[str, Any]:
    """Находит матчи BetsAPI без результата и догружает их.
    match_ids: если задан — только эти матчи (игнорируем лимит попыток). Иначе — по расписанию."""
    engine, session_maker = create_worker_engine_and_session()
    try:
        extra_from_scores = await _backfill_results_from_scores_from_db(session_maker, limit=None)
        reset_count = await _reset_stuck_result_attempts(session_maker, limit=STUCK_RESET_BATCH)

        now = datetime.now(timezone.utc)
        cutoff_7h = now - timedelta(hours=RESULT_BACKFILL_DELAY_HOURS[1])
        cutoff_24h = now - timedelta(hours=RESULT_BACKFILL_DELAY_HOURS[2])

        no_result = or_(
            MatchResult.id.is_(None),
            MatchResult.winner_id.is_(None),
            MatchResult.final_score.is_(None),
            MatchResult.final_score.in_(["0:0", "0-0"]),
        )
        if match_ids:
            q = (
                select(Match)
                .outerjoin(MatchResult, Match.id == MatchResult.match_id)
                .where(Match.id.in_(match_ids), Match.provider == "betsapi", no_result)
                .order_by(Match.start_time.asc())
            )
        else:
            due_condition = or_(
                and_(Match.result_fetch_attempts == 0, Match.start_time <= now),
                and_(Match.result_fetch_attempts == 1, Match.start_time <= cutoff_7h),
                and_(Match.result_fetch_attempts == 2, Match.start_time <= cutoff_24h),
            )
            q = (
                select(Match)
                .outerjoin(MatchRecommendation, MatchRecommendation.match_id == Match.id)
                .outerjoin(MatchResult, Match.id == MatchResult.match_id)
                .where(
                    Match.provider == "betsapi",
                    Match.result_fetch_attempts < MAX_RESULT_FETCH_ATTEMPTS,
                    due_condition,
                    no_result,
                )
                .order_by(MatchRecommendation.id.asc().nullslast(), Match.start_time.asc())
                .limit(batch_size)
            )
        async with session_maker() as session:
            rows = (await session.execute(q)).scalars().all()
            candidates = list(rows)
        processed = 0
        with_result = 0
        attempts_inc = 0

        if candidates:
            collector = BetsApiCollector()
            sid = settings.betsapi_table_tennis_sport_id
            by_day: dict[str, list[Match]] = {}
            for m in candidates:
                day = m.start_time.strftime("%Y%m%d") if m.start_time else ""
                if day:
                    by_day.setdefault(day, []).append(m)

            # Кэш events/ended по дням — один запрос на день.
            ended_by_day: dict[str, list[dict]] = {}
            for day, matches_in_day in by_day.items():
                if day not in ended_by_day:
                    try:
                        ended_list, _ = await collector.fetch_ended_by_day(
                            day_yyyymmdd=day,
                            page=1,
                            sport_id=sid,
                            rate_limit_seconds=1.0,
                        )
                        ended_by_day[day] = ended_list or []
                    except Exception as e:
                        logger.debug("Result backfill events/ended for day %s: %s", day, e)
                        ended_by_day[day] = []

            for match in candidates:
                pid = match.provider_match_id
                day = match.start_time.strftime("%Y%m%d") if match.start_time else ""
                found_via_ended = False
                if day and ended_by_day.get(day):
                    for ev in ended_by_day[day]:
                        if str(ev.get("id")) == pid:
                            await _normalize_betsapi_async(
                                [ev],
                                session_maker,
                                current_event_ids=None,
                            )
                            await _inc_result_fetch_attempts(session_maker, match.id)
                            attempts_inc += 1
                            processed += 1
                            found_via_ended = True
                            async with session_maker() as session:
                                has_result = (
                                    await session.execute(
                                        select(MatchResult.id).where(MatchResult.match_id == match.id).limit(1)
                                    )
                                ).scalar_one_or_none()
                            if has_result:
                                with_result += 1
                                logger.info("Result backfill (ended): match %s got result", pid)
                            break
                if found_via_ended:
                    continue

                try:
                    # Запрашиваем event/view по одному (stub + view), без odds.
                    # Используем _source="inplay", чтобы нормалайзер сам определил завершение по time_status/status.
                    stubs = [{"id": pid, "_source": "inplay"}]
                    events = await collector.fetch(
                        sport_id=settings.betsapi_table_tennis_sport_id,
                        include_upcoming=False,
                        include_inplay=False,
                        include_ended=False,
                        fetch_event_view=True,
                        fetch_event_odds=False,
                        events_from_lists=stubs,
                        event_ids_for_view=[pid],
                        event_ids_for_odds=[],
                        rate_limit_seconds=1.0,
                    )
                    if not events or len(events) == 0:
                        await _inc_result_fetch_attempts(session_maker, match.id)
                        attempts_inc += 1
                        processed += 1
                        continue
                    # Не передаём current_event_ids: мы догружаем один матч, а не список inplay;
                    # иначе все остальные LIVE были бы ошибочно помечены как пропавшие.
                    await _normalize_betsapi_async(
                        events,
                        session_maker,
                        current_event_ids=None,
                    )
                    await _inc_result_fetch_attempts(session_maker, match.id)
                    attempts_inc += 1
                    processed += 1
                    async with session_maker() as session:
                        has_result = (
                            await session.execute(
                                select(MatchResult.id).where(MatchResult.match_id == match.id).limit(1)
                            )
                        ).scalar_one_or_none()
                    if has_result:
                        with_result += 1
                        logger.info("Result backfill: match %s got result", pid)
                except Exception as e:
                    logger.warning("Result backfill failed for match %s: %s", pid, e)
                    await _inc_result_fetch_attempts(session_maker, match.id)
                    attempts_inc += 1
                    processed += 1

        return {
            "processed": processed,
            "with_result": with_result,
            "attempts_inc": attempts_inc,
            "from_scores": extra_from_scores,
            "reset_stuck": reset_count,
        }
    finally:
        await engine.dispose()


async def _inc_result_fetch_attempts(session_maker, match_id) -> None:
    """Увеличивает result_fetch_attempts и выставляет last_result_fetch_at."""
    now = datetime.now(timezone.utc)
    async with session_maker() as session:
        await session.execute(
            update(Match)
            .where(Match.id == match_id)
            .values(
                result_fetch_attempts=Match.result_fetch_attempts + 1,
                last_result_fetch_at=now,
            )
        )
        await session.commit()


async def _backfill_results_from_scores_from_db(session_maker, limit: int | None = None) -> int:
    """Для завершённых матчей без MatchResult, но с записанным счётом, создаёт результат из MatchScore.

    Это страховка на случай, если BetsAPI не отдаёт финальный результат, но в БД уже есть полный счёт по сетам.
    """
    async with session_maker() as session:
        # Находим матчи BetsAPI без MatchResult, у которых есть хотя бы один сет в MatchScore.
        sub = (
            select(Match.id)
            .join(MatchScore, MatchScore.match_id == Match.id)
            .where(
                Match.provider == "betsapi",
            )
            .group_by(Match.id)
        )
        q = (
            select(Match.id)
            .select_from(Match)
            .where(Match.id.in_(sub))
            .outerjoin(MatchResult, Match.id == MatchResult.match_id)
            .where(MatchResult.id.is_(None))
        )
        # scalars().all() возвращает список UUID, а не кортежей.
        match_ids = (await session.execute(q)).scalars().all()
        if not match_ids:
            return 0

        norm = Normalizer(session)
        if limit is not None and limit > 0:
            match_ids = match_ids[:limit]
        await norm._create_result_from_scores_for_matches(match_ids)
        await session.commit()
        logger.info("Result backfill from scores: created results for %s match(es)", len(match_ids))
        return len(match_ids)


@celery_app.task(bind=True, name="app.worker.tasks.collect_betsapi.backfill_missing_results")
def backfill_missing_results_task(self, match_ids: list[str] | None = None):
    """Догрузка результатов. match_ids: опционально — только эти матчи (UUID строки). Иначе по расписанию."""
    if not settings.betsapi_token:
        return {"ok": True, "processed": 0, "message": "token missing"}
    try:
        from uuid import UUID
        ids = [UUID(mid) for mid in (match_ids or []) if mid] if match_ids else None
        result = asyncio.run(
            _run_result_backfill_async(
                batch_size=settings.result_backfill_batch_size,
                match_ids=ids,
            )
        )
        if result.get("processed", 0) > 0:
            logger.info(
                "Result backfill: processed=%s with_result=%s attempts_inc=%s",
                result.get("processed"),
                result.get("with_result"),
                result.get("attempts_inc"),
            )
        if result.get("from_scores", 0) > 0:
            logger.info("Result backfill: created %s result(s) from MatchScore", result.get("from_scores"))
        if result.get("reset_stuck", 0) > 0:
            logger.info("Result backfill: reset attempts for %s stuck match(es)", result.get("reset_stuck"))
        return {"ok": True, **result}
    except Exception as e:
        logger.exception("Result backfill failed: %s", e)
        raise self.retry(exc=e, countdown=60, max_retries=3)


LINE_ODDS_BACKFILL_BATCH_SIZE = 50


@celery_app.task(bind=True, name="app.worker.tasks.collect_betsapi.backfill_line_odds")
def backfill_line_odds_task(self):
    """Догрузка коэффициентов линии по матчам без line OddsSnapshot (scheduled/pending_odds). По расписанию или после run_line_once."""
    if not settings.betsapi_token:
        return {"ok": True, "processed": 0, "message": "token missing"}
    try:
        batch_size = getattr(settings, "line_odds_backfill_batch_size", LINE_ODDS_BACKFILL_BATCH_SIZE)
        result = asyncio.run(_run_line_odds_backfill_async(batch_size=batch_size))
        if result.get("processed", 0) > 0:
            logger.info(
                "Line odds backfill: processed=%s normalized=%s",
                result.get("processed"),
                result.get("normalized"),
            )
        return {"ok": True, **result}
    except Exception as e:
        logger.exception("Line odds backfill failed: %s", e)
        raise self.retry(exc=e, countdown=120, max_retries=3)


async def _run_disappeared_retry_async(batch_size: int = 10) -> dict[str, Any]:
    """Матчи LIVE, пропавшие из inplay без результата: повторные запросы view через 15 мин, 1 ч, 2 ч."""
    engine, session_maker = create_worker_engine_and_session()
    try:
        collector = BetsApiCollector()
        events, processed = await fetch_disappeared_retry(
            collector, session_maker, batch_size=batch_size
        )
        if not events:
            return {"processed": processed, "normalized": 0, "match_ids": []}
        current_ids = {str(e.get("id")) for e in events if e.get("id") is not None}
        match_ids = await _normalize_betsapi_async(
            events,
            session_maker,
            current_event_ids=current_ids,
        )
        if match_ids:
            await publish_matches_updated([str(mid) for mid in match_ids], mode="live")
        return {
            "processed": processed,
            "normalized": len(match_ids),
            "match_ids": [str(m) for m in match_ids],
        }
    finally:
        await engine.dispose()


@celery_app.task(bind=True, name="app.worker.tasks.collect_betsapi.run_disappeared_retry")
def run_disappeared_retry_task(self):
    """Повторные запросы по матчам, пропавшим из inplay без результата (15 мин, 1 ч, 2 ч)."""
    if not settings.betsapi_token:
        return {"ok": True, "processed": 0, "message": "token missing"}
    try:
        result = asyncio.run(_run_disappeared_retry_async(batch_size=10))
        if result.get("normalized", 0) > 0:
            logger.info(
                "Disappeared retry: processed=%s normalized=%s",
                result.get("processed"),
                result.get("normalized"),
            )
        return {"ok": True, **result}
    except Exception as e:
        logger.exception("Disappeared retry failed: %s", e)
        raise self.retry(exc=e, countdown=120, max_retries=3)


@celery_app.task(bind=True, name="app.worker.tasks.normalize.normalize_betsapi_events")
def normalize_betsapi_events_task(
    self,
    events: list[dict[str, Any]],
    current_event_ids: list[str] | None = None,
):
    """Отдельная задача нормализации пачки событий BetsAPI.

    Здесь НЕТ внешних HTTP‑запросов — только работа с БД.
    Можно запускать такие задачи параллельно множеством воркеров,
    не превышая лимиты BetsAPI (их соблюдает только fetch‑логика)."""
    engine, session_maker = create_worker_engine_and_session()
    try:
        match_ids = asyncio.run(
            _normalize_betsapi_async(
                events,
                session_maker,
                current_event_ids=set(current_event_ids) if current_event_ids is not None else None,
            )
        )
        return {"ok": True, "match_ids": [str(m) for m in match_ids]}
    except Exception as e:
        logger.exception("normalize_betsapi_events failed: %s", e)
        raise
    finally:
        asyncio.run(engine.dispose())


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
    redis_client = None
    history_lock_conn = None
    try:
        collector = BetsApiCollector()
        # Защита от параллельных ручных/авто запусков истории:
        # одновременно разрешаем только один history-runner, иначе получаем дубли и рост очередей.
        history_lock_conn = await engine.connect()
        lock_ok = (
            await history_lock_conn.execute(
                text("SELECT pg_try_advisory_lock(:key)"),
                {"key": 920101},
            )
        ).scalar()
        if not lock_ok:
            logger.info("Skip load_betsapi_history: another history task is already running")
            return {"ok": True, "skipped": True, "reason": "history task already running"}
        try:
            redis_client = redis_from_url(settings.redis_url)
        except Exception as e:
            logger.warning("History backpressure init failed, continue without queue guard: %s", e)
            redis_client = None
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
                for attempt in range(MAX_ENDED_REQUEST_RETRIES):
                    try:
                        events, _ = await collector.fetch_ended_by_day(
                            day_yyyymmdd=day,
                            page=page,
                            sport_id=sport_id,
                            rate_limit_seconds=0,
                        )
                        break
                    except (BetsapiEndedRequestError, BetsApiRateLimitError) as e:
                        if attempt < MAX_ENDED_REQUEST_RETRIES - 1:
                            sleep_sec = ENDED_RETRY_SLEEP_RATE_LIMIT if isinstance(e, BetsApiRateLimitError) else ENDED_RETRY_SLEEP_OTHER
                            logger.warning(
                                "load_betsapi_history: day=%s page=%s attempt=%s error=%s, retry in %ss",
                                day, page, attempt + 1, e, sleep_sec,
                            )
                            await asyncio.sleep(sleep_sec)
                        else:
                            raise
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
                # Нормализацию и запись в БД выносим в отдельную Celery‑задачу,
                # чтобы обрабатывать страницы/дни параллельно несколькими воркерами.
                if redis_client is not None:
                    try:
                        await _wait_for_normalize_queue_capacity(
                            redis_client,
                            queue_name="normalize",
                            max_depth=settings.betsapi_history_normalize_queue_max_depth,
                            sleep_seconds=settings.betsapi_history_backpressure_sleep_seconds,
                        )
                    except Exception as e:
                        logger.warning("History backpressure check failed, continue enqueueing: %s", e)
                normalize_betsapi_events_task.delay(events, None)
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
                logger.info(
                    "load_betsapi_history: day=%s page=%s events=%s (queued for normalize)",
                    day,
                    page,
                    len(events),
                )
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
            # Точное число созданных матчей теперь считает параллельная задача нормализации.
            "match_ids_queued_for_processing": total_created,
        }
    finally:
        if history_lock_conn is not None:
            try:
                await history_lock_conn.execute(
                    text("SELECT pg_advisory_unlock(:key)"),
                    {"key": 920101},
                )
                await history_lock_conn.close()
            except Exception:
                pass
        if redis_client is not None:
            try:
                await redis_client.aclose()
            except Exception:
                pass
        await engine.dispose()


@celery_app.task(bind=True, name="app.worker.tasks.collect_betsapi.load_betsapi_history")
def load_betsapi_history_task(
    self,
    day_from: str = "20160901",
    day_to: str | None = None,
    delay_seconds: float = 1.0,
    sport_id: int | None = None,
):
    """Ручная загрузка архива завершённых матчей BetsAPI по диапазону дат.

    Используется из админского API `/matches/load-history` — можно задать любой диапазон
    и интервал между запросами `delay_seconds`, чтобы контролировать нагрузку.
    """
    from datetime import datetime, timezone

    logger.info(
        "load_betsapi_history started: day_from=%s day_to=%s delay_seconds=%s",
        day_from,
        day_to,
        delay_seconds,
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


@celery_app.task(bind=True, name="app.worker.tasks.collect_betsapi.load_betsapi_today")
def load_betsapi_today_task(
    self,
    delay_seconds: float | None = None,
    sport_id: int | None = None,
):
    """Автоматическая загрузка архива BetsAPI за текущий и предыдущий день (раз в 2 часа)."""
    from datetime import datetime, timedelta, timezone

    if not settings.betsapi_token:
        logger.warning("load_betsapi_today: BETSAPI_TOKEN not set in worker environment")
        return {"ok": False, "error": "BETSAPI_TOKEN not set"}

    now = datetime.now(timezone.utc)
    day_to = now.strftime("%Y%m%d")
    days_back = getattr(settings, "betsapi_history_auto_days", 2)
    start = now - timedelta(days=days_back - 1)
    day_from = start.strftime("%Y%m%d")

    sid = sport_id if sport_id is not None else settings.betsapi_table_tennis_sport_id
    effective_delay = delay_seconds if delay_seconds is not None else settings.betsapi_history_delay_seconds

    logger.info(
        "load_betsapi_today started: day_from=%s day_to=%s delay_seconds=%s",
        day_from,
        day_to,
        effective_delay,
    )
    try:
        result = asyncio.run(
            _run_load_betsapi_history_async(
                day_from=day_from,
                day_to=day_to,
                delay_seconds=effective_delay,
                sport_id=sid,
            )
        )
        return result
    except Exception as e:
        logger.exception("load_betsapi_today failed: %s", e)
        return {"ok": False, "error": str(e)}
