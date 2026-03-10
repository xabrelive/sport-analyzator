"""API: настольный теннис — линия (из БД, заполняется воркером BetsAPI)."""
import asyncio
import json
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
import sqlalchemy as sa
from sqlalchemy import select, or_, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_async_session, async_session_maker
from app.models.table_tennis_line_event import (
    TableTennisLineEvent,
    LINE_EVENT_STATUS_SCHEDULED,
    LINE_EVENT_STATUS_LIVE,
    LINE_EVENT_STATUS_FINISHED,
)
from app.services.betsapi_table_tennis import (
    backfill_missing_sets_scores_once,
    backfill_forecasts_from_existing_events_once,
    sync_results_from_archive_range_once,
    revalidate_cancelled_forecast_events_once,
)
from app.services.table_tennis_analytics import load_player_stats, build_strengths_weaknesses
from app.models.table_tennis_forecast import TableTennisForecast

router = APIRouter()


def _sanitize_page(page: int) -> int:
    return max(1, int(page or 1))


def _sanitize_page_size(page_size: int, max_size: int = 100) -> int:
    return max(1, min(int(page_size or 20), max_size))


def _parse_date_start_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        day = datetime.fromisoformat(raw).date()
    except ValueError:
        return None
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def _parse_date_end_utc_exclusive(value: str | None) -> datetime | None:
    start = _parse_date_start_utc(value)
    if start is None:
        return None
    return start + timedelta(days=1)


def _parse_sets_score(value: str | None) -> tuple[int | None, int | None]:
    if not value or "-" not in value:
        return None, None
    left, right = value.split("-", 1)
    try:
        return int(left), int(right)
    except (TypeError, ValueError):
        return None, None


def _event_to_dict(r: TableTennisLineEvent) -> dict:
    return {
        "id": r.id,
        "league_id": r.league_id,
        "league_name": r.league_name,
        "home_id": r.home_id,
        "home_name": r.home_name,
        "away_id": r.away_id,
        "away_name": r.away_name,
        "time": int(r.starts_at.timestamp()) if r.starts_at else None,
        "status": r.status,
        "odds_1": float(r.odds_1) if r.odds_1 is not None else None,
        "odds_2": float(r.odds_2) if r.odds_2 is not None else None,
        "forecast": r.forecast,
        "forecast_confidence": float(r.forecast_confidence) if r.forecast_confidence is not None else None,
        "sets_score": r.live_sets_score,
        "sets": r.live_score or {},
        "finished_at": int(r.finished_at.timestamp()) if r.finished_at else None,
        "last_score_changed_at": int(r.last_score_changed_at.timestamp()) if r.last_score_changed_at else None,
        "is_stale": bool(r.is_stale),
        "result_status": r.result_status,
    }


def _build_player_stats(player_id: str, rows: list[TableTennisLineEvent], now: datetime) -> dict:
    wins = 0
    losses = 0
    finished = 0
    upcoming = 0
    leagues = set()
    for r in rows:
        leagues.add((r.league_id, r.league_name))
        is_home = r.home_id == player_id
        if r.status == LINE_EVENT_STATUS_FINISHED:
            finished += 1
            h, a = _parse_sets_score(r.live_sets_score)
            if h is None or a is None:
                continue
            if is_home and h > a:
                wins += 1
            elif (not is_home) and a > h:
                wins += 1
            elif h != a:
                losses += 1
        elif r.status == LINE_EVENT_STATUS_SCHEDULED and r.starts_at and r.starts_at > now:
            upcoming += 1
    return {
        "total_matches": len(rows),
        "finished_matches": finished,
        "wins": wins,
        "losses": losses,
        "win_rate": round((wins / finished) * 100, 2) if finished else None,
        "upcoming_matches": upcoming,
        "leagues_count": len(leagues),
    }


def _build_match_justification(
    match: TableTennisLineEvent,
    home_stats: dict,
    away_stats: dict,
    h2h: dict | None,
) -> str | None:
    """Короткое текстовое обоснование прогноза по матчу."""
    parts: list[str] = []
    hn = home_stats.get("finished_matches") or 0
    an = away_stats.get("finished_matches") or 0
    hw = home_stats.get("wins") or 0
    aw = away_stats.get("wins") or 0
    hw_pct = home_stats.get("win_rate")
    aw_pct = away_stats.get("win_rate")

    if hn or an:
        parts.append(
            f"Статистика по матчам: {match.home_name} — {hn} игр, {hw} побед; "
            f"{match.away_name} — {an} игр, {aw} побед."
        )
    if hw_pct is not None or aw_pct is not None:
        parts.append(
            f"Winrate: {match.home_name} — {hw_pct if hw_pct is not None else '–'}%, "
            f"{match.away_name} — {aw_pct if aw_pct is not None else '–'}%."
        )
    if h2h and h2h.get("total"):
        parts.append(
          f"Личные встречи: {match.home_name} {h2h.get('home_wins', 0)}–{h2h.get('away_wins', 0)} {match.away_name} "
          f"за {h2h['total']} матч(ей)."
        )
    if not parts:
        return None
    return " ".join(parts)


def _build_line_response(rows: list) -> dict:
    """Собирает ответ с событиями, лигами и игроками по лигам."""
    events = []
    leagues_map = {}
    players_by_league = {}

    for r in rows:
        league_id = r.league_id or ""
        league_name = r.league_name or "—"
        if league_id:
            leagues_map[league_id] = {"id": league_id, "name": league_name}
        if league_id not in players_by_league:
            players_by_league[league_id] = {
                "league_id": league_id,
                "league_name": league_name,
                "players": {},
            }
        pl = players_by_league[league_id]["players"]
        if r.home_id:
            pl[r.home_id] = {"id": r.home_id, "name": r.home_name or "—"}
        if r.away_id:
            pl[r.away_id] = {"id": r.away_id, "name": r.away_name or "—"}
        events.append({
            "id": r.id,
            "league_id": league_id,
            "league_name": league_name,
            "home_id": r.home_id,
            "home_name": r.home_name or "—",
            "away_id": r.away_id,
            "away_name": r.away_name or "—",
            "time": int(r.starts_at.timestamp()) if r.starts_at else None,
            "status": r.status,
            "odds_1": float(r.odds_1) if r.odds_1 is not None else None,
            "odds_2": float(r.odds_2) if r.odds_2 is not None else None,
            "forecast": r.forecast,
        })

    leagues = list(leagues_map.values())
    players_by_league_list = [
        {"league_id": k, "league_name": v["league_name"], "players": list(v["players"].values())}
        for k, v in sorted(players_by_league.items(), key=lambda x: (x[1]["league_name"], x[0]))
    ]
    updated_at = rows[0].updated_at.timestamp() if rows else None
    return {
        "events": events,
        "leagues": leagues,
        "players_by_league": players_by_league_list,
        "updated_at": updated_at,
    }


@router.get("/live")
async def get_table_tennis_live(session: AsyncSession = Depends(get_async_session)):
    """Лайв: матчи со статусом live, а также finished — но только в течение 5 минут после завершения."""
    now = datetime.now(timezone.utc)
    five_minutes_ago = now - timedelta(minutes=5)
    live_freshness_cutoff = now - timedelta(minutes=15)
    result = await session.execute(
        select(TableTennisLineEvent).where(
            or_(
                and_(
                    TableTennisLineEvent.status == LINE_EVENT_STATUS_LIVE,
                    TableTennisLineEvent.is_stale.is_(False),
                    or_(
                        TableTennisLineEvent.last_score_changed_at >= live_freshness_cutoff,
                        TableTennisLineEvent.starts_at >= live_freshness_cutoff,
                    ),
                ),
                and_(
                    TableTennisLineEvent.status == LINE_EVENT_STATUS_FINISHED,
                    or_(
                        and_(
                            TableTennisLineEvent.finished_at.is_not(None),
                            TableTennisLineEvent.finished_at >= five_minutes_ago,
                        ),
                        and_(
                            TableTennisLineEvent.finished_at.is_(None),
                            TableTennisLineEvent.updated_at >= five_minutes_ago,
                        ),
                    ),
                ),
            )
        ).order_by(TableTennisLineEvent.starts_at)
    )
    rows = list(result.scalars().all())
    return _build_live_response(rows)


def _build_live_response(rows: list[TableTennisLineEvent]) -> dict:
    events = []
    for r in rows:
        events.append(
            {
                "id": r.id,
                "league_id": r.league_id,
                "league_name": r.league_name,
                "home_id": r.home_id,
                "home_name": r.home_name,
                "away_id": r.away_id,
                "away_name": r.away_name,
                "time": int(r.starts_at.timestamp()) if r.starts_at else None,
                "status": r.status,
                "odds_1": float(r.odds_1) if r.odds_1 is not None else None,
                "odds_2": float(r.odds_2) if r.odds_2 is not None else None,
                "forecast": r.forecast,
                "sets_score": r.live_sets_score,
                "sets": r.live_score or {},
                "last_score_changed_at": int(r.last_score_changed_at.timestamp()) if r.last_score_changed_at else None,
                "is_stale": bool(r.is_stale),
            }
        )
    return {"events": events, "updated_at": (rows[0].updated_at.timestamp() if rows else None)}


@router.get("/debug/betsapi-stats")
async def get_betsapi_stats(session: AsyncSession = Depends(get_async_session)):
    """Отладочная статистика: сколько запросов в BetsAPI ушло за последние 5/10/30/60 минут."""
    now = datetime.now(timezone.utc)
    windows = {
        "5m": now - timedelta(minutes=5),
        "10m": now - timedelta(minutes=10),
        "30m": now - timedelta(minutes=30),
        "60m": now - timedelta(minutes=60),
    }

    stats: dict[str, dict[str, int]] = {}
    for label, since in windows.items():
        result = await session.execute(
            sa.text(
                """
                SELECT endpoint, COUNT(*) AS cnt
                FROM betsapi_request_logs
                WHERE created_at >= :since
                GROUP BY endpoint
                """
            ),
            {"since": since},
        )
        rows = result.mappings().all()
        stats[label] = {str(r["endpoint"]): int(r["cnt"]) for r in rows}

    return {"now": int(now.timestamp()), "windows": stats}


@router.post("/debug/backfill-sets")
async def run_backfill_sets(limit: int = 120):
    """Ручной запуск дозаполнения счёта по сетам (live_score/live_sets_score)."""
    safe_limit = max(1, min(int(limit), 500))
    updated = await backfill_missing_sets_scores_once(limit=safe_limit)
    return {"ok": True, "limit": safe_limit, "updated": updated}


@router.post("/debug/backfill-forecasts")
async def run_backfill_forecasts() -> dict:
    """Ручной запуск: добавить в table_tennis_forecasts все уже рассчитанные прогнозы из line‑таблицы."""
    inserted = await backfill_forecasts_from_existing_events_once()
    return {"ok": True, "inserted": inserted}


@router.post("/debug/backfill-results-range")
async def run_backfill_results_range(
    date_from: str,
    date_to: str,
    only_with_forecast: bool = True,
    max_pages_per_day: int = 6,
) -> dict:
    """Ручной запуск дозагрузки результатов из архива за диапазон дат."""
    dt_from = _parse_date_start_utc(date_from)
    dt_to = _parse_date_start_utc(date_to)
    if dt_from is None or dt_to is None:
        return {
            "ok": False,
            "error": "invalid_date",
            "message": "Используйте формат YYYY-MM-DD для date_from/date_to",
        }
    result = await sync_results_from_archive_range_once(
        date_from=dt_from.date(),
        date_to=dt_to.date(),
        only_forecasted=bool(only_with_forecast),
        max_pages_per_day=max(1, min(int(max_pages_per_day), 20)),
    )
    return {
        "ok": True,
        "date_from": dt_from.date().isoformat(),
        "date_to": dt_to.date().isoformat(),
        "only_with_forecast": bool(only_with_forecast),
        "result": result,
    }


@router.post("/debug/revalidate-cancelled-forecasts")
async def run_revalidate_cancelled_forecasts(limit: int = 120) -> dict:
    """Ручной запуск перепроверки cancelled-матчей с прогнозами."""
    safe_limit = max(1, min(int(limit), 1000))
    result = await revalidate_cancelled_forecast_events_once(limit=safe_limit)
    return {"ok": True, "limit": safe_limit, "result": result}


@router.get("/line")
async def get_table_tennis_line(session: AsyncSession = Depends(get_async_session)):
    """Линия: только матчи со статусом scheduled. Cancelled, live, finished и др. не отдаём."""
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(TableTennisLineEvent)
        .where(TableTennisLineEvent.status == LINE_EVENT_STATUS_SCHEDULED)
        .where(TableTennisLineEvent.starts_at > now)
        .order_by(TableTennisLineEvent.starts_at)
    )
    rows = list(result.scalars().all())
    return _build_line_response(rows)


@router.get("/results")
async def get_table_tennis_results(
    page: int = 1,
    page_size: int = 30,
    league_id: str = "",
    player_query: str = "",
    date_from: str = "",
    date_to: str = "",
    session: AsyncSession = Depends(get_async_session),
):
    """Завершённые матчи (results) с фильтрами и пагинацией."""
    p = _sanitize_page(page)
    ps = _sanitize_page_size(page_size, max_size=100)
    offset = (p - 1) * ps
    dt_from = _parse_date_start_utc(date_from)
    dt_to_excl = _parse_date_end_utc_exclusive(date_to)
    player_q = (player_query or "").strip().lower()
    player_like = f"%{player_q}%"

    conditions = [TableTennisLineEvent.status == LINE_EVENT_STATUS_FINISHED]
    if league_id:
        conditions.append(TableTennisLineEvent.league_id == league_id)
    if player_q:
        conditions.append(
            or_(
                sa.func.lower(TableTennisLineEvent.home_name).like(player_like),
                sa.func.lower(TableTennisLineEvent.away_name).like(player_like),
            )
        )
    if dt_from is not None:
        conditions.append(TableTennisLineEvent.starts_at >= dt_from)
    if dt_to_excl is not None:
        conditions.append(TableTennisLineEvent.starts_at < dt_to_excl)

    total_result = await session.execute(
        select(func.count()).select_from(TableTennisLineEvent).where(*conditions)
    )
    total = int(total_result.scalar_one() or 0)

    rows_result = await session.execute(
        select(TableTennisLineEvent)
        .where(*conditions)
        .order_by(TableTennisLineEvent.starts_at.desc())
        .limit(ps)
        .offset(offset)
    )
    rows = list(rows_result.scalars().all())

    leagues_result = await session.execute(
        sa.text(
            """
            SELECT DISTINCT league_id, league_name
            FROM table_tennis_line_events
            WHERE status = 'finished'
              AND league_id IS NOT NULL
              AND league_name IS NOT NULL
            ORDER BY league_name
            """
        )
    )
    leagues = [
        {"id": str(r["league_id"]), "name": str(r["league_name"])}
        for r in leagues_result.mappings().all()
    ]

    return {
        "items": [_event_to_dict(r) for r in rows],
        "page": p,
        "page_size": ps,
        "total": total,
        "leagues": leagues,
        "filters": {
            "league_id": league_id or None,
            "player_query": player_query or None,
            "date_from": date_from or None,
            "date_to": date_to or None,
        },
    }


@router.get("/forecasts/stats")
async def get_table_tennis_forecasts_stats(
    date_from: str = "",
    date_to: str = "",
    league_id: str = "",
    channel: str = "",
    session: AsyncSession = Depends(get_async_session),
):
    """Сводная статистика по прематч‑прогнозам модели."""
    dt_from = _parse_date_start_utc(date_from)
    dt_to_excl = _parse_date_end_utc_exclusive(date_to)

    conditions = []
    if dt_from is not None:
        conditions.append(TableTennisForecast.created_at >= dt_from)
    if dt_to_excl is not None:
        conditions.append(TableTennisForecast.created_at < dt_to_excl)
    if league_id:
        conditions.append(TableTennisForecast.league_id == league_id)
    if channel:
        conditions.append(TableTennisForecast.channel == channel)

    # Всего
    total_result = await session.execute(
        select(func.count()).select_from(TableTennisForecast).where(*conditions)
    )
    total = int(total_result.scalar_one() or 0)

    # По статусам
    by_status_result = await session.execute(
        select(TableTennisForecast.status, func.count())
        .where(*conditions)
        .group_by(TableTennisForecast.status)
    )
    by_status_rows = by_status_result.all()
    by_status: dict[str, int] = {str(status): int(cnt) for status, cnt in by_status_rows}

    hits = by_status.get("hit", 0)
    misses = by_status.get("miss", 0)
    resolved = hits + misses
    hit_rate = (hits / resolved * 100.0) if resolved else None

    return {
        "total": total,
        "by_status": by_status,
        "hit_rate": hit_rate,
    }


@router.get("/forecasts")
async def get_table_tennis_forecasts(
    page: int = 1,
    page_size: int = 50,
    status: str = "",
    league_id: str = "",
    date_from: str = "",
    date_to: str = "",
    channel: str = "",
    session: AsyncSession = Depends(get_async_session),
):
    """Пагинированный список прогнозов по матчам для аналитики.

    Если page=0, возвращает все подходящие прогнозы без пагинации (для SSE/фона)."""
    p = _sanitize_page(page) if page > 0 else 1
    ps = _sanitize_page_size(page_size, max_size=200)
    offset = (p - 1) * ps if page > 0 else 0
    dt_from = _parse_date_start_utc(date_from)
    dt_to_excl = _parse_date_end_utc_exclusive(date_to)

    conditions = []
    if status:
        conditions.append(TableTennisForecast.status == status)
    if league_id:
        conditions.append(TableTennisForecast.league_id == league_id)
    if dt_from is not None:
        conditions.append(TableTennisForecast.created_at >= dt_from)
    if dt_to_excl is not None:
        conditions.append(TableTennisForecast.created_at < dt_to_excl)
    if channel:
        conditions.append(TableTennisForecast.channel == channel)


    total_result = await session.execute(
        select(func.count()).select_from(TableTennisForecast).where(*conditions)
    )
    total = int(total_result.scalar_one() or 0)

    stmt = (
        select(TableTennisForecast, TableTennisLineEvent)
        .join(
            TableTennisLineEvent,
            TableTennisLineEvent.id == TableTennisForecast.event_id,
        )
        .where(*conditions)
        .order_by(TableTennisForecast.created_at.desc())
    )
    if page > 0:
        stmt = stmt.limit(ps).offset(offset)

    rows_result = await session.execute(stmt)
    items: list[dict] = []
    for f_row, ev in rows_result.all():
        f: TableTennisForecast = f_row
        # Кф прогноза: берём кф той стороны, на которую даётся рекомендация (П1 / П2).
        txt = (f.forecast_text or "").lower()
        forecast_odds: float | None = None
        if "п1" in txt:
            forecast_odds = float(ev.odds_1) if ev.odds_1 is not None else None
        elif "п2" in txt:
            forecast_odds = float(ev.odds_2) if ev.odds_2 is not None else None

        # За сколько времени до начала матча был дан прогноз (секунды; может быть отрицательным, если после старта).
        lead_seconds: int | None = None
        if f.created_at and ev.starts_at:
            lead_seconds = int((ev.starts_at - f.created_at).total_seconds())

        # Эффективный статус события для аналитики:
        # если по счёту по сетам явно есть победитель — считаем матч завершённым,
        # даже если status в таблице ещё "live" (задержка фоновых задач).
        event_status = ev.status
        wins_home, wins_away = _parse_sets_score(ev.live_sets_score)
        if wins_home is not None and wins_away is not None and wins_home != wins_away:
            if event_status in {LINE_EVENT_STATUS_LIVE, LINE_EVENT_STATUS_SCHEDULED}:
                event_status = LINE_EVENT_STATUS_FINISHED

        items.append(
            {
                "event_id": f.event_id,
                "league_id": f.league_id,
                "league_name": f.league_name,
                "home_id": f.home_id,
                "home_name": f.home_name,
                "away_id": f.away_id,
                "away_name": f.away_name,
                "forecast_text": f.forecast_text,
                "confidence_pct": float(f.confidence_pct) if f.confidence_pct is not None else None,
                "status": f.status,
                "created_at": int(f.created_at.timestamp()) if f.created_at else None,
                "resolved_at": int(f.resolved_at.timestamp()) if f.resolved_at else None,
                "final_status": f.final_status,
                "final_sets_score": f.final_sets_score,
                "starts_at": int(ev.starts_at.timestamp()) if ev.starts_at else None,
                "odds_1": float(ev.odds_1) if ev.odds_1 is not None else None,
                "odds_2": float(ev.odds_2) if ev.odds_2 is not None else None,
                "channel": f.channel,
                "event_status": event_status,
                "sets_score": ev.live_sets_score,
                "live_score": ev.live_score,
                "forecast_odds": float(f.forecast_odds) if f.forecast_odds is not None else forecast_odds,
                "forecast_lead_seconds": lead_seconds,
            }
        )

    return {
        "items": items,
        "page": p if page > 0 else 1,
        "page_size": ps if page > 0 else total,
        "total": total,
    }


@router.get("/players")
async def get_table_tennis_players(
    page: int = 1,
    page_size: int = 30,
    q: str = "",
    session: AsyncSession = Depends(get_async_session),
):
    """Пагинированный список игроков с базовой статистикой."""
    p = _sanitize_page(page)
    ps = _sanitize_page_size(page_size, max_size=100)
    offset = (p - 1) * ps
    q_norm = (q or "").strip()
    q_like = f"%{q_norm.lower()}%"
    now = datetime.now(timezone.utc)

    total_result = await session.execute(
        sa.text(
            """
            WITH players_union AS (
              SELECT home_id AS id, MAX(home_name) AS name
              FROM table_tennis_line_events
              WHERE home_id IS NOT NULL
              GROUP BY home_id
              UNION
              SELECT away_id AS id, MAX(away_name) AS name
              FROM table_tennis_line_events
              WHERE away_id IS NOT NULL
              GROUP BY away_id
            )
            SELECT COUNT(*) AS total
            FROM players_union p
            WHERE (:q = '' OR LOWER(p.name) LIKE :q_like)
            """
        ),
        {"q": q_norm, "q_like": q_like},
    )
    total = int(total_result.scalar_one() or 0)

    rows_result = await session.execute(
        sa.text(
            """
            WITH players_union AS (
              SELECT home_id AS id, MAX(home_name) AS name
              FROM table_tennis_line_events
              WHERE home_id IS NOT NULL
              GROUP BY home_id
              UNION
              SELECT away_id AS id, MAX(away_name) AS name
              FROM table_tennis_line_events
              WHERE away_id IS NOT NULL
              GROUP BY away_id
            )
            SELECT
              p.id,
              p.name,
              (
                SELECT COUNT(*)
                FROM table_tennis_line_events e
                WHERE e.home_id = p.id OR e.away_id = p.id
              ) AS matches_total,
              (
                SELECT COUNT(*)
                FROM table_tennis_line_events e
                WHERE (e.home_id = p.id OR e.away_id = p.id)
                  AND e.status = 'finished'
              ) AS matches_finished,
              (
                SELECT COUNT(*)
                FROM table_tennis_line_events e
                WHERE (e.home_id = p.id OR e.away_id = p.id)
                  AND e.status = 'scheduled'
                  AND e.starts_at > :now
              ) AS matches_upcoming
            FROM players_union p
            WHERE (:q = '' OR LOWER(p.name) LIKE :q_like)
            ORDER BY p.name
            LIMIT :limit OFFSET :offset
            """
        ),
        {"q": q_norm, "q_like": q_like, "limit": ps, "offset": offset, "now": now},
    )
    items = [dict(r) for r in rows_result.mappings().all()]
    return {"items": items, "page": p, "page_size": ps, "total": total}


@router.get("/leagues")
async def get_table_tennis_leagues(
    page: int = 1,
    page_size: int = 30,
    q: str = "",
    session: AsyncSession = Depends(get_async_session),
):
    """Пагинированный список лиг с базовой статистикой."""
    p = _sanitize_page(page)
    ps = _sanitize_page_size(page_size, max_size=100)
    offset = (p - 1) * ps
    q_norm = (q or "").strip()
    q_like = f"%{q_norm.lower()}%"
    now = datetime.now(timezone.utc)

    total_result = await session.execute(
        sa.text(
            """
            SELECT COUNT(*) AS total
            FROM table_tennis_leagues l
            WHERE (:q = '' OR LOWER(l.name) LIKE :q_like)
            """
        ),
        {"q": q_norm, "q_like": q_like},
    )
    total = int(total_result.scalar_one() or 0)

    rows_result = await session.execute(
        sa.text(
            """
            SELECT
              l.id,
              l.name,
              (
                SELECT COUNT(*) FROM table_tennis_line_events e
                WHERE e.league_id = l.id
              ) AS matches_total,
              (
                SELECT COUNT(*) FROM table_tennis_line_events e
                WHERE e.league_id = l.id AND e.status = 'finished'
              ) AS matches_finished,
              (
                SELECT COUNT(*) FROM table_tennis_line_events e
                WHERE e.league_id = l.id AND e.status = 'scheduled' AND e.starts_at > :now
              ) AS matches_upcoming
            FROM table_tennis_leagues l
            WHERE (:q = '' OR LOWER(l.name) LIKE :q_like)
            ORDER BY l.name
            LIMIT :limit OFFSET :offset
            """
        ),
        {"q": q_norm, "q_like": q_like, "limit": ps, "offset": offset, "now": now},
    )
    items = [dict(r) for r in rows_result.mappings().all()]
    return {"items": items, "page": p, "page_size": ps, "total": total}


@router.get("/matches/{match_id}")
async def get_table_tennis_match_card(match_id: str, session: AsyncSession = Depends(get_async_session)):
    result = await session.execute(
        select(TableTennisLineEvent).where(TableTennisLineEvent.id == str(match_id))
    )
    match = result.scalar_one_or_none()
    if match is None:
        return {"match": None}

    now = datetime.now(timezone.utc)
    result_home = await session.execute(
        select(TableTennisLineEvent)
        .where(
            or_(
                TableTennisLineEvent.home_id == match.home_id,
                TableTennisLineEvent.away_id == match.home_id,
            ),
            TableTennisLineEvent.status == LINE_EVENT_STATUS_FINISHED,
            TableTennisLineEvent.starts_at <= match.starts_at,
        )
        .order_by(TableTennisLineEvent.starts_at.desc())
        .limit(10)
    )
    result_away = await session.execute(
        select(TableTennisLineEvent)
        .where(
            or_(
                TableTennisLineEvent.home_id == match.away_id,
                TableTennisLineEvent.away_id == match.away_id,
            ),
            TableTennisLineEvent.status == LINE_EVENT_STATUS_FINISHED,
            TableTennisLineEvent.starts_at <= match.starts_at,
        )
        .order_by(TableTennisLineEvent.starts_at.desc())
        .limit(10)
    )
    home_rows = list(result_home.scalars().all())
    away_rows = list(result_away.scalars().all())

    # Head-to-head: все завершённые матчи между этими игроками.
    h2h_result = await session.execute(
        select(TableTennisLineEvent)
        .where(
            TableTennisLineEvent.status == LINE_EVENT_STATUS_FINISHED,
            or_(
                and_(
                    TableTennisLineEvent.home_id == match.home_id,
                    TableTennisLineEvent.away_id == match.away_id,
                ),
                and_(
                    TableTennisLineEvent.home_id == match.away_id,
                    TableTennisLineEvent.away_id == match.home_id,
                ),
            ),
        )
        .order_by(TableTennisLineEvent.starts_at.desc())
    )
    h2h_rows = list(h2h_result.scalars().all())
    h2h_total = len(h2h_rows)
    h2h_home_wins = 0
    h2h_away_wins = 0
    for r in h2h_rows:
        hs, as_ = _parse_sets_score(r.live_sets_score)
        if hs is None or as_ is None:
            continue
        # home_id/away_id в записи матча могут быть как (home, away), так и (away, home) относительно текущего.
        if r.home_id == match.home_id:
            if hs > as_:
                h2h_home_wins += 1
            elif as_ > hs:
                h2h_away_wins += 1
        else:
            # r.home_id == match.away_id
            if hs > as_:
                h2h_away_wins += 1
            elif as_ > hs:
                h2h_home_wins += 1

    h2h_dict = {
        "total": h2h_total,
        "home_wins": h2h_home_wins,
        "away_wins": h2h_away_wins,
    }

    home_stats = _build_player_stats(match.home_id, home_rows, now)
    away_stats = _build_player_stats(match.away_id, away_rows, now)
    justification = _build_match_justification(match, home_stats, away_stats, h2h_dict)

    # Подробные сильные/слабые стороны для карточки матча (по всем завершённым матчам игрока).
    detailed_home = await load_player_stats(session, match.home_id)
    detailed_away = await load_player_stats(session, match.away_id)
    home_strengths, home_weaknesses = build_strengths_weaknesses(detailed_home)
    away_strengths, away_weaknesses = build_strengths_weaknesses(detailed_away)

    return {
        "match": _event_to_dict(match),
        "home_stats": home_stats,
        "away_stats": away_stats,
        "forecast": match.forecast,
        "forecast_confidence": float(match.forecast_confidence) if match.forecast_confidence is not None else None,
        "analytics": {
            "head_to_head": h2h_dict,
            "justification": justification,
            "home_strengths": home_strengths,
            "home_weaknesses": home_weaknesses,
            "away_strengths": away_strengths,
            "away_weaknesses": away_weaknesses,
        },
    }


@router.get("/players/{player_id}/card")
async def get_table_tennis_player_card(
    player_id: str,
    page_upcoming: int = 1,
    page_finished: int = 1,
    page_size: int = 20,
    session: AsyncSession = Depends(get_async_session),
):
    now = datetime.now(timezone.utc)
    p_up = _sanitize_page(page_upcoming)
    p_fin = _sanitize_page(page_finished)
    ps = _sanitize_page_size(page_size, max_size=100)
    offset_up = (p_up - 1) * ps
    offset_fin = (p_fin - 1) * ps

    base_filter = or_(
        TableTennisLineEvent.home_id == str(player_id),
        TableTennisLineEvent.away_id == str(player_id),
    )

    result = await session.execute(select(TableTennisLineEvent).where(base_filter).order_by(TableTennisLineEvent.starts_at.desc()))
    rows = list(result.scalars().all())
    if not rows:
        return {"player": None}

    player_name = None
    for r in rows:
        if r.home_id == str(player_id):
            player_name = r.home_name
            break
        if r.away_id == str(player_id):
            player_name = r.away_name
            break

    total_upcoming_result = await session.execute(
        select(func.count())
        .select_from(TableTennisLineEvent)
        .where(base_filter, TableTennisLineEvent.status == LINE_EVENT_STATUS_SCHEDULED, TableTennisLineEvent.starts_at > now)
    )
    total_finished_result = await session.execute(
        select(func.count())
        .select_from(TableTennisLineEvent)
        .where(base_filter, TableTennisLineEvent.status == LINE_EVENT_STATUS_FINISHED)
    )
    total_upcoming = int(total_upcoming_result.scalar_one() or 0)
    total_finished = int(total_finished_result.scalar_one() or 0)

    upcoming_rows_result = await session.execute(
        select(TableTennisLineEvent)
        .where(base_filter, TableTennisLineEvent.status == LINE_EVENT_STATUS_SCHEDULED, TableTennisLineEvent.starts_at > now)
        .order_by(TableTennisLineEvent.starts_at.asc())
        .limit(ps)
        .offset(offset_up)
    )
    finished_rows_result = await session.execute(
        select(TableTennisLineEvent)
        .where(base_filter, TableTennisLineEvent.status == LINE_EVENT_STATUS_FINISHED)
        .order_by(TableTennisLineEvent.starts_at.desc())
        .limit(ps)
        .offset(offset_fin)
    )
    upcoming = [_event_to_dict(r) for r in list(upcoming_rows_result.scalars().all())]
    finished = [_event_to_dict(r) for r in list(finished_rows_result.scalars().all())]

    return {
        "player": {"id": str(player_id), "name": player_name or "Игрок"},
        "stats": _build_player_stats(str(player_id), rows, now),
        "upcoming_matches": upcoming,
        "finished_matches": finished,
        "pagination": {
            "upcoming": {"page": p_up, "page_size": ps, "total": total_upcoming},
            "finished": {"page": p_fin, "page_size": ps, "total": total_finished},
        },
    }


@router.get("/leagues/{league_id}/card")
async def get_table_tennis_league_card(
    league_id: str,
    page_upcoming: int = 1,
    page_finished: int = 1,
    page_size: int = 20,
    date_from: str = "",
    date_to: str = "",
    session: AsyncSession = Depends(get_async_session),
):
    now = datetime.now(timezone.utc)
    p_up = _sanitize_page(page_upcoming)
    p_fin = _sanitize_page(page_finished)
    ps = _sanitize_page_size(page_size, max_size=100)
    offset_up = (p_up - 1) * ps
    offset_fin = (p_fin - 1) * ps
    dt_from = _parse_date_start_utc(date_from)
    dt_to_excl = _parse_date_end_utc_exclusive(date_to)

    base_conditions = [TableTennisLineEvent.league_id == str(league_id)]
    if dt_from is not None:
        base_conditions.append(TableTennisLineEvent.starts_at >= dt_from)
    if dt_to_excl is not None:
        base_conditions.append(TableTennisLineEvent.starts_at < dt_to_excl)

    league_result = await session.execute(
        select(TableTennisLineEvent.league_name).where(TableTennisLineEvent.league_id == str(league_id)).limit(1)
    )
    league_name = league_result.scalar_one_or_none() or str(league_id)

    total_upcoming_result = await session.execute(
        select(func.count())
        .select_from(TableTennisLineEvent)
        .where(
            *base_conditions,
            TableTennisLineEvent.status == LINE_EVENT_STATUS_SCHEDULED,
            TableTennisLineEvent.starts_at > now,
        )
    )
    total_finished_result = await session.execute(
        select(func.count())
        .select_from(TableTennisLineEvent)
        .where(
            *base_conditions,
            TableTennisLineEvent.status == LINE_EVENT_STATUS_FINISHED,
        )
    )
    total_upcoming = int(total_upcoming_result.scalar_one() or 0)
    total_finished = int(total_finished_result.scalar_one() or 0)

    upcoming_rows_result = await session.execute(
        select(TableTennisLineEvent)
        .where(
            *base_conditions,
            TableTennisLineEvent.status == LINE_EVENT_STATUS_SCHEDULED,
            TableTennisLineEvent.starts_at > now,
        )
        .order_by(TableTennisLineEvent.starts_at.asc())
        .limit(ps)
        .offset(offset_up)
    )
    finished_rows_result = await session.execute(
        select(TableTennisLineEvent)
        .where(
            *base_conditions,
            TableTennisLineEvent.status == LINE_EVENT_STATUS_FINISHED,
        )
        .order_by(TableTennisLineEvent.starts_at.desc())
        .limit(ps)
        .offset(offset_fin)
    )
    upcoming = [_event_to_dict(r) for r in list(upcoming_rows_result.scalars().all())]
    finished = [_event_to_dict(r) for r in list(finished_rows_result.scalars().all())]

    return {
        "league": {"id": str(league_id), "name": league_name},
        "stats": {
            "upcoming_matches": total_upcoming,
            "finished_matches": total_finished,
            "total_matches": total_upcoming + total_finished,
        },
        "upcoming_matches": upcoming,
        "finished_matches": finished,
        "pagination": {
            "upcoming": {"page": p_up, "page_size": ps, "total": total_upcoming},
            "finished": {"page": p_fin, "page_size": ps, "total": total_finished},
        },
        "filters": {
            "date_from": date_from or None,
            "date_to": date_to or None,
        },
    }


async def _line_sse_generator():
    """Генератор SSE: периодически отправляет актуальную линию (статусы, коэфы, новые матчи)."""
    interval = max(5, getattr(settings, "line_sse_interval_sec", 5))
    try:
        while True:
            now = datetime.now(timezone.utc)
            async with async_session_maker() as session:
                result = await session.execute(
                    select(TableTennisLineEvent)
                    .where(TableTennisLineEvent.status == LINE_EVENT_STATUS_SCHEDULED)
                    .where(TableTennisLineEvent.starts_at > now)
                    .order_by(TableTennisLineEvent.starts_at)
                )
                rows = list(result.scalars().all())
            payload = _build_line_response(rows)
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass


async def _forecasts_sse_generator(channel: str = "paid"):
    """SSE: периодически отдаёт агрегированную статистику и список прогнозов для указанного канала."""
    interval = max(10, getattr(settings, "line_sse_interval_sec", 5))
    try:
        while True:
            async with async_session_maker() as session:
                # Статистика
                stats = await get_table_tennis_forecasts_stats(
                    date_from="",
                    date_to="",
                    league_id="",
                    channel=channel,
                    session=session,
                )
                # Полный список прогнозов для канала (page=0 → без пагинации)
                forecasts = await get_table_tennis_forecasts(
                    page=0,
                    page_size=200,
                    status="",
                    league_id="",
                    date_from="",
                    date_to="",
                    channel=channel,
                    session=session,
                )
            payload = {
                "stats": stats,
                "forecasts": forecasts,
            }
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass


@router.get("/line/stream")
async def stream_table_tennis_line():
    """SSE-поток линии: обновление статусов, коэфов и списка матчей без перезагрузки страницы."""
    return StreamingResponse(
        _line_sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/forecasts/stream")
async def stream_table_tennis_forecasts(channel: str = "paid"):
    """SSE-поток статистики прогнозов (для страницы аналитики)."""
    return StreamingResponse(
        _forecasts_sse_generator(channel=channel),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

async def _live_sse_generator():
    """SSE: периодически отдаёт актуальный список лайв-матчей (live + свежие finished)."""
    interval = max(5, getattr(settings, "line_sse_interval_sec", 5))
    try:
        while True:
            now = datetime.now(timezone.utc)
            five_minutes_ago = now - timedelta(minutes=5)
            live_freshness_cutoff = now - timedelta(minutes=15)
            async with async_session_maker() as session:
                result = await session.execute(
                    select(TableTennisLineEvent).where(
                        or_(
                            and_(
                                TableTennisLineEvent.status == LINE_EVENT_STATUS_LIVE,
                                TableTennisLineEvent.is_stale.is_(False),
                                or_(
                                    TableTennisLineEvent.last_score_changed_at >= live_freshness_cutoff,
                                    TableTennisLineEvent.starts_at >= live_freshness_cutoff,
                                ),
                            ),
                            and_(
                                TableTennisLineEvent.status == LINE_EVENT_STATUS_FINISHED,
                                or_(
                                    and_(
                                        TableTennisLineEvent.finished_at.is_not(None),
                                        TableTennisLineEvent.finished_at >= five_minutes_ago,
                                    ),
                                    and_(
                                        TableTennisLineEvent.finished_at.is_(None),
                                        TableTennisLineEvent.updated_at >= five_minutes_ago,
                                    ),
                                ),
                            ),
                        )
                    )
                    .order_by(TableTennisLineEvent.starts_at)
                )
                rows = list(result.scalars().all())
            payload = _build_live_response(rows)
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass


@router.get("/live/stream")
async def stream_table_tennis_live():
    """SSE-поток лайва: обновление статусов, коэфов и счёта без перезагрузки страницы."""
    return StreamingResponse(
        _live_sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
