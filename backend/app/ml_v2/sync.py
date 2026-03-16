"""Sync finished matches from main DB to ClickHouse ML v2."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import logging
import math

from sqlalchemy import and_, select

from app.db.session import async_session_maker
from app.models.table_tennis_line_event import LINE_EVENT_STATUS_FINISHED, TableTennisLineEvent
from app.ml_v2.ch_client import get_ch_client
from app.ml_v2.state import get_job_cursor, set_job_cursor
from app.ml_v2.schema import ensure_schema

logger = logging.getLogger(__name__)

DEFAULT_ELO = 1500.0
K_FACTOR = 32.0  # K=32 для более отзывчивого рейтинга (TT)


def _parse_sets_score(value: str | None) -> tuple[int | None, int | None]:
    if not value or "-" not in value:
        return None, None
    left, right = value.split("-", 1)
    try:
        return int(left), int(right)
    except (TypeError, ValueError):
        return None, None


def _parse_live_score(live_score: dict | None) -> list[tuple[int, int]]:
    if not isinstance(live_score, dict):
        return []
    out: list[tuple[int, int]] = []
    for key in sorted(live_score.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
        row = live_score.get(key)
        if not isinstance(row, dict):
            continue
        try:
            out.append((int(row.get("home") or 0), int(row.get("away") or 0)))
        except (TypeError, ValueError):
            continue
    return out


def _expected(r_a: float, r_b: float) -> float:
    return 1.0 / (1.0 + math.pow(10.0, (r_b - r_a) / 400.0))


def recompute_elo_from_matches() -> dict[str, int]:
    """Пересчитывает рейтинг всех игроков с самого первого матча. Источник истины — ml.matches ORDER BY start_time.
    Один источник данных, без привязки к odds. Заполняет ml.player_elo_history заново (TRUNCATE + INSERT).
    Игрок везде идентифицируется по player_id (player1_id/player2_id в матче), не по имени и не по позиции (P1/P2)."""
    ensure_schema()
    client = get_ch_client()
    rows = client.query(
        """
        SELECT match_id, start_time, player1_id, player2_id, score_sets_p1, score_sets_p2
        FROM ml.matches
        ORDER BY start_time ASC
        """
    ).result_rows
    if not rows:
        logger.info("recompute_elo_from_matches: no matches in ml.matches")
        return {"recomputed_matches": 0, "elo_rows": 0}

    ratings: dict[str, float] = defaultdict(lambda: DEFAULT_ELO)
    now = datetime.now(timezone.utc)
    elo_rows: list[list] = []
    for row in rows:
        match_id = str(row[0])
        start_time = row[1]
        if isinstance(start_time, datetime) and start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        p1 = str(row[2] or "")
        p2 = str(row[3] or "")
        s1 = int(row[4] or 0)
        s2 = int(row[5] or 0)
        if not p1 or not p2:
            continue
        r1 = ratings[p1]
        r2 = ratings[p2]
        expected1 = _expected(r1, r2)
        result1 = 1.0 if s1 > s2 else 0.0
        new_r1 = r1 + K_FACTOR * (result1 - expected1)
        new_r2 = r2 + K_FACTOR * ((1.0 - result1) - (1.0 - expected1))
        ratings[p1] = new_r1
        ratings[p2] = new_r2
        elo_rows.append([p1, match_id, start_time, r1, new_r1, now])
        elo_rows.append([p2, match_id, start_time, r2, new_r2, now])

    client.command("TRUNCATE TABLE IF EXISTS ml.player_elo_history")
    if elo_rows:
        client.insert(
            "ml.player_elo_history",
            elo_rows,
            column_names=["player_id", "match_id", "match_time", "elo_before", "elo_after", "created_at"],
        )
    logger.info(
        "recompute_elo_from_matches: recomputed %s matches, %s elo history rows",
        len(rows),
        len(elo_rows),
    )
    return {"recomputed_matches": len(rows), "elo_rows": len(elo_rows)}


def _fetch_latest_elo(player_ids: set[str]) -> dict[str, float]:
    if not player_ids:
        return {}
    client = get_ch_client()
    rows = client.query(
        """
        SELECT player_id, argMax(elo_after, match_time) AS elo
        FROM ml.player_elo_history
        WHERE player_id IN %(ids)s
        GROUP BY player_id
        """,
        {"ids": tuple(player_ids)},
    ).result_rows
    return {str(r[0]): float(r[1]) for r in rows}


def _fetch_existing_match_ids(ids: list[str], chunk_size: int = 1500) -> set[str]:
    """Read existing CH match ids in safe chunks to avoid max_query_size errors."""
    if not ids:
        return set()
    client = get_ch_client()
    out: set[str] = set()
    step = max(100, int(chunk_size or 1500))
    for i in range(0, len(ids), step):
        batch = tuple(ids[i : i + step])
        if not batch:
            continue
        rows = client.query(
            "SELECT match_id FROM ml.matches WHERE match_id IN %(ids)s",
            {"ids": batch},
        ).result_rows
        out.update(str(r[0]) for r in rows)
    return out


def _parse_cursor(raw: str) -> tuple[datetime | None, str]:
    if not raw:
        return None, ""
    if "|" in raw:
        dt_raw, id_raw = raw.split("|", 1)
        try:
            dt = datetime.fromisoformat(dt_raw)
        except ValueError:
            dt = None
        event_id = str(id_raw or "").strip()
        return dt, event_id
    try:
        return datetime.fromisoformat(raw), ""
    except ValueError:
        return None, ""


def _cursor_value(dt: datetime, event_id: str) -> str:
    return f"{dt.isoformat()}|{str(event_id or '').strip()}"


def _insert_events_to_ch(events: list[TableTennisLineEvent], *, update_cursor: bool = True) -> dict[str, int]:
    if not events:
        return {"synced": 0}
    ensure_schema()
    client = get_ch_client()
    # Рейтинг не считаем в цикле — заполняем только из recompute_elo_from_matches() по ml.matches.
    players_rows: list[list] = []
    leagues_rows: list[list] = []
    matches_rows: list[list] = []
    sets_rows: list[list] = []
    stats_rows: list[list] = []

    last_dt: datetime | None = None
    last_event_id = ""
    for e in events:
        hs, as_ = _parse_sets_score(e.live_sets_score)
        if hs is None or as_ is None:
            continue
        sets_data = _parse_live_score(e.live_score)
        if not sets_data and (hs + as_) > 0:
            sets_data = [(hs, as_)]
        points_p1 = sum(x for x, _ in sets_data) if sets_data else hs * 11
        points_p2 = sum(y for _, y in sets_data) if sets_data else as_ * 11
        start_time = e.starts_at if isinstance(e.starts_at, datetime) else datetime.now(timezone.utc)
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)

        pid1 = str(e.home_id)
        pid2 = str(e.away_id)

        set1_win = 0
        if sets_data:
            set1_win = 1 if sets_data[0][0] > sets_data[0][1] else 0

        players_rows.append([pid1, str(e.home_name or ""), datetime.now(timezone.utc)])
        players_rows.append([pid2, str(e.away_name or ""), datetime.now(timezone.utc)])
        leagues_rows.append([str(e.league_id or ""), str(e.league_name or ""), datetime.now(timezone.utc)])
        matches_rows.append(
            [
                str(e.id),
                start_time,
                str(e.league_id or ""),
                pid1,
                pid2,
                int(hs),
                int(as_),
                float(e.odds_1 or 0.0),
                float(e.odds_2 or 0.0),
            ]
        )
        for i, (s1, s2) in enumerate(sets_data, start=1):
            sets_rows.append([str(e.id), i, int(s1), int(s2), datetime.now(timezone.utc)])
        duration = 0
        if getattr(e, "finished_at", None):
            duration = max(0, int((e.finished_at - start_time).total_seconds() / 60))
        stats_rows.append(
            [
                pid1,
                str(e.id),
                start_time,
                str(e.league_id or ""),
                1 if hs > as_ else 0,
                set1_win,
                int(hs),
                int(as_),
                int(points_p1),
                int(points_p2),
                int(duration),
                datetime.now(timezone.utc),
            ]
        )
        stats_rows.append(
            [
                pid2,
                str(e.id),
                start_time,
                str(e.league_id or ""),
                1 if as_ > hs else 0,
                1 - set1_win,
                int(as_),
                int(hs),
                int(points_p2),
                int(points_p1),
                int(duration),
                datetime.now(timezone.utc),
            ]
        )
        last_dt = start_time
        last_event_id = str(e.id or "")

    if players_rows:
        client.insert("ml.players", players_rows, column_names=["player_id", "player_name", "updated_at"])
    if leagues_rows:
        client.insert("ml.leagues", leagues_rows, column_names=["league_id", "league_name", "updated_at"])
    if matches_rows:
        client.insert(
            "ml.matches",
            matches_rows,
            column_names=[
                "match_id",
                "start_time",
                "league_id",
                "player1_id",
                "player2_id",
                "score_sets_p1",
                "score_sets_p2",
                "odds_p1",
                "odds_p2",
            ],
        )
    if sets_rows:
        client.insert("ml.match_sets", sets_rows, column_names=["match_id", "set_number", "score_p1", "score_p2", "created_at"])
    # Рейтинг — только из полного пересчёта по ml.matches (один источник истины, порядок по start_time).
    if matches_rows:
        recompute_elo_from_matches()
    if stats_rows:
        client.insert(
            "ml.player_match_stats",
            stats_rows,
            column_names=[
                "player_id",
                "match_id",
                "match_time",
                "league_id",
                "win",
                "set1_win",
                "sets_won",
                "sets_lost",
                "points_won",
                "points_lost",
                "duration_minutes",
                "created_at",
            ],
        )
        # Keep player_daily_stats up-to-date for the same player/date keys.
        _refresh_player_daily_stats_for_stats_rows(stats_rows)
    if update_cursor and last_dt is not None:
        set_job_cursor("sync_finished_cursor_v2", _cursor_value(last_dt, last_event_id))
    return {"synced": len(matches_rows)}


def _refresh_player_daily_stats_for_stats_rows(stats_rows: list[list]) -> int:
    """Recompute player_daily_stats for keys affected by inserted player_match_stats rows."""
    if not stats_rows:
        return 0
    client = get_ch_client()
    affected: set[tuple[str, datetime.date]] = set()
    player_ids: set[str] = set()
    min_dt: datetime | None = None
    max_dt: datetime | None = None
    for row in stats_rows:
        pid = str(row[0])
        mt = row[2]
        if not isinstance(mt, datetime):
            continue
        if mt.tzinfo is None:
            mt = mt.replace(tzinfo=timezone.utc)
        player_ids.add(pid)
        affected.add((pid, mt.date()))
        min_dt = mt if min_dt is None or mt < min_dt else min_dt
        max_dt = mt if max_dt is None or mt > max_dt else max_dt
    if not affected or min_dt is None or max_dt is None:
        return 0
    # Inclusive day window for affected keys.
    start_dt = datetime(min_dt.year, min_dt.month, min_dt.day, tzinfo=timezone.utc)
    end_day = datetime(max_dt.year, max_dt.month, max_dt.day, tzinfo=timezone.utc) + timedelta(days=1)
    rows = client.query(
        """
        SELECT
          player_id,
          toDate(match_time) AS d,
          count() AS matches_today,
          sum(sets_won + sets_lost) AS sets_today,
          sum(duration_minutes) AS minutes_today,
          sum(win) AS wins_today,
          count() - sum(win) AS losses_today
        FROM ml.player_match_stats FINAL
        WHERE player_id IN %(ids)s
          AND match_time >= %(from_dt)s
          AND match_time < %(to_dt)s
        GROUP BY player_id, d
        """,
        {"ids": tuple(player_ids), "from_dt": start_dt, "to_dt": end_day},
    ).result_rows
    out_rows: list[list] = []
    for pid, d, m, s, mins, w, l in rows:
        key = (str(pid), d)
        if key not in affected:
            continue
        out_rows.append(
            [
                str(pid),
                d,
                int(m or 0),
                int(s or 0),
                int(mins or 0),
                int(w or 0),
                int(l or 0),
                datetime.now(timezone.utc),
            ]
        )
    if not out_rows:
        return 0
    client.insert(
        "ml.player_daily_stats",
        out_rows,
        column_names=[
            "player_id",
            "date",
            "matches_today",
            "sets_today",
            "minutes_today",
            "wins_today",
            "losses_today",
            "created_at",
        ],
    )
    return len(out_rows)


async def backfill_match_sets_from_main(limit: int = 2000) -> dict[str, int]:
    """Дозаполняет ml.match_sets для матчей, которые уже есть в ml.matches, но без сетов.
    Источник: main DB (TableTennisLineEvent.live_sets_score, live_score). Вызывать из sync-loop или вручную.
    Используем ту же логику, что и в статусе: без FINAL, по уникальным match_id (GROUP BY), чтобы разрыв
    совпадал с отображением в админке и запрос реально возвращал недостающие id."""
    ensure_schema()
    client = get_ch_client()
    lim = max(100, min(int(limit or 2000), 20000))
    # Без FINAL — как в админке (uniqExact), иначе с FINAL запрос может вернуть 0 при фактическом разрыве
    q_missing = (
        """
        SELECT m.match_id
        FROM (SELECT match_id FROM ml.matches GROUP BY match_id) AS m
        LEFT JOIN (SELECT match_id FROM ml.match_sets GROUP BY match_id) AS s ON m.match_id = s.match_id
        WHERE s.match_id IS NULL
        LIMIT """
        + str(lim)
    )
    missing_rows = client.query(q_missing).result_rows
    missing_ids = [str(r[0]) for r in missing_rows]
    if not missing_ids:
        return {"filled": 0, "sets_inserted": 0, "remaining": 0}

    async with async_session_maker() as session:
        stmt = select(TableTennisLineEvent).where(
            TableTennisLineEvent.id.in_(missing_ids),
            TableTennisLineEvent.live_sets_score.is_not(None),
        )
        events = (await session.execute(stmt)).scalars().all()

    if not events and missing_ids:
        logger.warning(
            "backfill_match_sets: в main DB нет live_sets_score для %s матчей из CH (id в первых 5: %s). Заполните счета в table_tennis_line_events.",
            len(missing_ids),
            missing_ids[:5],
        )

    sets_rows: list[list] = []
    now = datetime.now(timezone.utc)
    for e in events:
        hs, as_ = _parse_sets_score(e.live_sets_score)
        if hs is None or as_ is None:
            continue
        sets_data = _parse_live_score(e.live_score)
        if not sets_data and (hs + as_) > 0:
            sets_data = [(hs, as_)]
        if not sets_data:
            continue
        for i, (s1, s2) in enumerate(sets_data, start=1):
            sets_rows.append([str(e.id), i, int(s1), int(s2), now])

    if sets_rows:
        client.insert(
            "ml.match_sets",
            sets_rows,
            column_names=["match_id", "set_number", "score_p1", "score_p2", "created_at"],
        )
    # Оценка оставшихся: тот же запрос без FINAL (как при подсчёте разрыва в админке)
    remaining_rows = client.query(
        """
        SELECT count()
        FROM (SELECT match_id FROM ml.matches GROUP BY match_id) AS m
        LEFT JOIN (SELECT match_id FROM ml.match_sets GROUP BY match_id) AS s ON m.match_id = s.match_id
        WHERE s.match_id IS NULL
        """
    ).result_rows
    remaining = int(remaining_rows[0][0]) if remaining_rows else 0
    match_ids_filled = len({r[0] for r in sets_rows}) if sets_rows else 0
    return {
        "filled": match_ids_filled,
        "sets_inserted": len(sets_rows),
        "remaining": remaining,
    }


def sync_player_daily_stats_to_ch_once(limit: int = 50000) -> dict[str, int]:
    """Backfill player_daily_stats from existing ml.player_match_stats in CH."""
    ensure_schema()
    client = get_ch_client()
    cursor_raw = get_job_cursor("sync_player_daily_stats_cursor_v2", default="")
    cursor_dt, cursor_mid = _parse_cursor(cursor_raw)
    lim = max(1000, int(limit or 1000))
    params: dict[str, object] = {"lim": lim}
    query = """
        SELECT player_id, match_time, match_id
        FROM ml.player_match_stats FINAL
    """
    if cursor_dt is not None:
        query += """
        WHERE (match_time > %(cursor_dt)s)
           OR (match_time = %(cursor_dt)s AND match_id > %(cursor_mid)s)
        """
        params["cursor_dt"] = cursor_dt
        params["cursor_mid"] = str(cursor_mid or "")
    query += " ORDER BY match_time ASC, match_id ASC LIMIT %(lim)s"
    chunk = client.query(query, params).result_rows
    if not chunk:
        return {"updated": 0, "fetched": 0, "done": True}
    by_player: set[str] = set()
    by_day: set[datetime.date] = set()
    last_dt = None
    last_mid = ""
    for pid, mt, mid in chunk:
        pid_s = str(pid)
        mt_u = mt if mt.tzinfo is not None else mt.replace(tzinfo=timezone.utc)
        by_player.add(pid_s)
        by_day.add(mt_u.date())
        last_dt = mt_u
        last_mid = str(mid or "")
    min_day = min(by_day)
    max_day = max(by_day)
    from_dt = datetime(min_day.year, min_day.month, min_day.day, tzinfo=timezone.utc)
    to_dt = datetime(max_day.year, max_day.month, max_day.day, tzinfo=timezone.utc) + timedelta(days=1)
    agg_rows = client.query(
        """
        SELECT
          player_id,
          toDate(match_time) AS d,
          count() AS matches_today,
          sum(sets_won + sets_lost) AS sets_today,
          sum(duration_minutes) AS minutes_today,
          sum(win) AS wins_today,
          count() - sum(win) AS losses_today
        FROM ml.player_match_stats FINAL
        WHERE player_id IN %(ids)s
          AND match_time >= %(from_dt)s
          AND match_time < %(to_dt)s
        GROUP BY player_id, d
        """,
        {"ids": tuple(by_player), "from_dt": from_dt, "to_dt": to_dt},
    ).result_rows
    affected = {(str(pid), d) for pid, d, _mt, _st, _min, _w, _l in agg_rows}
    out_rows: list[list] = []
    now = datetime.now(timezone.utc)
    for pid, d, m, s, mins, w, l in agg_rows:
        if (str(pid), d) not in affected:
            continue
        out_rows.append([str(pid), d, int(m or 0), int(s or 0), int(mins or 0), int(w or 0), int(l or 0), now])
    if out_rows:
        client.insert(
            "ml.player_daily_stats",
            out_rows,
            column_names=[
                "player_id",
                "date",
                "matches_today",
                "sets_today",
                "minutes_today",
                "wins_today",
                "losses_today",
                "created_at",
            ],
        )
    if last_dt is not None:
        set_job_cursor("sync_player_daily_stats_cursor_v2", _cursor_value(last_dt, last_mid))
    return {
        "updated": len(out_rows),
        "fetched": len(chunk),
        "done": len(chunk) < lim,
    }


async def sync_finished_to_ch_once(limit: int = 5000) -> dict[str, int]:
    cursor_raw = get_job_cursor("sync_finished_cursor_v2", default="")
    cursor_dt, cursor_event_id = _parse_cursor(cursor_raw)

    async with async_session_maker() as session:
        stmt = (
            select(TableTennisLineEvent)
            .where(TableTennisLineEvent.status == LINE_EVENT_STATUS_FINISHED)
            .order_by(TableTennisLineEvent.starts_at.asc(), TableTennisLineEvent.id.asc())
            .limit(limit)
        )
        if cursor_dt is not None:
            stmt = stmt.where(
                (TableTennisLineEvent.starts_at > cursor_dt)
                | (
                    (TableTennisLineEvent.starts_at == cursor_dt)
                    & (TableTennisLineEvent.id > cursor_event_id)
                )
            )
        events = (await session.execute(stmt)).scalars().all()

    return _insert_events_to_ch(events, update_cursor=True)


async def sync_missing_finished_to_ch_once(limit: int = 5000, scan_limit: int = 50000) -> dict[str, int]:
    """Backfill finished events that are present in main DB but missing in CH."""
    ensure_schema()
    client = get_ch_client()
    scan_limit = max(limit * 5, scan_limit)

    async with async_session_maker() as session:
        stmt = (
            select(TableTennisLineEvent)
            .where(
                and_(
                    TableTennisLineEvent.status == LINE_EVENT_STATUS_FINISHED,
                    TableTennisLineEvent.live_sets_score.is_not(None),
                )
            )
            .order_by(TableTennisLineEvent.starts_at.desc(), TableTennisLineEvent.id.desc())
            .limit(scan_limit)
        )
        candidates = (await session.execute(stmt)).scalars().all()

    if not candidates:
        return {"synced": 0, "missing_candidates": 0}

    ids = [str(e.id) for e in candidates]
    exists = _fetch_existing_match_ids(ids, chunk_size=1500)
    missing = [e for e in candidates if str(e.id) not in exists][:limit]
    if not missing:
        return {"synced": 0, "missing_candidates": 0}
    res = _insert_events_to_ch(missing, update_cursor=False)
    res["missing_candidates"] = len(missing)
    return res


async def sync_missing_finished_to_ch_full_scan_once(limit: int = 10000) -> dict[str, int]:
    """Full scan fallback: finds any missing finished main events across full history."""
    ensure_schema()
    client = get_ch_client()
    ch_rows = client.query("SELECT match_id FROM ml.matches").result_rows
    ch_ids = {str(r[0]) for r in ch_rows}

    async with async_session_maker() as session:
        id_rows = (
            await session.execute(
                select(TableTennisLineEvent.id)
                .where(
                    and_(
                        TableTennisLineEvent.status == LINE_EVENT_STATUS_FINISHED,
                        TableTennisLineEvent.live_sets_score.is_not(None),
                    )
                )
                .order_by(TableTennisLineEvent.starts_at.asc(), TableTennisLineEvent.id.asc())
            )
        ).all()
        missing_ids = [str(r[0]) for r in id_rows if str(r[0]) not in ch_ids][: max(1, int(limit))]
        if not missing_ids:
            return {"synced": 0, "missing_total": 0}
        events = (
            await session.execute(
                select(TableTennisLineEvent)
                .where(TableTennisLineEvent.id.in_(missing_ids))
                .order_by(TableTennisLineEvent.starts_at.asc(), TableTennisLineEvent.id.asc())
            )
        ).scalars().all()
    res = _insert_events_to_ch(events, update_cursor=False)
    res["missing_total"] = len(missing_ids)
    return res

