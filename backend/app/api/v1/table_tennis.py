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
from app.api.v1.auth import get_current_user
from app.db.session import get_async_session, async_session_maker
from app.models.table_tennis_line_event import (
    TableTennisLineEvent,
    LINE_EVENT_STATUS_SCHEDULED,
    LINE_EVENT_STATUS_LIVE,
    LINE_EVENT_STATUS_FINISHED,
)
from app.services.betsapi_table_tennis import (
    backfill_missing_sets_scores_once,
    sync_results_from_archive_range_once,
    revalidate_cancelled_forecast_events_once,
)
from app.services.table_tennis_analytics import load_player_stats, build_strengths_weaknesses
from app.models.table_tennis_forecast_v2 import TableTennisForecastV2
from app.models.table_tennis_forecast_explanation import TableTennisForecastExplanation
from app.models.user import User
from app.models.user_forecast_notification import UserForecastNotification
from app.services.forecast_v2_pipeline import (
    get_kpi_runtime_state,
    run_kpi_guard_once,
    run_forecast_v2_once,
    run_result_priority_once,
    run_validation_checks_once,
)
from app.services.notification_dispatcher import dispatch_forecast_notifications_once
from app.services.subscription_access import (
    FORECAST_LOCKED_ANALYTICS,
    DASHBOARD_PURCHASE_URL,
    get_subscription_access,
)
from app.services.telegram_channel_dispatcher import dispatch_channel_notifications_once

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


def _has_in_progress_set_fragment(live_score: dict | None) -> bool:
    if not isinstance(live_score, dict):
        return False
    for _, set_data in live_score.items():
        if not isinstance(set_data, dict):
            continue
        h_raw = set_data.get("home")
        a_raw = set_data.get("away")
        if h_raw is None and a_raw is None:
            continue
        try:
            h = int(str(h_raw or "0"))
            a = int(str(a_raw or "0"))
        except (TypeError, ValueError):
            continue
        if h == 0 and a == 0:
            continue
        if not (max(h, a) >= 11 and abs(h - a) >= 2):
            return True
    return False


def _normalize_forecast_event_status(event: TableTennisLineEvent | None) -> str | None:
    if not event:
        return None
    if event.status != LINE_EVENT_STATUS_FINISHED:
        return event.status
    hs, as_ = _parse_sets_score(event.live_sets_score)
    required_wins = max(1, int(getattr(settings, "table_tennis_match_sets_to_win", 3)))
    has_final_sets = hs is not None and as_ is not None and hs != as_ and max(hs, as_) >= required_wins
    if (not has_final_sets) or _has_in_progress_set_fragment(event.live_score):
        return LINE_EVENT_STATUS_LIVE
    return event.status


def _compute_ml_analytics(event: TableTennisLineEvent) -> dict | None:
    """ML-аналитика для карточки матча: вероятности, фичи, value-сигналы."""
    if not event.home_id or not event.away_id:
        return None
    try:
        from app.ml.inference import predict_for_upcoming

        pred = predict_for_upcoming(
            home_id=event.home_id,
            away_id=event.away_id,
            league_id=event.league_id or "",
            odds_p1=float(event.odds_1 or 1.9),
            odds_p2=float(event.odds_2 or 1.9),
            start_time=event.starts_at,
            match_id=event.id,
        )
        if pred is None:
            return None
        out = {
            "p_match": round(pred.p_match, 4),
            "p_set1": round(pred.p_set1, 4),
            "p_set2": round(pred.p_set2, 4),
            "model_used": pred.model_used,
            "value_signals": pred.value_signals,
        }
        if getattr(pred, "suspicious", False):
            out["suspicious"] = True
            out["suspicious_score"] = round(pred.suspicious_score, 3)
            out["suspicious_reason"] = pred.suspicious_reason or ""
        if pred.features:
            f = pred.features
            out["features"] = {
                "elo_diff": round(f.elo_diff, 1),
                "form_diff": round(f.form_diff, 4),
                "fatigue_diff": round(f.fatigue_diff, 1),
                "h2h_count": f.h2h_count,
                "h2h_p1_wr": round(f.h2h_p1_wr, 3) if f.h2h_count else None,
                "sample_size": f.sample_size,
                "elo_p1": round(f.elo_p1, 0),
                "elo_p2": round(f.elo_p2, 0),
            }
        return out
    except Exception:
        return None


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


async def _load_v2_forecast_map(
    session: AsyncSession,
    event_ids: list[str],
    channel: str = "paid",
    resolved_only: bool = False,
) -> dict[str, str]:
    """Latest V2 forecast text per event for given channel."""
    if not event_ids:
        return {}
    conditions = [
        TableTennisForecastV2.event_id.in_(event_ids),
        TableTennisForecastV2.channel == channel,
    ]
    if resolved_only:
        conditions.append(TableTennisForecastV2.status.in_(["hit", "miss"]))
    rows = (
        await session.execute(
            select(
                TableTennisForecastV2.event_id,
                TableTennisForecastV2.forecast_text,
                TableTennisForecastV2.created_at,
            )
            .where(and_(*conditions))
            .order_by(TableTennisForecastV2.event_id.asc(), TableTennisForecastV2.created_at.desc())
        )
    ).all()
    out: dict[str, str] = {}
    for event_id, forecast_text, _created_at in rows:
        if event_id not in out and forecast_text:
            out[str(event_id)] = str(forecast_text)
    return out


async def _load_v2_forecast_map_resolved_only(
    session: AsyncSession,
    event_ids: list[str],
    channel: str,
) -> dict[str, str]:
    """Latest V2 forecast text per event, only for resolved (hit/miss) forecasts."""
    return await _load_v2_forecast_map(session, event_ids, channel=channel, resolved_only=True)


def _build_line_response(
    rows: list,
    forecast_map_ml: dict[str, str] | None = None,
    forecast_map_no_ml: dict[str, str] | None = None,
    forecast_map_nn: dict[str, str] | None = None,
) -> dict:
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
            "forecast": (forecast_map_ml or {}).get(str(r.id)) or r.forecast,
            "forecast_ml": (forecast_map_ml or {}).get(str(r.id)) or r.forecast,
            "forecast_no_ml": (forecast_map_no_ml or {}).get(str(r.id)),
            "forecast_nn": (forecast_map_nn or {}).get(str(r.id)),
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
async def get_table_tennis_live(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Лайв: матчи со статусом live, а также finished — но только в течение 5 минут после завершения."""
    now = datetime.now(timezone.utc)
    five_minutes_ago = now - timedelta(minutes=5)
    live_freshness_cutoff = now - timedelta(minutes=30)
    result = await session.execute(
        select(TableTennisLineEvent).where(
            or_(
                and_(
                    TableTennisLineEvent.status == LINE_EVENT_STATUS_LIVE,
                    TableTennisLineEvent.is_stale.is_(False),
                    or_(
                        TableTennisLineEvent.last_score_changed_at >= live_freshness_cutoff,
                        TableTennisLineEvent.starts_at >= live_freshness_cutoff,
                        TableTennisLineEvent.updated_at >= live_freshness_cutoff,
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
    access = await get_subscription_access(user.id, session)
    if not access["can_see_forecasts"]:
        forecast_map_ml = None
        forecast_map_no_ml = None
        forecast_map_nn = None
        forecast_placeholder = FORECAST_LOCKED_ANALYTICS
        forecast_locked = True
        forecast_purchase_url = DASHBOARD_PURCHASE_URL
    else:
        ch = access["forecast_channel"] or "paid"
        if access["only_resolved"]:
            forecast_map_ml = await _load_v2_forecast_map_resolved_only(
                session, [str(r.id) for r in rows], channel=ch
            )
        else:
            forecast_map_ml = await _load_v2_forecast_map(
                session, [str(r.id) for r in rows], channel=ch
            )
        if access.get("has_analytics_no_ml", False):
            forecast_map_no_ml = await _load_v2_forecast_map(
                session, [str(r.id) for r in rows], channel="no_ml"
            )
        else:
            forecast_map_no_ml = None
        if access.get("has_analytics", False):
            forecast_map_nn = await _load_v2_forecast_map(
                session, [str(r.id) for r in rows], channel="nn"
            )
        else:
            forecast_map_nn = None
        forecast_placeholder = None
        forecast_locked = False
        forecast_purchase_url = None
    resp = _build_live_response(
        rows,
        forecast_map_ml=forecast_map_ml,
        forecast_map_no_ml=forecast_map_no_ml,
        forecast_map_nn=forecast_map_nn,
    )
    if forecast_locked:
        for ev in resp.get("events", []):
            ev["forecast"] = forecast_placeholder
        resp["forecast_locked"] = True
        resp["forecast_locked_message"] = forecast_placeholder
        resp["forecast_purchase_url"] = forecast_purchase_url
    return resp


def _build_live_response(
    rows: list[TableTennisLineEvent],
    forecast_map_ml: dict[str, str] | None = None,
    forecast_map_no_ml: dict[str, str] | None = None,
    forecast_map_nn: dict[str, str] | None = None,
) -> dict:
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
                "forecast": (forecast_map_ml or {}).get(str(r.id)) or r.forecast,
                "forecast_ml": (forecast_map_ml or {}).get(str(r.id)) or r.forecast,
                "forecast_no_ml": (forecast_map_no_ml or {}).get(str(r.id)),
                "forecast_nn": (forecast_map_nn or {}).get(str(r.id)),
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
async def get_table_tennis_line(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Линия: только матчи со статусом scheduled. Cancelled, live, finished и др. не отдаём."""
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(TableTennisLineEvent)
        .where(TableTennisLineEvent.status == LINE_EVENT_STATUS_SCHEDULED)
        .where(TableTennisLineEvent.starts_at > now)
        .order_by(TableTennisLineEvent.starts_at)
    )
    rows = list(result.scalars().all())
    access = await get_subscription_access(user.id, session)
    if not access["can_see_forecasts"]:
        forecast_map_ml = None
        forecast_map_no_ml = None
        forecast_map_nn = None
        forecast_placeholder = FORECAST_LOCKED_ANALYTICS
        forecast_locked = True
        forecast_purchase_url = DASHBOARD_PURCHASE_URL
    else:
        ch = access["forecast_channel"] or "paid"
        if access["only_resolved"]:
            forecast_map_ml = await _load_v2_forecast_map_resolved_only(
                session, [str(r.id) for r in rows], channel=ch
            )
        else:
            forecast_map_ml = await _load_v2_forecast_map(
                session, [str(r.id) for r in rows], channel=ch
            )
        if access.get("has_analytics_no_ml", False):
            forecast_map_no_ml = await _load_v2_forecast_map(
                session, [str(r.id) for r in rows], channel="no_ml"
            )
        else:
            forecast_map_no_ml = None
        if access.get("has_analytics", False):
            forecast_map_nn = await _load_v2_forecast_map(
                session, [str(r.id) for r in rows], channel="nn"
            )
        else:
            forecast_map_nn = None
        forecast_placeholder = None
        forecast_locked = False
        forecast_purchase_url = None
    resp = _build_line_response(
        rows,
        forecast_map_ml=forecast_map_ml,
        forecast_map_no_ml=forecast_map_no_ml,
        forecast_map_nn=forecast_map_nn,
    )
    if forecast_locked:
        for ev in resp.get("events", []):
            ev["forecast"] = forecast_placeholder
        resp["forecast_locked"] = True
        resp["forecast_locked_message"] = forecast_placeholder
        resp["forecast_purchase_url"] = forecast_purchase_url
    return resp


@router.get("/results")
async def get_table_tennis_results(
    page: int = 1,
    page_size: int = 30,
    league_id: str = "",
    player_query: str = "",
    date_from: str = "",
    date_to: str = "",
    user: User = Depends(get_current_user),
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

    access = await get_subscription_access(user.id, session)
    items = [_event_to_dict(r) for r in rows]
    if not access["can_see_forecasts"]:
        for it in items:
            it["forecast"] = None
            it.pop("forecast_confidence", None)
        return {
            "items": items,
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
            "forecast_locked": True,
            "forecast_locked_message": FORECAST_LOCKED_ANALYTICS,
            "forecast_purchase_url": DASHBOARD_PURCHASE_URL,
        }

    return {
        "items": items,
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


def _forecast_v2_item(
    forecast: TableTennisForecastV2,
    event: TableTennisLineEvent | None,
    explanations: list[TableTennisForecastExplanation],
) -> dict:
    starts_at_ts = int(event.starts_at.timestamp()) if event and event.starts_at else None
    created_at_ts = int(forecast.created_at.timestamp()) if forecast.created_at else None
    lead_seconds = None
    if event and event.starts_at and forecast.created_at:
        lead_seconds = int((event.starts_at - forecast.created_at).total_seconds())
    return {
        "id": forecast.id,
        "event_id": forecast.event_id,
        "channel": forecast.channel,
        "market": forecast.market,
        "pick_side": forecast.pick_side,
        "forecast_text": forecast.forecast_text,
        "probability_pct": float(forecast.probability_pct) if forecast.probability_pct is not None else None,
        "confidence_score": float(forecast.confidence_score) if forecast.confidence_score is not None else None,
        "edge_pct": float(forecast.edge_pct) if forecast.edge_pct is not None else None,
        "odds_used": float(forecast.odds_used) if forecast.odds_used is not None else None,
        "status": forecast.status,
        "final_status": forecast.final_status,
        "final_sets_score": forecast.final_sets_score,
        "created_at": created_at_ts,
        "resolved_at": int(forecast.resolved_at.timestamp()) if forecast.resolved_at else None,
        "starts_at": starts_at_ts,
        "forecast_lead_seconds": lead_seconds,
        "event_status": _normalize_forecast_event_status(event),
        "league_id": event.league_id if event else None,
        "league_name": event.league_name if event else None,
        "home_id": event.home_id if event else None,
        "home_name": event.home_name if event else None,
        "away_id": event.away_id if event else None,
        "away_name": event.away_name if event else None,
        "sets_score": event.live_sets_score if event else None,
        "live_score": event.live_score if event else None,
        "explanation_summary": forecast.explanation_summary,
        "factors": [
            {
                "factor_key": e.factor_key,
                "factor_label": e.factor_label,
                "factor_value": e.factor_value,
                "contribution": float(e.contribution) if e.contribution is not None else None,
                "direction": e.direction,
                "rank": e.rank,
            }
            for e in sorted(explanations, key=lambda x: x.rank)
        ],
    }


async def _build_player_match_context(
    session: AsyncSession,
    event: TableTennisLineEvent,
) -> dict:
    """Build per-player and H2H context for this exact match."""
    if not event.home_id or not event.away_id:
        return {}

    cutoff = event.starts_at or datetime.now(timezone.utc)

    async def _player_recent(pid: str, max_rows: int = 30) -> dict:
        rows = (
            await session.execute(
                select(TableTennisLineEvent)
                .where(
                    TableTennisLineEvent.status == LINE_EVENT_STATUS_FINISHED,
                    or_(
                        TableTennisLineEvent.home_id == pid,
                        TableTennisLineEvent.away_id == pid,
                    ),
                    TableTennisLineEvent.starts_at.is_not(None),
                    TableTennisLineEvent.starts_at < cutoff,
                )
                .order_by(TableTennisLineEvent.starts_at.desc())
                .limit(max_rows)
            )
        ).scalars().all()

        wins = 0
        losses = 0
        form: list[dict] = []
        for row in rows:
            hs, as_ = _parse_sets_score(row.live_sets_score)
            if hs is None or as_ is None or hs == as_:
                continue
            is_home = row.home_id == pid
            won = (is_home and hs > as_) or ((not is_home) and as_ > hs)
            opponent_name = row.away_name if is_home else row.home_name
            if won:
                wins += 1
                form.append(
                    {
                        "event_id": str(row.id),
                        "result": "W",
                        "opponent_name": opponent_name,
                        "starts_at": int(row.starts_at.timestamp()) if row.starts_at else None,
                        "sets_score": row.live_sets_score,
                    }
                )
            else:
                losses += 1
                form.append(
                    {
                        "event_id": str(row.id),
                        "result": "L",
                        "opponent_name": opponent_name,
                        "starts_at": int(row.starts_at.timestamp()) if row.starts_at else None,
                        "sets_score": row.live_sets_score,
                    }
                )
        played = wins + losses
        return {
            "played": played,
            "wins": wins,
            "losses": losses,
            "win_rate": round((wins / played) * 100.0, 1) if played else None,
            "last5_form": form[:5],
        }

    h2h_rows = (
        await session.execute(
            select(TableTennisLineEvent)
            .where(
                TableTennisLineEvent.status == LINE_EVENT_STATUS_FINISHED,
                TableTennisLineEvent.starts_at.is_not(None),
                TableTennisLineEvent.starts_at < cutoff,
                or_(
                    and_(
                        TableTennisLineEvent.home_id == event.home_id,
                        TableTennisLineEvent.away_id == event.away_id,
                    ),
                    and_(
                        TableTennisLineEvent.home_id == event.away_id,
                        TableTennisLineEvent.away_id == event.home_id,
                    ),
                ),
            )
            .order_by(TableTennisLineEvent.starts_at.desc())
            .limit(50)
        )
    ).scalars().all()

    h2h_home_wins = 0
    h2h_away_wins = 0
    for row in h2h_rows:
        hs, as_ = _parse_sets_score(row.live_sets_score)
        if hs is None or as_ is None or hs == as_:
            continue
        if row.home_id == event.home_id:
            if hs > as_:
                h2h_home_wins += 1
            else:
                h2h_away_wins += 1
        else:
            if hs > as_:
                h2h_away_wins += 1
            else:
                h2h_home_wins += 1

    home_ctx = await _player_recent(str(event.home_id))
    away_ctx = await _player_recent(str(event.away_id))
    home_ctx["h2h_wins"] = h2h_home_wins
    away_ctx["h2h_wins"] = h2h_away_wins

    return {
        "home": home_ctx,
        "away": away_ctx,
        "h2h": {
            "total": h2h_home_wins + h2h_away_wins,
            "home_wins": h2h_home_wins,
            "away_wins": h2h_away_wins,
        },
    }


ALL_CHANNELS = ["free", "paid", "vip", "bot_signals", "no_ml", "nn"]


def _allowed_channels_and_resolved(access: dict, channel: str) -> tuple[list[str], bool]:
    """
    allowed_channels — всегда все вкладки видны.
    only_resolved — для запрошенного channel: True если нет доступа (показываем только hit/miss, без прогнозов и pending).
    """
    has_analytics = access["has_analytics"]
    has_no_ml = access.get("has_analytics_no_ml", False)
    has_vip = access["has_vip_channel"]

    if channel == "free":
        only_resolved = False  # бесплатный для всех
    elif channel == "paid":
        only_resolved = not has_analytics
    elif channel == "vip":
        only_resolved = not has_vip
    elif channel == "bot_signals":
        only_resolved = not has_analytics
    elif channel == "no_ml":
        # Аналитика без ML: отдельная услуга, доступ только при подписке analytics_no_ml.
        # Без неё показываем только уже завершённые прогнозы (hit/miss), без pending.
        only_resolved = not has_no_ml
    elif channel == "nn":
        only_resolved = not has_analytics
    else:
        only_resolved = True

    return ALL_CHANNELS, only_resolved


@router.get("/v2/forecasts/stats")
async def get_table_tennis_forecasts_v2_stats(
    date_from: str = "",
    date_to: str = "",
    league_id: str = "",
    channel: str = "paid",
    quality_tier: str = "",
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    access = await get_subscription_access(user.id, session)
    allowed, only_resolved = _allowed_channels_and_resolved(access, channel)

    dt_from = _parse_date_start_utc(date_from)
    dt_to_excl = _parse_date_end_utc_exclusive(date_to)
    if channel == "bot_signals":
        base_sent = (
            select(
                UserForecastNotification.event_id.label("event_id"),
                func.max(UserForecastNotification.forecast_v2_id).label("forecast_v2_id"),
                func.max(UserForecastNotification.sent_at).label("sent_at"),
            )
            .where(
                UserForecastNotification.user_id == user.id,
                UserForecastNotification.channel == "telegram",
            )
            .group_by(UserForecastNotification.event_id)
            .subquery()
        )
        conditions = []
        if dt_from is not None:
            conditions.append(base_sent.c.sent_at >= dt_from)
        if dt_to_excl is not None:
            conditions.append(base_sent.c.sent_at < dt_to_excl)
        if quality_tier:
            conditions.append(TableTennisForecastV2.explanation_summary.ilike(f"%Tier {quality_tier.upper()}%"))
        if league_id:
            conditions.append(TableTennisLineEvent.league_id == league_id)
        if only_resolved:
            conditions.append(TableTennisForecastV2.status.in_(["hit", "miss"]))

        by_status_rows = (
            await session.execute(
                select(TableTennisForecastV2.status, func.count())
                .join(base_sent, base_sent.c.forecast_v2_id == TableTennisForecastV2.id)
                .join(TableTennisLineEvent, TableTennisLineEvent.id == base_sent.c.event_id)
                .where(*conditions)
                .group_by(TableTennisForecastV2.status)
            )
        ).all()
        by_status: dict[str, int] = {str(status): int(cnt) for status, cnt in by_status_rows}
        total = sum(by_status.values())
        hits = by_status.get("hit", 0)
        misses = by_status.get("miss", 0)
        resolved = hits + misses
        hit_rate = (hits / resolved * 100.0) if resolved else None
        avg_odds = (
            await session.execute(
                select(func.avg(TableTennisForecastV2.odds_used))
                .join(base_sent, base_sent.c.forecast_v2_id == TableTennisForecastV2.id)
                .join(TableTennisLineEvent, TableTennisLineEvent.id == base_sent.c.event_id)
                .where(*conditions)
            )
        ).scalar_one_or_none()
        result = {
            "total": total,
            "by_status": by_status,
            "hit_rate": hit_rate,
            "avg_odds": float(avg_odds) if avg_odds is not None else None,
            "kpi_runtime": get_kpi_runtime_state(),
            "allowed_channels": allowed,
            "only_resolved": only_resolved,
        }
        if only_resolved:
            result["forecast_purchase_url"] = DASHBOARD_PURCHASE_URL
        return result

    conditions = [TableTennisForecastV2.channel == channel]
    if dt_from is not None:
        conditions.append(TableTennisForecastV2.created_at >= dt_from)
    if dt_to_excl is not None:
        conditions.append(TableTennisForecastV2.created_at < dt_to_excl)
    if quality_tier:
        conditions.append(TableTennisForecastV2.explanation_summary.ilike(f"%Tier {quality_tier.upper()}%"))
    if league_id:
        conditions.append(TableTennisLineEvent.league_id == league_id)
    if only_resolved:
        conditions.append(TableTennisForecastV2.status.in_(["hit", "miss"]))

    base = (
        select(TableTennisForecastV2.status, func.count())
        .join(TableTennisLineEvent, TableTennisLineEvent.id == TableTennisForecastV2.event_id)
        .where(*conditions)
        .group_by(TableTennisForecastV2.status)
    )
    by_status_rows = (await session.execute(base)).all()
    by_status: dict[str, int] = {str(status): int(cnt) for status, cnt in by_status_rows}

    total = sum(by_status.values())
    hits = by_status.get("hit", 0)
    misses = by_status.get("miss", 0)
    resolved = hits + misses
    hit_rate = (hits / resolved * 100.0) if resolved else None

    avg_odds_result = await session.execute(
        select(func.avg(TableTennisForecastV2.odds_used))
        .join(TableTennisLineEvent, TableTennisLineEvent.id == TableTennisForecastV2.event_id)
        .where(*conditions)
    )
    avg_odds = avg_odds_result.scalar_one_or_none()

    result = {
        "total": total,
        "by_status": by_status,
        "hit_rate": hit_rate,
        "avg_odds": float(avg_odds) if avg_odds is not None else None,
        "kpi_runtime": get_kpi_runtime_state(),
        "allowed_channels": allowed,
        "only_resolved": only_resolved,
    }
    if only_resolved:
        result["forecast_purchase_url"] = DASHBOARD_PURCHASE_URL
    return result


@router.get("/v2/forecasts")
async def get_table_tennis_forecasts_v2(
    page: int = 1,
    page_size: int = 50,
    status: str = "",
    league_id: str = "",
    date_from: str = "",
    date_to: str = "",
    channel: str = "paid",
    quality_tier: str = "",
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    access = await get_subscription_access(user.id, session)
    allowed, only_resolved = _allowed_channels_and_resolved(access, channel)

    p = _sanitize_page(page) if page > 0 else 1
    ps = _sanitize_page_size(page_size, max_size=250)
    offset = (p - 1) * ps if page > 0 else 0
    dt_from = _parse_date_start_utc(date_from)
    dt_to_excl = _parse_date_end_utc_exclusive(date_to)

    if channel == "bot_signals":
        base_sent = (
            select(
                UserForecastNotification.event_id.label("event_id"),
                func.max(UserForecastNotification.forecast_v2_id).label("forecast_v2_id"),
                func.max(UserForecastNotification.sent_at).label("sent_at"),
            )
            .where(
                UserForecastNotification.user_id == user.id,
                UserForecastNotification.channel == "telegram",
            )
            .group_by(UserForecastNotification.event_id)
            .subquery()
        )
        conditions = []
        if status:
            conditions.append(TableTennisForecastV2.status == status)
        elif only_resolved:
            conditions.append(TableTennisForecastV2.status.in_(["hit", "miss"]))
        if league_id:
            conditions.append(TableTennisLineEvent.league_id == league_id)
        if dt_from is not None:
            conditions.append(base_sent.c.sent_at >= dt_from)
        if dt_to_excl is not None:
            conditions.append(base_sent.c.sent_at < dt_to_excl)
        if quality_tier:
            conditions.append(TableTennisForecastV2.explanation_summary.ilike(f"%Tier {quality_tier.upper()}%"))

        total = int(
            (
                await session.execute(
                    select(func.count(base_sent.c.event_id))
                    .join(TableTennisForecastV2, TableTennisForecastV2.id == base_sent.c.forecast_v2_id)
                    .join(TableTennisLineEvent, TableTennisLineEvent.id == base_sent.c.event_id)
                    .where(*conditions)
                )
            ).scalar_one()
            or 0
        )
        stmt = (
            select(TableTennisForecastV2, TableTennisLineEvent)
            .join(base_sent, base_sent.c.forecast_v2_id == TableTennisForecastV2.id)
            .join(TableTennisLineEvent, TableTennisLineEvent.id == base_sent.c.event_id)
            .where(*conditions)
            .order_by(base_sent.c.sent_at.desc())
        )
        if page > 0:
            stmt = stmt.limit(ps).offset(offset)
        rows = (await session.execute(stmt)).all()
        forecast_ids = [f.id for f, _ev in rows]
        explanation_rows = (
            await session.execute(
                select(TableTennisForecastExplanation).where(
                    TableTennisForecastExplanation.forecast_v2_id.in_(forecast_ids or [-1])
                )
            )
        ).scalars().all()
        by_forecast: dict[int, list[TableTennisForecastExplanation]] = {}
        for exp in explanation_rows:
            by_forecast.setdefault(exp.forecast_v2_id, []).append(exp)
        items = [
            _forecast_v2_item(forecast, event, by_forecast.get(forecast.id, []))
            for forecast, event in rows
        ]
        result = {
            "items": items,
            "page": p if page > 0 else 1,
            "page_size": ps if page > 0 else total,
            "total": total,
            "allowed_channels": allowed,
            "only_resolved": only_resolved,
        }
        if only_resolved:
            result["forecast_purchase_url"] = DASHBOARD_PURCHASE_URL
        return result

    conditions = [TableTennisForecastV2.channel == channel]
    if status:
        conditions.append(TableTennisForecastV2.status == status)
    elif only_resolved:
        conditions.append(TableTennisForecastV2.status.in_(["hit", "miss"]))
    if league_id:
        conditions.append(TableTennisLineEvent.league_id == league_id)
    if dt_from is not None:
        conditions.append(TableTennisForecastV2.created_at >= dt_from)
    if dt_to_excl is not None:
        conditions.append(TableTennisForecastV2.created_at < dt_to_excl)
    if quality_tier:
        conditions.append(TableTennisForecastV2.explanation_summary.ilike(f"%Tier {quality_tier.upper()}%"))

    total = int(
        (
            await session.execute(
                select(func.count(TableTennisForecastV2.id))
                .join(TableTennisLineEvent, TableTennisLineEvent.id == TableTennisForecastV2.event_id)
                .where(*conditions)
            )
        ).scalar_one()
        or 0
    )

    stmt = (
        select(TableTennisForecastV2, TableTennisLineEvent)
        .join(TableTennisLineEvent, TableTennisLineEvent.id == TableTennisForecastV2.event_id)
        .where(*conditions)
        .order_by(TableTennisForecastV2.created_at.desc())
    )
    if page > 0:
        stmt = stmt.limit(ps).offset(offset)

    rows = (await session.execute(stmt)).all()
    forecast_ids = [f.id for f, _ev in rows]
    explanation_rows = (
        await session.execute(
            select(TableTennisForecastExplanation).where(
                TableTennisForecastExplanation.forecast_v2_id.in_(forecast_ids or [-1])
            )
        )
    ).scalars().all()
    by_forecast: dict[int, list[TableTennisForecastExplanation]] = {}
    for exp in explanation_rows:
        by_forecast.setdefault(exp.forecast_v2_id, []).append(exp)

    items = [
        _forecast_v2_item(forecast, event, by_forecast.get(forecast.id, []))
        for forecast, event in rows
    ]
    result = {
        "items": items,
        "page": p if page > 0 else 1,
        "page_size": ps if page > 0 else total,
        "total": total,
        "allowed_channels": allowed,
        "only_resolved": only_resolved,
    }
    if only_resolved:
        result["forecast_purchase_url"] = DASHBOARD_PURCHASE_URL
    return result


@router.get("/v2/matches/{match_id}")
async def get_table_tennis_match_card_v2(
    match_id: str,
    channel: str = "paid",
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    access = await get_subscription_access(user.id, session)
    if not access["can_see_forecasts"]:
        event = (
            await session.execute(select(TableTennisLineEvent).where(TableTennisLineEvent.id == str(match_id)))
        ).scalar_one_or_none()
        if event is None:
            return {"match": None}
        return {
            "match": _event_to_dict(event),
            "forecast_v2": None,
            "player_context": await _build_player_match_context(session, event),
            "forecast_locked": True,
            "forecast_locked_message": FORECAST_LOCKED_ANALYTICS,
            "forecast_purchase_url": DASHBOARD_PURCHASE_URL,
            "ml_analytics": None,
        }
    if access["forecast_channel"]:
        channel = access["forecast_channel"]
    if access["only_resolved"]:
        # For VIP-only, only return forecast if it's resolved
        pass  # handled in forecast fetch below

    event = (
        await session.execute(select(TableTennisLineEvent).where(TableTennisLineEvent.id == str(match_id)))
    ).scalar_one_or_none()
    if event is None:
        return {"match": None}

    forecast_conditions = [
        TableTennisForecastV2.event_id == event.id,
        TableTennisForecastV2.channel == channel,
    ]
    if access["only_resolved"]:
        forecast_conditions.append(TableTennisForecastV2.status.in_(["hit", "miss"]))
    forecast = (
        await session.execute(
            select(TableTennisForecastV2)
            .where(and_(*forecast_conditions))
            .order_by(TableTennisForecastV2.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    explanations: list[TableTennisForecastExplanation] = []
    if forecast:
        explanations = (
            await session.execute(
                select(TableTennisForecastExplanation).where(
                    TableTennisForecastExplanation.forecast_v2_id == forecast.id
                )
            )
        ).scalars().all()

    player_context = await _build_player_match_context(session, event)
    ml_analytics = _compute_ml_analytics(event)

    return {
        "match": _event_to_dict(event),
        "forecast_v2": _forecast_v2_item(forecast, event, explanations) if forecast else None,
        "player_context": player_context,
        "ml_analytics": ml_analytics,
    }


@router.get("/v2/players/{player_id}")
async def get_table_tennis_player_card_v2(
    player_id: str,
    channel: str = "paid",
    page_upcoming: int = 1,
    page_finished: int = 1,
    page_size: int = 15,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    ps = _sanitize_page_size(page_size, max_size=50)
    p_up = _sanitize_page(page_upcoming)
    p_fin = _sanitize_page(page_finished)
    now = datetime.now(timezone.utc)

    # Reuse existing player endpoint and enrich with V2 forecasts.
    access = await get_subscription_access(user.id, session)
    player_data = await get_table_tennis_player_card(
        player_id=player_id,
        page_upcoming=p_up,
        page_finished=p_fin,
        page_size=ps,
        user=user,
        session=session,
    )
    if not player_data.get("player"):
        return player_data

    analytics_locked = not access["can_see_forecasts"]
    if analytics_locked:
        player_data["forecast_locked"] = True
        player_data["forecast_locked_message"] = FORECAST_LOCKED_ANALYTICS
        player_data["forecast_purchase_url"] = DASHBOARD_PURCHASE_URL
        player_data["stats"] = None
        for group_key in ("upcoming_matches", "finished_matches"):
            for item in (player_data.get(group_key) or []):
                if isinstance(item, dict):
                    item.pop("forecast_v2", None)
        player_data["v2_channel"] = channel
        player_data["now"] = int(now.timestamp())
        return player_data

    upcoming_items = player_data.get("upcoming_matches") or []
    finished_items = player_data.get("finished_matches") or []
    event_ids = [
        str(item.get("id"))
        for item in (upcoming_items + finished_items)
        if isinstance(item, dict) and item.get("id")
    ]
    forecast_rows = (
        await session.execute(
            select(TableTennisForecastV2)
            .where(
                and_(
                    TableTennisForecastV2.event_id.in_(event_ids or ["-1"]),
                    TableTennisForecastV2.channel == channel,
                )
            )
            .order_by(TableTennisForecastV2.created_at.desc())
        )
    ).scalars().all()
    forecasts_by_event: dict[str, dict] = {}
    for fc in forecast_rows:
        forecasts_by_event.setdefault(fc.event_id, {
            "forecast_text": fc.forecast_text,
            "status": fc.status,
            "odds_used": float(fc.odds_used) if fc.odds_used is not None else None,
            "probability_pct": float(fc.probability_pct) if fc.probability_pct is not None else None,
        })

    for group_key in ("upcoming_matches", "finished_matches"):
        group_items = player_data.get(group_key) or []
        for item in group_items:
            if isinstance(item, dict):
                item["forecast_v2"] = forecasts_by_event.get(str(item.get("id")))

    player_data["v2_channel"] = channel
    player_data["now"] = int(now.timestamp())
    return player_data


@router.get("/v2/debug/kpi")
async def get_table_tennis_v2_kpi_debug(recompute: bool = False):
    state = await run_kpi_guard_once() if recompute else get_kpi_runtime_state()
    return {"kpi": state}


@router.post("/v2/debug/run-once")
async def run_table_tennis_v2_once(
    run_forecast: bool = True,
    run_results: bool = True,
):
    forecasts = await run_forecast_v2_once() if run_forecast else 0
    resolved = await run_result_priority_once() if run_results else 0
    kpi = await run_kpi_guard_once()
    validation = await run_validation_checks_once()
    return {
        "forecasts_created_or_updated": forecasts,
        "resolved_outcomes": resolved,
        "kpi": kpi,
        "validation": validation,
    }


@router.get("/v2/debug/validate")
async def get_table_tennis_v2_validation():
    return await run_validation_checks_once()


@router.post("/v2/debug/notifications/run-once")
async def run_table_tennis_notifications_once():
    return await dispatch_forecast_notifications_once()


@router.post("/v2/debug/channel-dispatch/run-once")
async def run_table_tennis_channel_dispatch_once():
    return await dispatch_channel_notifications_once()


@router.get("/players")
async def get_table_tennis_players(
    page: int = 1,
    page_size: int = 30,
    q: str = "",
    user: User = Depends(get_current_user),
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
    user: User = Depends(get_current_user),
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
async def get_table_tennis_match_card(
    match_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Legacy match card. Prefer /v2/matches/{id} which has subscription gating."""
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

    access = await get_subscription_access(user.id, session)
    if not access["can_see_forecasts"]:
        return {
            "match": _event_to_dict(match),
            "home_stats": None,
            "away_stats": None,
            "forecast": FORECAST_LOCKED_ANALYTICS,
            "forecast_confidence": None,
            "analytics": None,
            "forecast_locked": True,
            "forecast_locked_message": FORECAST_LOCKED_ANALYTICS,
            "forecast_purchase_url": DASHBOARD_PURCHASE_URL,
        }

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


def _event_to_dict_safe(r: TableTennisLineEvent, hide_forecast: bool = False) -> dict:
    d = _event_to_dict(r)
    if hide_forecast:
        d["forecast"] = None
        d["forecast_confidence"] = None
    return d


@router.get("/players/{player_id}/card")
async def get_table_tennis_player_card(
    player_id: str,
    page_upcoming: int = 1,
    page_finished: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user),
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
    access = await get_subscription_access(user.id, session)
    hide_forecast = not access["can_see_forecasts"]
    upcoming = [_event_to_dict_safe(r, hide_forecast) for r in list(upcoming_rows_result.scalars().all())]
    finished = [_event_to_dict_safe(r, hide_forecast) for r in list(finished_rows_result.scalars().all())]

    resp: dict = {
        "player": {"id": str(player_id), "name": player_name or "Игрок"},
        "stats": _build_player_stats(str(player_id), rows, now) if access["can_see_forecasts"] else None,
        "upcoming_matches": upcoming,
        "finished_matches": finished,
        "pagination": {
            "upcoming": {"page": p_up, "page_size": ps, "total": total_upcoming},
            "finished": {"page": p_fin, "page_size": ps, "total": total_finished},
        },
    }
    if hide_forecast:
        resp["forecast_locked"] = True
        resp["forecast_locked_message"] = FORECAST_LOCKED_ANALYTICS
        resp["forecast_purchase_url"] = DASHBOARD_PURCHASE_URL
    return resp


@router.get("/leagues/{league_id}/card")
async def get_table_tennis_league_card(
    league_id: str,
    page_upcoming: int = 1,
    page_finished: int = 1,
    page_size: int = 20,
    date_from: str = "",
    date_to: str = "",
    user: User = Depends(get_current_user),
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
    access = await get_subscription_access(user.id, session)
    hide_forecast = not access["can_see_forecasts"]
    upcoming = [_event_to_dict_safe(r, hide_forecast) for r in list(upcoming_rows_result.scalars().all())]
    finished = [_event_to_dict_safe(r, hide_forecast) for r in list(finished_rows_result.scalars().all())]

    resp: dict = {
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
    if hide_forecast:
        resp["forecast_locked"] = True
        resp["forecast_locked_message"] = FORECAST_LOCKED_ANALYTICS
        resp["forecast_purchase_url"] = DASHBOARD_PURCHASE_URL
    return resp


async def _line_sse_generator(user: User):
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
                access = await get_subscription_access(user.id, session)
                if not access["can_see_forecasts"]:
                    forecast_map_ml = None
                    forecast_map_no_ml = None
                    forecast_map_nn = None
                    forecast_placeholder = FORECAST_LOCKED_ANALYTICS
                    forecast_locked = True
                    forecast_purchase_url = DASHBOARD_PURCHASE_URL
                else:
                    ch = access["forecast_channel"] or "paid"
                    if access["only_resolved"]:
                        forecast_map_ml = await _load_v2_forecast_map_resolved_only(
                            session, [str(r.id) for r in rows], channel=ch
                        )
                    else:
                        forecast_map_ml = await _load_v2_forecast_map(
                            session, [str(r.id) for r in rows], channel=ch
                        )
                    if access.get("has_analytics_no_ml", False):
                        forecast_map_no_ml = await _load_v2_forecast_map(
                            session, [str(r.id) for r in rows], channel="no_ml"
                        )
                    else:
                        forecast_map_no_ml = None
                    if access.get("has_analytics", False):
                        forecast_map_nn = await _load_v2_forecast_map(
                            session, [str(r.id) for r in rows], channel="nn"
                        )
                    else:
                        forecast_map_nn = None
                    forecast_placeholder = None
                    forecast_locked = False
                    forecast_purchase_url = None
            payload = _build_line_response(
                rows,
                forecast_map_ml=forecast_map_ml,
                forecast_map_no_ml=forecast_map_no_ml,
                forecast_map_nn=forecast_map_nn,
            )
            if forecast_locked:
                for ev in payload.get("events", []):
                    ev["forecast"] = forecast_placeholder
                payload["forecast_locked"] = True
                payload["forecast_locked_message"] = forecast_placeholder
                payload["forecast_purchase_url"] = forecast_purchase_url
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass


async def _forecasts_v2_sse_generator(
    user: User,
    channel: str = "paid",
    quality_tier: str = "",
):
    """SSE for V2 forecasts and stats."""
    interval = max(5, int(getattr(settings, "line_sse_interval_sec", 5)))
    try:
        while True:
            async with async_session_maker() as session:
                stats = await get_table_tennis_forecasts_v2_stats(
                    date_from="",
                    date_to="",
                    league_id="",
                    channel=channel,
                    quality_tier=quality_tier,
                    user=user,
                    session=session,
                )
                forecasts = await get_table_tennis_forecasts_v2(
                    page=0,
                    page_size=500,
                    status="",
                    league_id="",
                    date_from="",
                    date_to="",
                    channel=channel,
                    quality_tier=quality_tier,
                    user=user,
                    session=session,
                )
            payload = {
                "stats": stats,
                "forecasts": forecasts,
                "updated_at": int(datetime.now(timezone.utc).timestamp()),
            }
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass


@router.get("/line/stream")
async def stream_table_tennis_line(user: User = Depends(get_current_user)):
    """SSE-поток линии: обновление статусов, коэфов и списка матчей без перезагрузки страницы."""
    return StreamingResponse(
        _line_sse_generator(user),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/v2/forecasts/stream")
async def stream_table_tennis_forecasts_v2(
    channel: str = "paid",
    quality_tier: str = "",
    user: User = Depends(get_current_user),
):
    return StreamingResponse(
        _forecasts_v2_sse_generator(user=user, channel=channel, quality_tier=quality_tier),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

async def _live_sse_generator(user: User):
    """SSE: периодически отдаёт актуальный список лайв-матчей (live + свежие finished)."""
    interval = max(5, getattr(settings, "line_sse_interval_sec", 5))
    try:
        while True:
            now = datetime.now(timezone.utc)
            five_minutes_ago = now - timedelta(minutes=5)
            live_freshness_cutoff = now - timedelta(minutes=30)
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
                                    TableTennisLineEvent.updated_at >= live_freshness_cutoff,
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
                access = await get_subscription_access(user.id, session)
                if not access["can_see_forecasts"]:
                    forecast_map_ml = None
                    forecast_map_no_ml = None
                    forecast_map_nn = None
                    forecast_placeholder = FORECAST_LOCKED_ANALYTICS
                    forecast_locked = True
                    forecast_purchase_url = DASHBOARD_PURCHASE_URL
                else:
                    ch = access["forecast_channel"] or "paid"
                    if access["only_resolved"]:
                        forecast_map_ml = await _load_v2_forecast_map_resolved_only(
                            session, [str(r.id) for r in rows], channel=ch
                        )
                    else:
                        forecast_map_ml = await _load_v2_forecast_map(
                            session, [str(r.id) for r in rows], channel=ch
                        )
                    if access.get("has_analytics_no_ml", False):
                        forecast_map_no_ml = await _load_v2_forecast_map(
                            session, [str(r.id) for r in rows], channel="no_ml"
                        )
                    else:
                        forecast_map_no_ml = None
                    if access.get("has_analytics", False):
                        forecast_map_nn = await _load_v2_forecast_map(
                            session, [str(r.id) for r in rows], channel="nn"
                        )
                    else:
                        forecast_map_nn = None
                    forecast_placeholder = None
                    forecast_locked = False
                    forecast_purchase_url = None
            payload = _build_live_response(
                rows,
                forecast_map_ml=forecast_map_ml,
                forecast_map_no_ml=forecast_map_no_ml,
                forecast_map_nn=forecast_map_nn,
            )
            if forecast_locked:
                for ev in payload.get("events", []):
                    ev["forecast"] = forecast_placeholder
                payload["forecast_locked"] = True
                payload["forecast_locked_message"] = forecast_placeholder
                payload["forecast_purchase_url"] = forecast_purchase_url
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass


@router.get("/live/stream")
async def stream_table_tennis_live(user: User = Depends(get_current_user)):
    """SSE-поток лайва: обновление статусов, коэфов и счёта без перезагрузки страницы."""
    return StreamingResponse(
        _live_sse_generator(user),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
