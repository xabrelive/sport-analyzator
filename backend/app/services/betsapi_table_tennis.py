"""BetsAPI: загрузка линии по настольному теннису (upcoming) с постраничным обходом.

Важно: проходим по страницам, пока API не вернёт пустую страницу (нет результатов).
Результат сохраняется в БД (table_tennis_line_events) и отдаётся через API (GET /api/v1/table-tennis/line).
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timezone, timedelta
from typing import Any, Dict, List

import httpx
import sqlalchemy as sa
from sqlalchemy import select, update, case, func
from sqlalchemy.dialects.postgresql import insert

from app.config import settings
from app.db.session import async_session_maker
from app.models.table_tennis_line_event import (
    TableTennisLineEvent,
    LINE_EVENT_STATUS_SCHEDULED,
    LINE_EVENT_STATUS_LIVE,
    LINE_EVENT_STATUS_FINISHED,
    LINE_EVENT_STATUS_POSTPONED,
    LINE_EVENT_STATUS_CANCELLED,
    STATUSES_UPCOMING,
)
from app.models.table_tennis_player import TableTennisPlayer
from app.models.table_tennis_league import TableTennisLeague
from app.models.table_tennis_league_rule import TableTennisLeagueRule
from app.models.table_tennis_forecast_v2 import TableTennisForecastV2
from app.worker.queue import put_batch as line_put_batch
from app.services.table_tennis_analytics import update_forecast_outcome_for_event

logger = logging.getLogger(__name__)

# Кэш последней загрузки (для обратной совместимости; приоритет — чтение из БД)
_line_cache: Dict[str, Any] = {
    "events": [],
    "updated_at": None,
}

BETSAPI_BASE_URL = "https://api.betsapi.com/v2"
BET365API_BASE_URL = "https://api.b365api.com"

# BetsAPI time_status -> наш status
_TIME_STATUS_MAP = {
    0: LINE_EVENT_STATUS_SCHEDULED,   # Not Started
    1: LINE_EVENT_STATUS_LIVE,        # Inplay
    2: LINE_EVENT_STATUS_SCHEDULED,   # To Be Fixed
    3: LINE_EVENT_STATUS_FINISHED,    # Ended
    4: LINE_EVENT_STATUS_POSTPONED,  # Postponed
    5: LINE_EVENT_STATUS_CANCELLED,  # Cancelled
    6: LINE_EVENT_STATUS_CANCELLED,  # Abandoned
    7: LINE_EVENT_STATUS_LIVE,       # Interrupted
    8: LINE_EVENT_STATUS_LIVE,       # Suspended
}


async def _log_betsapi_request(endpoint: str, status_code: int, ok: bool) -> None:
    """Записывает отладочную статистику по запросу в BetsAPI."""
    try:
        async with async_session_maker() as session:
            await session.execute(
                sa.text(
                    "INSERT INTO betsapi_request_logs (endpoint, status_code, ok) "
                    "VALUES (:endpoint, :status_code, :ok)"
                ),
                {"endpoint": endpoint, "status_code": int(status_code), "ok": bool(ok)},
            )
            await session.commit()
    except Exception as e:  # noqa: BLE001
        logger.debug("Failed to log BetsAPI request: %s", e)


# Множества для защиты от дублирующих запросов на один и тот же матч (в рамках процесса).
_inflight_odds: set[str] = set()
_inflight_odds_lock = asyncio.Lock()


async def _try_reserve_odds_ids(ids: list[str]) -> list[str]:
    """Отфильтровать event_id, для которых ещё не идёт запрос odds, и зарезервировать их."""
    async with _inflight_odds_lock:
        unique: list[str] = []
        for eid in ids:
            if eid in _inflight_odds:
                continue
            _inflight_odds.add(eid)
            unique.append(eid)
        return unique


async def _release_odds_ids(ids: list[str]) -> None:
    async with _inflight_odds_lock:
        for eid in ids:
            _inflight_odds.discard(eid)


def _to_int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_ss_value(ss: Any) -> tuple[int | None, int | None]:
    """Парсит BetsAPI ss (например '6-7') в (home, away)."""
    if not isinstance(ss, str) or "-" not in ss:
        return None, None
    left, right = ss.split("-", 1)
    return _to_int_or_none(left), _to_int_or_none(right)


def _build_live_scores_from_event(ev: Dict[str, Any]) -> dict[str, dict[str, str]]:
    """Нормализует per-set scores и дополняет текущим ss, если set-breakdown пустой."""
    out: dict[str, dict[str, str]] = {}
    raw_scores = ev.get("scores")
    if isinstance(raw_scores, dict):
        for key, val in raw_scores.items():
            if not isinstance(val, dict):
                continue
            h = _to_int_or_none(val.get("home"))
            a = _to_int_or_none(val.get("away"))
            if h is None and a is None:
                continue
            out[str(key)] = {
                "home": "" if h is None else str(h),
                "away": "" if a is None else str(a),
            }

    # Если API не дал scores по сетам, но дал ss (текущий сет), сохраняем его как fallback.
    if not out:
        ss_home, ss_away = _parse_ss_value(ev.get("ss"))
        if ss_home is not None or ss_away is not None:
            out["1"] = {
                "home": "" if ss_home is None else str(ss_home),
                "away": "" if ss_away is None else str(ss_away),
            }
    return out


def _derive_live_sets_score(scores: dict[str, dict[str, str]], ss: Any) -> str | None:
    """Пытается получить общий счёт по сетам максимально надёжно.

    Приоритет:
    1) посчитать по завершённым сетам из scores;
    2) взять summary-значение из scores (если есть компактный счёт вида 2-1);
    3) fallback к ss, только если ss похож на сетовый счёт.
    """
    wins_home = 0
    wins_away = 0
    completed_sets = 0
    summary_candidate: tuple[int, int] | None = None
    summary_key_rank = -1

    for key in sorted(scores.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
        set_score = scores.get(key) or {}
        sh = _to_int_or_none(set_score.get("home"))
        sa = _to_int_or_none(set_score.get("away"))
        if sh is None or sa is None:
            continue

        # Some feeds include a compact aggregate score inside `scores`.
        if sh <= 5 and sa <= 5:
            rank = int(key) if str(key).isdigit() else 0
            if rank >= summary_key_rank:
                summary_key_rank = rank
                summary_candidate = (sh, sa)

        # Completed table-tennis set: winner has >=11 and 2+ points advantage.
        if max(sh, sa) >= 11 and abs(sh - sa) >= 2:
            completed_sets += 1
            if sh > sa:
                wins_home += 1
            elif sa > sh:
                wins_away += 1

    if completed_sets > 0:
        return f"{wins_home}-{wins_away}"

    if summary_candidate and (summary_candidate[0] > 0 or summary_candidate[1] > 0):
        return f"{summary_candidate[0]}-{summary_candidate[1]}"

    ss_home, ss_away = _parse_ss_value(ss)
    if (
        ss_home is not None
        and ss_away is not None
        and ss_home <= 5
        and ss_away <= 5
        and (ss_home > 0 or ss_away > 0)
    ):
        return f"{ss_home}-{ss_away}"

    return None


def _is_completed_set_score(home: int, away: int) -> bool:
    winner = max(home, away)
    loser = min(home, away)
    return winner >= 11 and (winner - loser) >= 2


def _has_in_progress_set_fragment(live_score: Any) -> bool:
    if not isinstance(live_score, dict):
        return False
    for _, set_data in live_score.items():
        if not isinstance(set_data, dict):
            continue
        home_raw = set_data.get("home")
        away_raw = set_data.get("away")
        if home_raw is None and away_raw is None:
            continue
        home = _to_int_or_none(home_raw)
        away = _to_int_or_none(away_raw)
        if home is None and away is None:
            continue
        h = int(home or 0)
        a = int(away or 0)
        if h == 0 and a == 0:
            continue
        if not _is_completed_set_score(h, a):
            return True
    return False


async def _load_league_rules_map() -> Dict[str, Dict[str, int]]:
    """Загружает правила лиг для эвристики live/finished/stale."""
    async with async_session_maker() as session:
        result = await session.execute(select(TableTennisLeagueRule))
        rows = list(result.scalars().all())
    rules: Dict[str, Dict[str, int]] = {}
    for r in rows:
        rules[str(r.league_id)] = {
            "max_sets_wins": int(r.max_sets_wins or 3),
            "expected_duration_minutes": int(r.expected_duration_minutes or 30),
            "stale_after_minutes": int(r.stale_after_minutes or 25),
        }
    return rules


async def _fetch_upcoming_page(
    client: httpx.AsyncClient,
    page: int,
) -> List[Dict[str, Any]]:
    """Запрос одной страницы upcoming-событий настольного тенниса.

    Если страница пуста или API вернул ошибку/нет results — возвращаем пустой список.
    """
    token = (settings.betsapi_token or "").strip()
    if not token:
        logger.warning(
            "BetsAPI: BETSAPI_TOKEN не задан — линия не запрашивается. "
            "Задайте betsapi_token в .env"
        )
        return []

    params = {
        "sport_id": settings.betsapi_table_tennis_sport_id,
        "page": page,
        "token": token,
    }
    url = f"{BETSAPI_BASE_URL}/events/upcoming"
    try:
        r = await client.get(url, params=params, timeout=15.0)
    except httpx.HTTPError as e:
        logger.warning("BetsAPI: HTTP error on page %s: %s", page, e)
        await _log_betsapi_request("events/upcoming", 0, False)
        return []

    await _log_betsapi_request("events/upcoming", r.status_code, r.status_code == 200)
    if r.status_code != 200:
        logger.warning(
            "BetsAPI: non-200 status on page %s: %s %s",
            page,
            r.status_code,
            r.text[:200],
        )
        return []

    try:
        data = r.json()
    except ValueError:
        logger.warning("BetsAPI: invalid JSON on page %s", page)
        return []

    # Формат BetsAPI v2: {"success":1,"pager":{"page":1,...},"results":[...]}
    results = data.get("results")
    if not isinstance(results, list) or not results:
        logger.info("BetsAPI: page %s has no results (stop paging)", page)
        return []
    return results


async def _fetch_inplay(
    client: httpx.AsyncClient,
) -> List[Dict[str, Any]]:
    """Запрос всех inplay-событий настольного тенниса (лайв, без пагинации)."""
    token = (settings.betsapi_token or "").strip()
    if not token:
        logger.warning(
            "BetsAPI: BETSAPI_TOKEN не задан — лайв не запрашивается. "
            "Задайте betsapi_token в .env"
        )
        return []

    params = {
        "sport_id": settings.betsapi_table_tennis_sport_id,
        "token": token,
    }
    # Для inplay используем тот же v2-хост, что и для линии — структура такая же (есть ss и scores).
    url = f"{BETSAPI_BASE_URL}/events/inplay"
    try:
        r = await client.get(url, params=params, timeout=15.0)
    except httpx.HTTPError as e:
        logger.warning("BetsAPI: HTTP error on inplay: %s", e)
        await _log_betsapi_request("events/inplay", 0, False)
        return []

    await _log_betsapi_request("events/inplay", r.status_code, r.status_code == 200)
    if r.status_code != 200:
        logger.warning(
            "BetsAPI: non-200 status on inplay: %s %s",
            r.status_code,
            r.text[:200],
        )
        return []

    try:
        data = r.json()
    except ValueError:
        logger.warning("BetsAPI: invalid JSON on inplay")
        return []

    results = data.get("results")
    if not isinstance(results, list) or not results:
        logger.info("BetsAPI: inplay has no results for table tennis")
        return []
    return results


async def update_line_live_status_once(update_non_forecast_scores: bool = True) -> None:
    """Один проход: загрузить inplay и обновить статусы матчей в таблице линии.

    Если матч был в линии (scheduled/postponed) и стал лайв — меняем статус на live.
    Также фиксируем переходы в finished/cancelled и др. статусы по time_status.
    """
    async with httpx.AsyncClient() as client:
        events = await _fetch_inplay(client)

    if not events:
        return

    # Парсим события так же, как для линии — через _parse_event_for_db (учитывает time_status -> status),
    # но дополнительно кладём лайв-счёт по сетам (кол-во выигранных сетов) и счёт каждого сета.
    rows: List[Dict[str, Any]] = []
    for ev in events:
        row = _parse_event_for_db(ev)
        if not row:
            continue

        scores = _build_live_scores_from_event(ev)
        live_sets_score = _derive_live_sets_score(scores, ev.get("ss")) if scores else None
        if scores:
            row["live_score"] = scores

        row["live_sets_score"] = live_sets_score
        # Для finished не допускаем NULL в счёте по сетам.
        # Для live/postponed ничего не "обнуляем", чтобы не затирать предыдущий счёт
        # при частичных/пустых ответах API.
        if row.get("status") in (
            LINE_EVENT_STATUS_FINISHED,
        ):
            if row.get("live_sets_score") is None:
                row["live_sets_score"] = "0-0"
            if row.get("live_score") is None:
                row["live_score"] = {}
        rows.append(row)
    if not rows:
        return

    now = datetime.now(timezone.utc)
    rules_map = await _load_league_rules_map()

    # Сравниваем с текущими значениями, чтобы отмечать изменение счёта только когда оно реально произошло.
    async with async_session_maker() as session:
        existing_result = await session.execute(
            select(
                TableTennisLineEvent.id,
                TableTennisLineEvent.live_score,
                TableTennisLineEvent.live_sets_score,
                TableTennisLineEvent.forecast,
            ).where(TableTennisLineEvent.id.in_([r["id"] for r in rows]))
        )
        existing_map = {
            str(r[0]): {"live_score": r[1], "live_sets_score": r[2], "forecast": r[3]}
            for r in existing_result.all()
        }

    for row in rows:
        prev = existing_map.get(str(row["id"]))
        has_forecast = bool((prev or {}).get("forecast"))
        new_score = row.get("live_score")
        new_sets_score = row.get("live_sets_score")
        status_now = row.get("status")

        # Для матчей без прогноза обновляем текущий счёт реже (каждые N циклов),
        # но финальные статусы/результаты всё равно обрабатываем сразу.
        if (
            not has_forecast
            and not update_non_forecast_scores
            and status_now not in (LINE_EVENT_STATUS_FINISHED, LINE_EVENT_STATUS_CANCELLED)
        ):
            row["live_score"] = None
            row["live_sets_score"] = None
            row["last_score_changed_at"] = None
            continue

        if prev and new_score is not None:
            if prev.get("live_score") == new_score and (prev.get("live_sets_score") or None) == (new_sets_score or None):
                # Счёт не изменился — не трогаем его и не обновляем last_score_changed_at.
                row["live_score"] = None
                row["live_sets_score"] = None
            else:
                row["last_score_changed_at"] = now
        elif new_score is not None:
            # Новый матч с уже известным счётом.
            row["last_score_changed_at"] = now

    updated_ids: list[str] = [str(r["id"]) for r in rows]

    async with async_session_maker() as session:
        stmt = insert(TableTennisLineEvent).values(rows)
        # Для уже существующих матчей обновляем только статус, лайв-счёт и updated_at, не трогая odds и прочее.
        # Важно: если из BetsAPI пришёл пустой счёт по сетам, сохраняем прежний live_score/live_sets_score.
        # last_score_changed_at обновляем только если пришёл новый live_score.
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "status": stmt.excluded.status,
                "live_sets_score": case(
                    (
                        stmt.excluded.live_sets_score.is_(None),
                        TableTennisLineEvent.live_sets_score,
                    ),
                    else_=stmt.excluded.live_sets_score,
                ),
                "live_score": case(
                    (
                        stmt.excluded.live_score.is_(None),
                        TableTennisLineEvent.live_score,
                    ),
                    else_=stmt.excluded.live_score,
                ),
                "last_score_changed_at": case(
                    (
                        stmt.excluded.last_score_changed_at.is_(None),
                        TableTennisLineEvent.last_score_changed_at,
                    ),
                    else_=stmt.excluded.last_score_changed_at,
                ),
                "is_stale": False,
                "stale_since": None,
                "result_status": case(
                    (
                        stmt.excluded.status == LINE_EVENT_STATUS_FINISHED,
                        TableTennisLineEvent.result_status,
                    ),
                    else_="open",
                ),
                "updated_at": now,
            },
        )
        await session.execute(stmt)
        # Страховка от JSON null в live_score для начавшихся/завершённых матчей.
        await session.execute(
            TableTennisLineEvent.__table__.update()
            .where(TableTennisLineEvent.id.in_(updated_ids))
            .where(
                TableTennisLineEvent.status.in_(
                    [LINE_EVENT_STATUS_LIVE, LINE_EVENT_STATUS_FINISHED, LINE_EVENT_STATUS_POSTPONED]
                )
            )
            .where(
                (TableTennisLineEvent.live_score.is_(None))
                | (sa.cast(TableTennisLineEvent.live_score, sa.Text) == "null")
            )
            .values(live_score={}, updated_at=now)
        )
        # Для матчей, которые только что стали finished, один раз проставляем finished_at.
        await session.execute(
            TableTennisLineEvent.__table__.update()
            .where(
                TableTennisLineEvent.id.in_(updated_ids),
                TableTennisLineEvent.status == LINE_EVENT_STATUS_FINISHED,
                TableTennisLineEvent.finished_at.is_(None),
            )
            .values(finished_at=now, updated_at=now)
        )

        # Попробуем сразу зарезолвить прогнозы для матчей, которые уже в статусе finished.
        finished_result = await session.execute(
            select(TableTennisLineEvent).where(
                TableTennisLineEvent.id.in_(updated_ids),
                TableTennisLineEvent.status == LINE_EVENT_STATUS_FINISHED,
            )
        )
        finished_events = list(finished_result.scalars().all())
        for ev_obj in finished_events:
            await update_forecast_outcome_for_event(session, ev_obj)

        await session.commit()

    logger.info("BetsAPI: updated line statuses from inplay for %s events", len(rows))


async def fetch_table_tennis_line_once() -> List[Dict[str, Any]]:
    """Загрузить всю линию настольного тенниса (upcoming) со всех страниц.

    Идём по страницам 1..N, пока:
    - не получим пустую `results`, или
    - не достигнем betsapi_table_tennis_max_pages.
    """
    max_pages = max(1, settings.betsapi_table_tennis_max_pages)
    all_events: List[Dict[str, Any]] = []

    hit_page_limit = False
    async with httpx.AsyncClient() as client:
        page = 1
        while page <= max_pages:
            results = await _fetch_upcoming_page(client, page)
            if not results:
                break
            all_events.extend(results)
            await line_put_batch(results)
            logger.info(
                "BetsAPI: fetched page %s (%s events), total=%s",
                page,
                len(results),
                len(all_events),
            )
            page += 1
            # Небольшая пауза, чтобы не упираться в rate limit
            await asyncio.sleep(0.5)
        if page > max_pages and all_events:
            hit_page_limit = True

    logger.info(
        "BetsAPI: table tennis line fetch complete, total events=%s", len(all_events)
    )
    _line_cache["events"] = all_events
    _line_cache["updated_at"] = time.time()
    # Матчи, которых нет в текущей линии, помечаем отменёнными (убрались из линии).
    current_ids = [str(ev.get("id")) for ev in all_events if ev.get("id") is not None]
    await _mark_missing_events_cancelled(current_ids, line_fetch_complete=not hit_page_limit)
    return all_events


async def _mark_missing_events_cancelled(
    current_event_ids: List[str],
    line_fetch_complete: bool,
) -> None:
    """Матчи, которых нет в current_event_ids и которые ещё в статусе scheduled/postponed, помечаем cancelled."""
    if not current_event_ids:
        return
    if not line_fetch_complete:
        logger.warning(
            "BetsAPI: skipped 'missing->cancelled' because line fetch hit max pages (incomplete snapshot)"
        )
        return
    now = datetime.now(timezone.utc)
    horizon_minutes = max(10, int(getattr(settings, "betsapi_table_tennis_cancel_missing_horizon_minutes", 90)))
    horizon_dt = now + timedelta(minutes=horizon_minutes)
    async with async_session_maker() as session:
        stmt = (
            update(TableTennisLineEvent)
            .where(TableTennisLineEvent.id.notin_(current_event_ids))
            .where(TableTennisLineEvent.status.in_(STATUSES_UPCOMING))
            # Не трогаем дальние матчи и матчи, где уже есть счёт (если счёт есть — это точно не отмена).
            .where(TableTennisLineEvent.starts_at <= horizon_dt)
            .where(
                sa.or_(
                    TableTennisLineEvent.live_sets_score.is_(None),
                    TableTennisLineEvent.live_sets_score == "",
                    TableTennisLineEvent.live_sets_score == "0-0",
                )
            )
            .values(status=LINE_EVENT_STATUS_CANCELLED, updated_at=now)
        )
        result = await session.execute(stmt)
        await session.commit()
        if result.rowcount and result.rowcount > 0:
            logger.info("BetsAPI: marked %s events as cancelled (removed from line)", result.rowcount)


async def repair_cancelled_with_scores_once(limit: int = 200) -> int:
    """Исправляет ложные cancelled.

    1) Если есть явный счёт по сетам с победителем — матч считаем finished.
    2) Для будущих матчей с прогнозом (pending), ошибочно помеченных cancelled — возвращаем status=scheduled.
    """
    async with async_session_maker() as session:
        rows_result = await session.execute(
            select(TableTennisLineEvent)
            .where(
                TableTennisLineEvent.status == LINE_EVENT_STATUS_CANCELLED,
                TableTennisLineEvent.live_sets_score.is_not(None),
                TableTennisLineEvent.live_sets_score != "",
                TableTennisLineEvent.live_sets_score != "0-0",
            )
            .limit(max(1, int(limit)))
        )
        rows = list(rows_result.scalars().all())
        if not rows:
            rows = []
        now = datetime.now(timezone.utc)
        fixed = 0
        for row in rows:
            left, right = row.live_sets_score.split("-", 1) if row.live_sets_score else ("", "")
            try:
                l = int(left)
                r = int(right)
            except ValueError:
                continue
            if l == r:
                continue
            row.status = LINE_EVENT_STATUS_FINISHED
            if row.finished_at is None:
                row.finished_at = now
            row.updated_at = now
            await update_forecast_outcome_for_event(session, row)
            fixed += 1

        # Исправляем будущие cancelled с прогнозом: это чаще всего следствие неполного snapshot upcoming.
        future_ids_result = await session.execute(
            select(TableTennisLineEvent.id)
            .join(
                TableTennisForecastV2,
                TableTennisForecastV2.event_id == TableTennisLineEvent.id,
            )
            .where(
                TableTennisLineEvent.status == LINE_EVENT_STATUS_CANCELLED,
                TableTennisLineEvent.starts_at > now,
                TableTennisForecastV2.status.in_(["pending", "cancelled", "no_result"]),
            )
            .group_by(TableTennisLineEvent.id)
            .limit(max(1, int(limit)))
        )
        future_ids = [str(r[0]) for r in future_ids_result.all()]
        if future_ids:
            future_rows_result = await session.execute(
                select(TableTennisLineEvent).where(TableTennisLineEvent.id.in_(future_ids))
            )
            future_cancelled = list(future_rows_result.scalars().all())
        else:
            future_cancelled = []
        for row in future_cancelled:
            row.status = LINE_EVENT_STATUS_SCHEDULED
            row.result_status = "open"
            row.locked_at = None
            row.result_checked_1h_at = None
            row.result_checked_3h_at = None
            row.updated_at = now
            fixed += 1
        await session.commit()
    if fixed:
        logger.info("BetsAPI: repaired %s cancelled matches to finished by sets score", fixed)
    return fixed


async def revalidate_cancelled_forecast_events_once(limit: int = 100) -> dict[str, int]:
    """Перепроверяет cancelled-матчи с прогнозом и pending-статусом прогноза.

    Логика:
    1) Пытаемся получить актуальный status/score через /event (с fallback /event/view).
    2) Если по событию всё ещё нет данных, пробуем архив ended по дню старта.
    3) При валидном счёте/статусе обновляем line_events и сразу резолвим прогноз.
    """
    now = datetime.now(timezone.utc)
    async with async_session_maker() as session:
        ids_result = await session.execute(
            select(TableTennisLineEvent.id, func.max(TableTennisLineEvent.updated_at).label("u"))
            .join(
                TableTennisForecastV2,
                TableTennisForecastV2.event_id == TableTennisLineEvent.id,
            )
            .where(
                TableTennisLineEvent.status == LINE_EVENT_STATUS_CANCELLED,
                TableTennisLineEvent.result_status != "locked",
                TableTennisForecastV2.status.in_(["pending", "cancelled", "no_result"]),
            )
            .group_by(TableTennisLineEvent.id)
            .order_by(sa.desc("u"))
            .limit(max(1, int(limit)))
        )
        ids = [str(r[0]) for r in ids_result.all()]
        if ids:
            rows_result = await session.execute(
                select(TableTennisLineEvent).where(TableTennisLineEvent.id.in_(ids))
            )
            candidates = list(rows_result.scalars().all())
        else:
            candidates = []

    if not candidates:
        return {"candidates": 0, "updated_by_event": 0, "updated_by_archive": 0}

    by_id: dict[str, TableTennisLineEvent] = {str(r.id): r for r in candidates if r.id}
    updated_by_event = 0
    updated_by_archive = 0
    unresolved_ids: set[str] = set(by_id.keys())

    async with httpx.AsyncClient() as client, async_session_maker() as session:
        # Получаем "свежие" данные по каждому cancelled-событию с прогнозом.
        for eid in list(unresolved_ids):
            ev = await _fetch_event_result(client, eid)
            if not ev:
                continue
            row = await session.get(TableTennisLineEvent, eid)
            if row is None:
                continue

            time_status = ev.get("time_status")
            try:
                ts_int = int(time_status) if time_status is not None else 0
            except (TypeError, ValueError):
                ts_int = 0
            mapped_status = _TIME_STATUS_MAP.get(ts_int, LINE_EVENT_STATUS_SCHEDULED)

            scores = _build_live_scores_from_event(ev)
            sets_score = _derive_live_sets_score(scores, ev.get("ss")) if scores else None

            changed = False
            if mapped_status != LINE_EVENT_STATUS_CANCELLED:
                row.status = mapped_status
                row.result_status = "open"
                row.locked_at = None
                row.result_checked_1h_at = None
                row.result_checked_3h_at = None
                changed = True
                if mapped_status == LINE_EVENT_STATUS_FINISHED and row.finished_at is None:
                    row.finished_at = now

            if scores:
                row.live_score = scores
                row.last_score_changed_at = now
                changed = True
            if sets_score:
                row.live_sets_score = sets_score
                changed = True

            # Даже если API вернул cancelled/other, переводим в finished только при
            # действительно финальном счёте и без признаков незавершённого текущего сета.
            left = right = None
            if row.live_sets_score and "-" in row.live_sets_score:
                try:
                    l_raw, r_raw = row.live_sets_score.split("-", 1)
                    left = int(l_raw)
                    right = int(r_raw)
                except (TypeError, ValueError):
                    left = right = None
            league_id = str(row.league_id or "")
            league_rules = rules_map.get(league_id, {})
            required_wins = int(league_rules.get("max_sets_wins", settings.table_tennis_match_sets_to_win or 3))
            score_final = (
                left is not None
                and right is not None
                and left != right
                and max(left, right) >= max(1, required_wins)
            )
            has_in_progress_set = _has_in_progress_set_fragment(row.live_score)
            if score_final and not has_in_progress_set:
                row.status = LINE_EVENT_STATUS_FINISHED
                row.result_status = "open"
                row.locked_at = None
                if row.finished_at is None:
                    row.finished_at = now
                changed = True

            if changed:
                row.updated_at = now
                await update_forecast_outcome_for_event(session, row)
                updated_by_event += 1
                unresolved_ids.discard(eid)

        # Догружаем по архиву ended те, кто не нашёлся/не обновился на предыдущем шаге.
        if unresolved_ids:
            day_map: dict[str, set[str]] = {}
            for eid in unresolved_ids:
                row = by_id.get(eid)
                if row is None or row.starts_at is None:
                    continue
                day_key = row.starts_at.astimezone(timezone.utc).strftime("%Y%m%d")
                day_map.setdefault(day_key, set()).add(eid)

            for day_key, ids_for_day in day_map.items():
                ended_rows = await _fetch_ended_events_day(client, day_key, max_pages=6)
                if not ended_rows:
                    continue
                ended_by_id = {str(ev.get("id")): ev for ev in ended_rows if ev.get("id") is not None}
                for eid in ids_for_day:
                    ev = ended_by_id.get(eid)
                    if not ev:
                        continue
                    row = await session.get(TableTennisLineEvent, eid)
                    if row is None:
                        continue
                    scores = _build_live_scores_from_event(ev)
                    sets_score = _derive_live_sets_score(scores, ev.get("ss")) if scores else None
                    if not scores and not sets_score:
                        continue
                    row.status = LINE_EVENT_STATUS_FINISHED
                    row.result_status = "open"
                    row.locked_at = None
                    if row.finished_at is None:
                        row.finished_at = now
                    if scores:
                        row.live_score = scores
                    if sets_score:
                        row.live_sets_score = sets_score
                    row.updated_at = now
                    await update_forecast_outcome_for_event(session, row)
                    updated_by_archive += 1

        await session.commit()

    total_updated = updated_by_event + updated_by_archive
    if total_updated:
        logger.info(
            "BetsAPI: revalidated cancelled forecast events: candidates=%s, updated_by_event=%s, updated_by_archive=%s",
            len(candidates),
            updated_by_event,
            updated_by_archive,
        )
    return {
        "candidates": len(candidates),
        "updated_by_event": updated_by_event,
        "updated_by_archive": updated_by_archive,
    }


def _parse_event_for_db(ev: Dict[str, Any]) -> Dict[str, Any] | None:
    """Преобразует сырой ответ BetsAPI в словарь для вставки в table_tennis_line_events."""
    eid = ev.get("id")
    if eid is None:
        return None
    row_id = str(eid)
    league = ev.get("league") if isinstance(ev.get("league"), dict) else {}
    home = ev.get("home") if isinstance(ev.get("home"), dict) else {}
    away = ev.get("away") if isinstance(ev.get("away"), dict) else {}
    ts = ev.get("time")
    if ts is None:
        return None
    try:
        starts_at = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
    odds_1 = ev.get("odds_1")
    odds_2 = ev.get("odds_2")
    if odds_1 is not None and not isinstance(odds_1, (int, float)):
        odds_1 = None
    if odds_2 is not None and not isinstance(odds_2, (int, float)):
        odds_2 = None
    time_status = ev.get("time_status")
    if time_status is not None and not isinstance(time_status, int):
        try:
            time_status = int(time_status)
        except (TypeError, ValueError):
            time_status = 0
    status = _TIME_STATUS_MAP.get(time_status if time_status is not None else 0, LINE_EVENT_STATUS_SCHEDULED)
    return {
        "id": row_id,
        "league_id": str(league.get("id") or ""),
        "league_name": (league.get("name") or "").strip() or "—",
        "home_id": str(home.get("id") or ""),
        "home_name": (home.get("name") or "").strip() or "—",
        "away_id": str(away.get("id") or ""),
        "away_name": (away.get("name") or "").strip() or "—",
        "starts_at": starts_at,
        "status": status,
        "odds_1": float(odds_1) if odds_1 is not None else None,
        "odds_2": float(odds_2) if odds_2 is not None else None,
    }


async def save_table_tennis_line_to_db(events: List[Dict[str, Any]]) -> None:
    """Сохраняет события линии в БД (upsert по id). Сначала дополняет справочники игроков и лиг."""
    rows: List[Dict[str, Any]] = []
    for ev in events:
        row = _parse_event_for_db(ev)
        if row:
            rows.append(row)
    if not rows:
        return

    now = datetime.now(timezone.utc)

    # Уникальные лиги и игроки из батча
    leagues_seen: Dict[str, str] = {}
    players_seen: Dict[str, str] = {}
    for r in rows:
        if r["league_id"]:
            leagues_seen[r["league_id"]] = r["league_name"]
        if r["home_id"]:
            players_seen[r["home_id"]] = r["home_name"]
        if r["away_id"]:
            players_seen[r["away_id"]] = r["away_name"]

    async with async_session_maker() as session:
        # Лиги и игроки: только добавляем новых, существующие по id не перезаписываем.
        if leagues_seen:
            league_rows = [
                {"id": lid, "name": name, "updated_at": now}
                for lid, name in leagues_seen.items()
            ]
            stmt_league = insert(TableTennisLeague).values(league_rows)
            stmt_league = stmt_league.on_conflict_do_nothing(index_elements=["id"])
            await session.execute(stmt_league)
        if players_seen:
            player_rows = [
                {"id": pid, "name": name, "updated_at": now}
                for pid, name in players_seen.items()
            ]
            stmt_player = insert(TableTennisPlayer).values(player_rows)
            stmt_player = stmt_player.on_conflict_do_nothing(index_elements=["id"])
            await session.execute(stmt_player)

        stmt = insert(TableTennisLineEvent).values(rows)
        # Добавляем только новые матчи; для уже существующих в таблице меняем только статус и сбрасываем
        # отметки result_checked_1h_at / result_checked_3h_at (например, если статус был cancelled и снова стал live/scheduled).
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "status": stmt.excluded.status,
                "result_checked_1h_at": None,
                "result_checked_3h_at": None,
                "is_stale": False,
                "stale_since": None,
                "result_status": "open",
                "locked_at": None,
                "updated_at": now,
            },
        )
        await session.execute(stmt)

        await session.commit()
    logger.info("BetsAPI: saved %s events to table_tennis_line_events", len(rows))
    # После сохранения добираем коэффициенты только для тех матчей, где их ещё нет.
    event_ids = [r["id"] for r in rows]
    await _update_missing_odds(event_ids)


async def _update_missing_odds(event_ids: List[str]) -> None:
    """Добирает коэффициенты только для матчей: status=scheduled, время начала ещё не наступило, кф нет.
    Cancelled и матчи с прошедшим временем не запрашиваем."""
    if not event_ids:
        return

    now = datetime.now(timezone.utc)
    # Только scheduled и в будущем; без коэффициентов; сначала ближайшие по старту.
    async with async_session_maker() as session:
        result = await session.execute(
            TableTennisLineEvent.__table__.select()
            .where(
                TableTennisLineEvent.id.in_(event_ids),
                TableTennisLineEvent.status == LINE_EVENT_STATUS_SCHEDULED,
                TableTennisLineEvent.result_status != "locked",
                TableTennisLineEvent.starts_at > now,
                (TableTennisLineEvent.odds_1.is_(None) | TableTennisLineEvent.odds_2.is_(None)),
            )
            .order_by(TableTennisLineEvent.starts_at.asc())
        )
        rows = result.mappings().all()

    if not rows:
        return

    # Отбираем id, для которых ещё не запрашиваем коэффициенты (без дублей).
    to_fetch_ids = await _try_reserve_odds_ids([str(r["id"]) for r in rows])
    if not to_fetch_ids:
        return

    logger.info("BetsAPI: fetching odds for %s events (soonest first)", len(to_fetch_ids))

    try:
        # Параллельно запрашиваем odds, но ограничиваем число одновременных запросов.
        semaphore = asyncio.Semaphore(10)
        results: dict[str, tuple[float, float]] = {}

        async with httpx.AsyncClient() as client:
            async def fetch_one(eid: str) -> None:
                async with semaphore:
                    try:
                        odds = await _fetch_event_odds(client, eid)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("BetsAPI: failed to fetch odds for event %s: %s", eid, e)
                        return
                    if odds is None:
                        return
                    results[eid] = odds

            await asyncio.gather(*(fetch_one(eid) for eid in to_fetch_ids))

        if not results:
            return

        async with async_session_maker() as session:
            now_db = datetime.now(timezone.utc)
            for eid, (odds_1, odds_2) in results.items():
                await session.execute(
                    TableTennisLineEvent.__table__.update()
                    .where(TableTennisLineEvent.id == eid)
                    .values(odds_1=odds_1, odds_2=odds_2, updated_at=now_db)
                )
            await session.commit()
    finally:
        await _release_odds_ids(to_fetch_ids)


async def _fetch_event_odds(client: httpx.AsyncClient, event_id: str) -> tuple[float, float] | None:
    """Запрос коэффициентов для конкретного события через /event/odds.

    BetsAPI: основной рынок матча (Match Winner 2-Way) — odds_market=1.
    Возвращаем (П1, П2) или None, если не удалось распарсить.
    """
    token = (settings.betsapi_token or "").strip()
    if not token:
        return None

    params = {
        "event_id": event_id,
        "token": token,
        "odds_market": 1,  # Match Winner 2-Way
    }
    url = f"{BETSAPI_BASE_URL}/event/odds"
    r = await client.get(url, params=params, timeout=15.0)
    await _log_betsapi_request("event/odds", r.status_code, r.status_code == 200)
    if r.status_code != 200:
        logger.warning(
            "BetsAPI: non-200 status on event/odds for %s: %s %s",
            event_id,
            r.status_code,
            r.text[:200],
        )
        return None

    try:
        data = r.json()
    except ValueError:
        logger.warning("BetsAPI: invalid JSON on event/odds for %s", event_id)
        return None

    # Структура может отличаться, но в типичном ответе есть словарь букмекеров с полями home_od / away_od.
    results = data.get("results")
    if not results:
        return None

    def _find_home_away(d: Any) -> tuple[float, float] | None:
        if isinstance(d, dict):
            if "home_od" in d and "away_od" in d:
                try:
                    return float(d["home_od"]), float(d["away_od"])
                except (TypeError, ValueError):
                    return None
            for v in d.values():
                res = _find_home_away(v)
                if res is not None:
                    return res
        elif isinstance(d, list):
            for item in d:
                res = _find_home_away(item)
                if res is not None:
                    return res
        return None

    odds = _find_home_away(results)
    if odds is None:
        logger.info("BetsAPI: no match-winner odds found for event %s", event_id)
        return None
    return odds


async def _fetch_event_result(client: httpx.AsyncClient, event_id: str) -> Dict[str, Any] | None:
    """Запрос результата матча (единичный вызов для уточнения статуса/счёта).

    Используем /event (v2), который возвращает финальный статус/счёт.
    """
    token = (settings.betsapi_token or "").strip()
    if not token:
        return None

    params = {"event_id": event_id, "token": token}

    # 1) Пробуем v2 /event.
    url_v2 = f"{BETSAPI_BASE_URL}/event"
    r = await client.get(url_v2, params=params, timeout=15.0)
    await _log_betsapi_request("event", r.status_code, r.status_code == 200)
    if r.status_code == 200:
        try:
            data = r.json()
        except ValueError:
            logger.warning("BetsAPI: invalid JSON on event result for %s (v2)", event_id)
            data = {}
        results = data.get("results")
        if isinstance(results, list) and results:
            return results[0]
        if isinstance(results, dict):
            return results

    # 2) Fallback: b365api v3 /event/view (часто содержит scores для завершённых матчей).
    url_v3 = f"{BET365API_BASE_URL}/v3/event/view"
    r3 = await client.get(url_v3, params=params, timeout=15.0)
    await _log_betsapi_request("event/view", r3.status_code, r3.status_code == 200)
    if r3.status_code != 200:
        logger.warning(
            "BetsAPI: event fallback failed for %s: v2=%s, v3=%s",
            event_id,
            r.status_code,
            r3.status_code,
        )
        return None
    try:
        data3 = r3.json()
    except ValueError:
        logger.warning("BetsAPI: invalid JSON on event result for %s (v3)", event_id)
        return None
    results3 = data3.get("results")
    if isinstance(results3, list) and results3:
        return results3[0]
    if isinstance(results3, dict):
        return results3
    return None


async def _fetch_ended_events_day(client: httpx.AsyncClient, day_yyyymmdd: str, max_pages: int = 3) -> list[Dict[str, Any]]:
    """Получает завершённые события за день через v3/events/ended."""
    token = (settings.betsapi_token or "").strip()
    if not token:
        return []
    out: list[Dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        params = {
            "sport_id": settings.betsapi_table_tennis_sport_id,
            "day": day_yyyymmdd,
            "page": page,
            "token": token,
        }
        url = f"{BET365API_BASE_URL}/v3/events/ended"
        try:
            r = await client.get(url, params=params, timeout=20.0)
        except httpx.HTTPError:
            await _log_betsapi_request("events/ended", 0, False)
            break
        await _log_betsapi_request("events/ended", r.status_code, r.status_code == 200)
        if r.status_code != 200:
            break
        try:
            data = r.json()
        except ValueError:
            break
        results = data.get("results")
        if not isinstance(results, list) or not results:
            break
        out.extend([x for x in results if isinstance(x, dict)])
        # Если страница меньше 50 (типичный page size), дальше обычно пусто.
        if len(results) < 50:
            break
    return out


async def backfill_missing_sets_scores_once(limit: int = 80) -> int:
    """Дозаполняет live_score/live_sets_score для матчей, где данных по сетам ещё нет."""
    now = datetime.now(timezone.utc)
    async with async_session_maker() as session:
        result = await session.execute(
            select(TableTennisLineEvent.id, TableTennisLineEvent.starts_at)
            .where(
                TableTennisLineEvent.status.in_(
                    [
                        LINE_EVENT_STATUS_LIVE,
                        LINE_EVENT_STATUS_POSTPONED,
                        LINE_EVENT_STATUS_FINISHED,
                    ]
                ),
                (
                    TableTennisLineEvent.live_sets_score.is_(None)
                    | TableTennisLineEvent.live_score.is_(None)
                    | (sa.cast(TableTennisLineEvent.live_score, sa.Text) == "null")
                    | (sa.cast(TableTennisLineEvent.live_score, sa.Text) == "{}")
                ),
            )
            .order_by(TableTennisLineEvent.starts_at.desc())
            .limit(max(1, int(limit)))
        )
        candidates = [(str(row[0]), row[1]) for row in result.all()]

    event_ids = [eid for eid, _ in candidates]

    if not event_ids:
        return 0

    sem = asyncio.Semaphore(8)

    async def _fetch_one(client: httpx.AsyncClient, eid: str) -> tuple[str, Dict[str, Any] | None]:
        async with sem:
            try:
                return eid, await _fetch_event_result(client, eid)
            except Exception as e:  # noqa: BLE001
                logger.debug("BetsAPI backfill: failed to fetch event %s: %s", eid, e)
                return eid, None

    async with httpx.AsyncClient() as client:
        responses = await asyncio.gather(*[_fetch_one(client, eid) for eid in event_ids])

    updates: list[tuple[str, Dict[str, Any]]] = []
    updated_ids: set[str] = set()
    for eid, ev in responses:
        if not ev:
            continue
        scores = _build_live_scores_from_event(ev)
        sets_score = _derive_live_sets_score(scores, ev.get("ss")) if scores else None
        if not scores and not sets_score:
            continue
        payload: Dict[str, Any] = {"updated_at": now}
        if scores:
            payload["live_score"] = scores
            payload["last_score_changed_at"] = now
        if sets_score:
            payload["live_sets_score"] = sets_score
        updates.append((eid, payload))
        updated_ids.add(eid)

    missing_ids = {eid for eid, _ in candidates} - updated_ids
    if missing_ids:
        day_map: dict[str, set[str]] = {}
        for eid, starts_at in candidates:
            if eid not in missing_ids:
                continue
            if not isinstance(starts_at, datetime):
                continue
            day_key = starts_at.astimezone(timezone.utc).strftime("%Y%m%d")
            day_map.setdefault(day_key, set()).add(eid)

        if day_map:
            async with httpx.AsyncClient() as client:
                for day_key, ids_for_day in day_map.items():
                    ended_rows = await _fetch_ended_events_day(client, day_key, max_pages=4)
                    if not ended_rows:
                        continue
                    ended_by_id = {str(ev.get("id")): ev for ev in ended_rows if ev.get("id") is not None}
                    for eid in ids_for_day:
                        ev = ended_by_id.get(eid)
                        if not ev:
                            continue
                        scores = _build_live_scores_from_event(ev)
                        sets_score = _derive_live_sets_score(scores, ev.get("ss")) if scores else None
                        if not scores and not sets_score:
                            continue
                        payload2: Dict[str, Any] = {"updated_at": now}
                        if scores:
                            payload2["live_score"] = scores
                            payload2["last_score_changed_at"] = now
                        if sets_score:
                            payload2["live_sets_score"] = sets_score
                        updates.append((eid, payload2))
                        updated_ids.add(eid)

    if not updates:
        updated_count = 0
    else:
        async with async_session_maker() as session:
            for eid, payload in updates:
                await session.execute(
                    TableTennisLineEvent.__table__.update()
                    .where(TableTennisLineEvent.id == eid)
                    .values(**payload)
                )
            await session.commit()
        updated_count = len(updates)

    # Жёсткая нормализация только для finished: в live нельзя подставлять пустой счёт,
    # иначе можно потерять ранее полученные сеты.
    async with async_session_maker() as session:
        fallback_result = await session.execute(
            sa.text(
                """
                UPDATE table_tennis_line_events
                SET
                  live_sets_score = COALESCE(live_sets_score, '0-0'),
                  live_score = CASE
                    WHEN live_score IS NULL OR live_score::text = 'null' THEN '{}'::json
                    ELSE live_score
                  END,
                  updated_at = :now
                WHERE status IN ('finished')
                  AND (live_sets_score IS NULL OR live_score IS NULL OR live_score::text = 'null')
                """
            ),
            {"now": now},
        )
        await session.commit()
    fallback_count = int(fallback_result.rowcount or 0)

    total_updated = updated_count + fallback_count
    logger.info(
        "BetsAPI backfill: updated sets data for %s matches (api=%s, fallback=%s)",
        total_updated,
        updated_count,
        fallback_count,
    )
    return total_updated


async def check_past_matches_results_once() -> None:
    """Один проход:

    - авто-завершение матчей, где счёт по сетам не менялся >=15 минут, и у кого-то уже достаточно выигранных сетов;
    - однократная проверка результата через 2 часа и (опционально) через 3 часа после планового начала.
    """
    now = datetime.now(timezone.utc)
    fifteen_minutes_ago = now - timedelta(minutes=15)
    two_hours_ago = now - timedelta(hours=2)
    three_hours_ago = now - timedelta(hours=3)
    rules_map = await _load_league_rules_map()

    async with async_session_maker() as session:
        # 0. Авто-завершение «зависших» матчей:
        # прошло >=15 минут, счёт по сетам не менялся >=15 минут, есть победитель по сетам,
        # но статус ещё не finished. Считаем, что матч завершён, и помечаем победителя по сетовому счёту.
        q_stuck = (
            TableTennisLineEvent.__table__.select()
            .where(
                TableTennisLineEvent.starts_at <= fifteen_minutes_ago,
                TableTennisLineEvent.status.in_(
                    [LINE_EVENT_STATUS_SCHEDULED, LINE_EVENT_STATUS_LIVE, LINE_EVENT_STATUS_POSTPONED]
                ),
                TableTennisLineEvent.result_status != "locked",
                TableTennisLineEvent.live_sets_score.is_not(None),
            )
        )
        stuck_rows = (await session.execute(q_stuck)).mappings().all()
        for row in stuck_rows:
            sets_score = row.get("live_sets_score") or ""
            try:
                p1, p2 = sets_score.split("-", 1)
                wins_home = int(p1)
                wins_away = int(p2)
            except Exception:
                continue
            league_id = str(row.get("league_id") or "")
            league_rules = rules_map.get(league_id, {})
            required_wins = int(league_rules.get("max_sets_wins", 3))
            stale_after_minutes = int(league_rules.get("stale_after_minutes", 25))
            if required_wins <= 0:
                continue
            has_in_progress_set = _has_in_progress_set_fragment(row.get("live_score"))

            # Если матч "живой", но явного победителя по завершённым сетам ещё нет — считаем данные stale
            # только при длительном отсутствии изменений.
            if max(wins_home, wins_away) < required_wins:
                last_changed = row.get("last_score_changed_at")
                if isinstance(last_changed, datetime) and last_changed <= (now - timedelta(minutes=stale_after_minutes)):
                    await session.execute(
                        TableTennisLineEvent.__table__.update()
                        .where(TableTennisLineEvent.id == row["id"])
                        .values(
                            is_stale=True,
                            stale_since=row.get("stale_since") or now,
                            updated_at=now,
                        )
                    )
                continue
            # Если кто-то уже набрал нужное количество побед по сетам и нет фрагмента
            # незавершённого текущего сета — матч считаем завершённым.
            if (wins_home >= required_wins or wins_away >= required_wins) and not has_in_progress_set:
                await session.execute(
                    TableTennisLineEvent.__table__.update()
                    .where(TableTennisLineEvent.id == row["id"])
                    .values(
                        status=LINE_EVENT_STATUS_FINISHED,
                        finished_at=row.get("finished_at") or now,
                        is_stale=False,
                        stale_since=None,
                        updated_at=now,
                    )
                )

        # Матчи, где нужно сделать 2-часовую проверку.
        # Приоритет: только те, по которым есть V2-прематч‑прогноз.
        q1 = (
            select(TableTennisLineEvent.id)
            .join(
                TableTennisForecastV2,
                TableTennisForecastV2.event_id == TableTennisLineEvent.id,
            )
            .where(
                TableTennisLineEvent.starts_at <= two_hours_ago,
                TableTennisLineEvent.result_status != "locked",
                TableTennisLineEvent.result_checked_1h_at.is_(None),
            )
        )
        # Матчи, где нужно сделать 3-часовую проверку (также только с прогнозами).
        q3 = (
            select(TableTennisLineEvent.id)
            .join(
                TableTennisForecastV2,
                TableTennisForecastV2.event_id == TableTennisLineEvent.id,
            )
            .where(
                TableTennisLineEvent.starts_at <= three_hours_ago,
                TableTennisLineEvent.result_status != "locked",
                TableTennisLineEvent.result_checked_3h_at.is_(None),
            )
        )
        r1 = await session.execute(q1)
        r3 = await session.execute(q3)
        ids_1h = {str(row[0]) for row in r1.all()}
        ids_3h = {str(row[0]) for row in r3.all()}
        await session.commit()

    to_check: Dict[str, Dict[str, bool]] = {}
    for eid in ids_1h:
        to_check.setdefault(eid, {})["h1"] = True
    for eid in ids_3h:
        to_check.setdefault(eid, {})["h3"] = True

    if not to_check:
        return

    logger.info(
        "BetsAPI: result-check pass, %s matches for 1h and/or 3h checks",
        len(to_check),
    )

    async with httpx.AsyncClient() as client, async_session_maker() as session:
        for eid, flags in to_check.items():
            try:
                ev = await _fetch_event_result(client, eid)
            except Exception as e:  # noqa: BLE001
                logger.warning("BetsAPI: failed to fetch event result for %s: %s", eid, e)
                continue

            now_local = datetime.now(timezone.utc)
            update_values: Dict[str, Any] = {
                "updated_at": now_local,
            }
            # Обновляем статус по time_status, если есть
            if ev is not None:
                # /event не всегда содержит ровно ту же структуру, что /events/upcoming.
                # Нас интересует только time_status (статус матча) и, если есть, счёт по сетам.
                time_status = ev.get("time_status")
                try:
                    ts_int = int(time_status) if time_status is not None else 0
                except (TypeError, ValueError):
                    ts_int = 0
                status = _TIME_STATUS_MAP.get(ts_int, LINE_EVENT_STATUS_SCHEDULED)
                update_values["status"] = status
                if status == LINE_EVENT_STATUS_FINISHED:
                    update_values["finished_at"] = now_local
                    # Через 2ч сверки считаем матч "зафиксированным".
                    if flags.get("h1"):
                        update_values["result_status"] = "locked"
                        update_values["locked_at"] = now_local
                # Если в ответе результата есть scores — обновим и live_score/live_sets_score.
                scores = _build_live_scores_from_event(ev)
                if scores:
                    sets_score = _derive_live_sets_score(scores, ev.get("ss"))
                    if sets_score:
                        update_values["live_sets_score"] = sets_score
                    update_values["live_score"] = scores
                    update_values["last_score_changed_at"] = now_local
                    update_values["is_stale"] = False
                    update_values["stale_since"] = None
                elif status == LINE_EVENT_STATUS_FINISHED:
                    # У finished не держим JSON null в детализации сетов.
                    update_values["live_score"] = {}
                    if not update_values.get("live_sets_score"):
                        update_values["live_sets_score"] = "0-0"

            if flags.get("h1"):
                update_values["result_checked_1h_at"] = now_local
            if flags.get("h3"):
                update_values["result_checked_3h_at"] = now_local

            await session.execute(
                TableTennisLineEvent.__table__.update()
                .where(TableTennisLineEvent.id == eid)
                .values(**update_values)
            )

            # После обновления статуса/счёта попробуем зарезолвить прогноз по этому матчу.
            ev_obj_result = await session.execute(
                select(TableTennisLineEvent).where(TableTennisLineEvent.id == eid)
            )
            ev_obj = ev_obj_result.scalar_one_or_none()
            if ev_obj is not None:
                await update_forecast_outcome_for_event(session, ev_obj)

        await session.commit()


async def update_line_missing_odds_once() -> None:
    """Один проход: для всех матчей линии без коэффициентов (scheduled, в будущем) запросить odds."""
    now = datetime.now(timezone.utc)
    async with async_session_maker() as session:
        result = await session.execute(
            select(TableTennisLineEvent.id).where(
                TableTennisLineEvent.status == LINE_EVENT_STATUS_SCHEDULED,
                TableTennisLineEvent.starts_at > now,
                (TableTennisLineEvent.odds_1.is_(None) | TableTennisLineEvent.odds_2.is_(None)),
            ).order_by(TableTennisLineEvent.starts_at.asc())
        )
        event_ids = [str(r[0]) for r in result.all()]
    if not event_ids:
        return
    await _update_missing_odds(event_ids)


async def sync_forecast_outcomes_once(limit: int = 200) -> int:
    """Синхронизирует статусы прогнозов с основной таблицей событий.

    Берём pending‑прогнозы и соответствующие им матчи, у которых статус уже finished/cancelled,
    и вызываем update_forecast_outcome_for_event. Ограничиваемся батчем limit за один проход.
    """
    async with async_session_maker() as session:
        ids_result = await session.execute(
            select(TableTennisLineEvent.id)
            .join(
                TableTennisForecastV2,
                TableTennisForecastV2.event_id == TableTennisLineEvent.id,
            )
            .where(
                sa.or_(
                    sa.and_(
                        TableTennisForecastV2.status == "pending",
                        sa.or_(
                            TableTennisLineEvent.status.in_(
                                [LINE_EVENT_STATUS_FINISHED, LINE_EVENT_STATUS_CANCELLED]
                            ),
                            TableTennisLineEvent.live_sets_score.is_not(None),
                        ),
                    ),
                    sa.and_(
                        TableTennisForecastV2.status.in_(["cancelled", "no_result"]),
                        TableTennisLineEvent.status.in_(
                            [
                                LINE_EVENT_STATUS_SCHEDULED,
                                LINE_EVENT_STATUS_LIVE,
                                LINE_EVENT_STATUS_POSTPONED,
                            ]
                        ),
                    ),
                )
            )
            .group_by(TableTennisLineEvent.id)
            .limit(max(1, int(limit)))
        )
        ids = [str(r[0]) for r in ids_result.all()]
        if not ids:
            return 0
        result = await session.execute(
            select(TableTennisLineEvent).where(TableTennisLineEvent.id.in_(ids))
        )
        events = list(result.scalars().all())
        if not events:
            return 0

        for ev in events:
            await update_forecast_outcome_for_event(session, ev)
        await session.commit()

    logger.info("BetsAPI forecasts sync: updated outcomes for %s events", len(events))
    return len(events)


async def sync_results_from_archive_range_once(
    date_from: date,
    date_to: date,
    only_forecasted: bool = True,
    max_pages_per_day: int = 6,
) -> dict[str, int]:
    """Дозаполняет результаты из архива /v3/events/ended по диапазону дней.

    При only_forecasted=True обрабатывает только матчи, по которым есть pending‑прогноз.
    """
    if date_from > date_to:
        date_from, date_to = date_to, date_from

    async with async_session_maker() as session:
        base_stmt = select(TableTennisLineEvent.id).where(
            TableTennisLineEvent.starts_at >= datetime(
                date_from.year, date_from.month, date_from.day, tzinfo=timezone.utc
            ),
            TableTennisLineEvent.starts_at < datetime(
                date_to.year, date_to.month, date_to.day, tzinfo=timezone.utc
            )
            + timedelta(days=1),
            TableTennisLineEvent.result_status != "locked",
        )
        if only_forecasted:
            base_stmt = (
                base_stmt.join(
                    TableTennisForecastV2,
                    TableTennisForecastV2.event_id == TableTennisLineEvent.id,
                )
                .where(TableTennisForecastV2.status.in_(["pending", "cancelled", "no_result"]))
                .group_by(TableTennisLineEvent.id)
            )
        events_result = await session.execute(base_stmt)
        target_ids = [str(r[0]) for r in events_result.all()]
        if target_ids:
            rows_result = await session.execute(
                select(TableTennisLineEvent).where(TableTennisLineEvent.id.in_(target_ids))
            )
            target_events = list(rows_result.scalars().all())
        else:
            target_events = []
        if not target_events:
            return {"targets": 0, "matched": 0, "resolved": 0}

        events_map: dict[str, TableTennisLineEvent] = {str(e.id): e for e in target_events if e.id}

    day = date_from
    archive_by_id: dict[str, dict[str, Any]] = {}
    async with httpx.AsyncClient() as client:
        while day <= date_to:
            day_key = day.strftime("%Y%m%d")
            rows = await _fetch_ended_events_day(
                client,
                day_key,
                max_pages=max(1, int(max_pages_per_day)),
            )
            for ev in rows:
                eid = str(ev.get("id") or "")
                if eid:
                    archive_by_id[eid] = ev
            day = day + timedelta(days=1)

    matched_ids = [eid for eid in events_map.keys() if eid in archive_by_id]
    if not matched_ids:
        return {"targets": len(events_map), "matched": 0, "resolved": 0}

    resolved = 0
    now = datetime.now(timezone.utc)
    async with async_session_maker() as session:
        rows_result = await session.execute(
            select(TableTennisLineEvent).where(TableTennisLineEvent.id.in_(matched_ids))
        )
        rows = list(rows_result.scalars().all())
        for row in rows:
            ev = archive_by_id.get(str(row.id))
            if not ev:
                continue
            scores = _build_live_scores_from_event(ev)
            sets_score = _derive_live_sets_score(scores, ev.get("ss")) if scores else None

            row.status = LINE_EVENT_STATUS_FINISHED
            if row.finished_at is None:
                row.finished_at = now
            if scores:
                row.live_score = scores
            elif row.live_score is None:
                row.live_score = {}
            if sets_score:
                row.live_sets_score = sets_score
            elif row.live_sets_score is None:
                row.live_sets_score = "0-0"
            row.updated_at = now

            await update_forecast_outcome_for_event(session, row)
            resolved += 1

        await session.commit()

    return {"targets": len(events_map), "matched": len(matched_ids), "resolved": resolved}


async def load_archive_to_main(
    days_back: int = 90,
    max_pages_per_day: int = 10,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, int]:
    """Загружает завершённые матчи из архива BetsAPI в main DB (table_tennis_line_events).

    Используется для первичного наполнения: линия даёт только upcoming, архив — finished.
    Без этого ML-таблицы остаются пустыми (sync читает только finished с live_sets_score).

    Если заданы date_from/date_to — используются они; иначе days_back от сегодня.
    """
    token = (settings.betsapi_token or "").strip()
    if not token:
        logger.warning("BetsAPI: BETSAPI_TOKEN не задан — load_archive_to_main пропущен")
        return {"inserted": 0, "updated": 0, "skipped": 0}

    today = datetime.now(timezone.utc).date()
    if date_from is not None and date_to is not None:
        pass  # используем переданные даты
    else:
        date_from = today - timedelta(days=max(1, days_back))
        date_to = today

    all_events: list[Dict[str, Any]] = []
    async with httpx.AsyncClient() as client:
        day = date_from
        while day <= date_to:
            day_key = day.strftime("%Y%m%d")
            rows = await _fetch_ended_events_day(
                client,
                day_key,
                max_pages=max(1, int(max_pages_per_day)),
            )
            all_events.extend(rows)
            day = day + timedelta(days=1)
            await asyncio.sleep(0.3)

    if not all_events:
        return {"inserted": 0, "updated": 0, "skipped": 0}

    now = datetime.now(timezone.utc)
    rows_to_save: list[Dict[str, Any]] = []
    for ev in all_events:
        row = _parse_event_for_db(ev)
        if not row:
            continue
        scores = _build_live_scores_from_event(ev)
        sets_score = _derive_live_sets_score(scores or {}, ev.get("ss"))
        row["status"] = LINE_EVENT_STATUS_FINISHED
        row["live_score"] = scores if scores else {}
        row["live_sets_score"] = sets_score if sets_score else "0-0"
        row["finished_at"] = now
        row["last_score_changed_at"] = now
        if not row.get("live_sets_score") or row["live_sets_score"] == "0-0":
            continue
        rows_to_save.append(row)

    if not rows_to_save:
        return {"inserted": 0, "updated": 0, "skipped": len(all_events)}

    leagues_seen: Dict[str, str] = {}
    players_seen: Dict[str, str] = {}
    for r in rows_to_save:
        if r.get("league_id"):
            leagues_seen[r["league_id"]] = r.get("league_name", "—")
        if r.get("home_id"):
            players_seen[r["home_id"]] = r.get("home_name", "—")
        if r.get("away_id"):
            players_seen[r["away_id"]] = r.get("away_name", "—")

    inserted = 0
    updated = 0
    async with async_session_maker() as session:
        if leagues_seen:
            league_rows = [
                {"id": lid, "name": name, "updated_at": now}
                for lid, name in leagues_seen.items()
            ]
            stmt_league = insert(TableTennisLeague).values(league_rows)
            stmt_league = stmt_league.on_conflict_do_nothing(index_elements=["id"])
            await session.execute(stmt_league)
        if players_seen:
            player_rows = [
                {"id": pid, "name": name, "updated_at": now}
                for pid, name in players_seen.items()
            ]
            stmt_player = insert(TableTennisPlayer).values(player_rows)
            stmt_player = stmt_player.on_conflict_do_nothing(index_elements=["id"])
            await session.execute(stmt_player)

        existing_result = await session.execute(
            select(TableTennisLineEvent.id, TableTennisLineEvent.live_sets_score).where(
                TableTennisLineEvent.id.in_([r["id"] for r in rows_to_save])
            )
        )
        existing_map = {str(r[0]): r[1] for r in existing_result.all()}

        for r in rows_to_save:
            eid = r["id"]
            has_sets = bool(r.get("live_sets_score") and r["live_sets_score"] != "0-0")
            if not has_sets:
                continue
            if eid in existing_map:
                if existing_map[eid]:
                    continue
                await session.execute(
                    TableTennisLineEvent.__table__.update()
                    .where(TableTennisLineEvent.id == eid)
                    .values(
                        status=LINE_EVENT_STATUS_FINISHED,
                        live_score=r.get("live_score") or {},
                        live_sets_score=r["live_sets_score"],
                        finished_at=now,
                        last_score_changed_at=now,
                        updated_at=now,
                    )
                )
                updated += 1
            else:
                stmt = insert(TableTennisLineEvent).values(r)
                stmt = stmt.on_conflict_do_nothing(index_elements=["id"])
                await session.execute(stmt)
                inserted += 1

        await session.commit()
    logger.info(
        "BetsAPI load_archive_to_main: inserted=%s, updated=%s, total_events=%s",
        inserted,
        updated,
        len(rows_to_save),
    )
    return {"inserted": inserted, "updated": updated, "skipped": len(all_events) - inserted - updated}


def get_cached_line() -> Dict[str, Any]:
    """Возвращает кэшированную линию и агрегаты: события, лиги, игроки по лигам.
    Формат: { "events": [...], "leagues": [{"id", "name"}], "players_by_league": [{"league_id", "league_name", "players": [{"id", "name"}]}], "updated_at": unix? }
    """
    events = _line_cache.get("events") or []
    updated_at = _line_cache.get("updated_at")

    leagues_map: Dict[str, Dict[str, Any]] = {}
    players_by_league: Dict[str, Dict[str, Any]] = {}

    for ev in events:
        league = ev.get("league") if isinstance(ev.get("league"), dict) else {}
        league_id = str(league.get("id") or "")
        league_name = (league.get("name") or "").strip() or "—"
        if league_id:
            leagues_map[league_id] = {"id": league_id, "name": league_name}
        if league_id not in players_by_league:
            players_by_league[league_id] = {"league_id": league_id, "league_name": league_name, "players": {}}
        pl_map = players_by_league[league_id]["players"]
        for side in ("home", "away"):
            team = ev.get(side) if isinstance(ev.get(side), dict) else {}
            tid = str(team.get("id") or "")
            tname = (team.get("name") or "").strip() or "—"
            if tid:
                pl_map[tid] = {"id": tid, "name": tname}
        players_by_league[league_id]["players"] = pl_map

    leagues = list(leagues_map.values())
    players_by_league_list = [
        {"league_id": k, "league_name": v["league_name"], "players": list(v["players"].values())}
        for k, v in sorted(players_by_league.items(), key=lambda x: (x[1]["league_name"], x[0]))
    ]

    normalized_events = []
    for ev in events:
        league = ev.get("league") if isinstance(ev.get("league"), dict) else {}
        home = ev.get("home") if isinstance(ev.get("home"), dict) else {}
        away = ev.get("away") if isinstance(ev.get("away"), dict) else {}
        # Коэффициенты на победу 1 / победу 2 (пока из API не подтягиваем — отдельный запрос odds на каждый матч)
        odds_1 = ev.get("odds_1")
        odds_2 = ev.get("odds_2")
        if odds_1 is not None and not isinstance(odds_1, (int, float)):
            odds_1 = None
        if odds_2 is not None and not isinstance(odds_2, (int, float)):
            odds_2 = None
        normalized_events.append({
            "id": ev.get("id"),
            "league_id": str(league.get("id") or ""),
            "league_name": (league.get("name") or "").strip() or "—",
            "home_id": str(home.get("id") or ""),
            "home_name": (home.get("name") or "").strip() or "—",
            "away_id": str(away.get("id") or ""),
            "away_name": (away.get("name") or "").strip() or "—",
            "time": ev.get("time"),
            "odds_1": float(odds_1) if odds_1 is not None else None,
            "odds_2": float(odds_2) if odds_2 is not None else None,
        })

    return {
        "events": normalized_events,
        "leagues": leagues,
        "players_by_league": players_by_league_list,
        "updated_at": updated_at,
    }


async def table_tennis_line_loop() -> None:
    """Фоновый цикл: периодически опрашивает BetsAPI и пишет лог.

    На следующем шаге сюда можно добавить сохранение в БД и рассылку обновлений на фронт.
    """
    interval = max(10, settings.betsapi_table_tennis_line_interval_sec)
    token = (settings.betsapi_token or "").strip()
    if not token:
        logger.warning(
            "BetsAPI: betsapi_token не задан, фоновый опрос линии настольного тенниса отключён."
        )
        return

    logger.info(
        "BetsAPI: starting table tennis line producer (interval=%ss, sport_id=%s)",
        interval,
        settings.betsapi_table_tennis_sport_id,
    )

    while True:
        try:
            await fetch_table_tennis_line_once()
        except Exception as e:  # noqa: BLE001
            logger.exception("BetsAPI: unexpected error in line loop: %s", e)
        await asyncio.sleep(interval)


async def table_tennis_odds_loop() -> None:
    """Фоновый цикл: периодически проходим по матчам без коэффициентов и запрашиваем odds."""
    interval = max(60, settings.betsapi_table_tennis_odds_interval_sec)
    token = (settings.betsapi_token or "").strip()
    if not token:
        logger.warning(
            "BetsAPI: betsapi_token не задан, фоновый опрос коэффициентов линии отключён."
        )
        return

    logger.info(
        "BetsAPI: starting table tennis odds loop (interval=%ss)",
        interval,
    )

    while True:
        try:
            await update_line_missing_odds_once()
        except Exception as e:  # noqa: BLE001
            logger.exception("BetsAPI: unexpected error in odds loop: %s", e)
        await asyncio.sleep(interval)


async def table_tennis_live_loop() -> None:
    """Фоновый цикл: периодически опрашивает inplay-события и обновляет статусы матчей (live/finished/cancelled)."""
    forecast_interval = max(3, settings.betsapi_table_tennis_live_interval_forecast_sec)
    other_interval = max(forecast_interval, settings.betsapi_table_tennis_live_interval_other_sec)
    interval = forecast_interval
    token = (settings.betsapi_token or "").strip()
    if not token:
        logger.warning(
            "BetsAPI: betsapi_token не задан, фоновый опрос лайв-событий отключён."
        )
        return

    logger.info(
        "BetsAPI: starting table tennis live loop (forecast=%ss, other=%ss)",
        forecast_interval,
        other_interval,
    )
    backfill_interval_sec = max(30, interval * 12)
    last_backfill_ts = 0.0
    archive_interval_sec = max(60, settings.betsapi_table_tennis_archive_sync_interval_sec)
    last_archive_sync_ts = 0.0
    cancel_recheck_interval_sec = max(30, settings.betsapi_table_tennis_cancel_forecast_recheck_interval_sec)
    last_cancel_recheck_ts = 0.0
    other_every_n = max(1, int(round(other_interval / interval)))
    tick = 0

    while True:
        try:
            tick += 1
            update_non_forecast_scores = (tick % other_every_n) == 0
            await update_line_live_status_once(
                update_non_forecast_scores=update_non_forecast_scores
            )
            # Дополнительно синхронизируем статусы прогнозов для уже завершённых матчей.
            try:
                await sync_forecast_outcomes_once(limit=200)
            except Exception as e:  # noqa: BLE001
                logger.exception("BetsAPI: error during forecast outcomes sync: %s", e)
            try:
                await repair_cancelled_with_scores_once(limit=200)
            except Exception as e:  # noqa: BLE001
                logger.exception("BetsAPI: error during cancelled->finished repair: %s", e)
            now_ts = time.monotonic()
            if now_ts - last_archive_sync_ts >= archive_interval_sec:
                today = datetime.now(timezone.utc).date()
                yesterday = today - timedelta(days=1)
                try:
                    # only_forecasted=False: подтягиваем результаты по всем матчам в диапазоне,
                    # иначе после очистки прогнозов или для матчей без прогноза результаты не обновляются
                    archive_res = await sync_results_from_archive_range_once(
                        date_from=yesterday,
                        date_to=today,
                        only_forecasted=False,
                        max_pages_per_day=6,
                    )
                    logger.info("BetsAPI archive sync (today/yesterday): %s", archive_res)
                except Exception as e:  # noqa: BLE001
                    logger.exception("BetsAPI: archive sync error: %s", e)
                last_archive_sync_ts = now_ts
            if now_ts - last_cancel_recheck_ts >= cancel_recheck_interval_sec:
                try:
                    recheck_res = await revalidate_cancelled_forecast_events_once(limit=120)
                    if recheck_res.get("updated_by_event", 0) or recheck_res.get("updated_by_archive", 0):
                        logger.info("BetsAPI cancelled recheck: %s", recheck_res)
                except Exception as e:  # noqa: BLE001
                    logger.exception("BetsAPI: cancelled forecast recheck error: %s", e)
                last_cancel_recheck_ts = now_ts
            if now_ts - last_backfill_ts >= backfill_interval_sec:
                await backfill_missing_sets_scores_once(limit=120)
                last_backfill_ts = now_ts
        except Exception as e:  # noqa: BLE001
            logger.exception("BetsAPI: unexpected error in live loop: %s", e)
        await asyncio.sleep(interval)


async def table_tennis_results_loop() -> None:
    """Фоновый цикл: раз в N секунд (по умолчанию 30 минут) проверяет матчи и однократно запрашивает результат.

    - первый раз ~через час после планового начала;
    - второй раз ~через 3 часа после планового начала.
    """
    interval = max(300, settings.betsapi_table_tennis_result_check_interval_sec)
    token = (settings.betsapi_token or "").strip()
    if not token:
        logger.warning(
            "BetsAPI: betsapi_token не задан, фоновая проверка результатов матчей отключена."
        )
        return

    logger.info(
        "BetsAPI: starting table tennis results loop (interval=%ss)",
        interval,
    )

    while True:
        try:
            await check_past_matches_results_once()
        except Exception as e:  # noqa: BLE001
            logger.exception("BetsAPI: unexpected error in results loop: %s", e)
        await asyncio.sleep(interval)

