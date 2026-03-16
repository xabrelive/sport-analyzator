"""Data pipeline: синхронизация finished матчей из основной БД в ML-базу."""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import async_session_maker
from app.models.table_tennis_line_event import LINE_EVENT_STATUS_FINISHED, TableTennisLineEvent
from app.ml.db import get_ml_session

logger = logging.getLogger(__name__)

DEFAULT_ELO = 1500.0
K_FACTOR_BASE = 40
ELO_DECAY_DAYS = 180
ELO_DECAY_WEIGHT = 0.1


def _parse_sets_score(value: str | None) -> tuple[int | None, int | None]:
    if not value or "-" not in value:
        return None, None
    left, right = value.split("-", 1)
    try:
        return int(left), int(right)
    except (TypeError, ValueError):
        return None, None


def _parse_live_score(live_score: dict | None) -> list[tuple[int, int]]:
    """Извлекает счёт по сетам: [(p1, p2), ...]."""
    if not isinstance(live_score, dict):
        return []
    out = []
    for key in sorted(live_score.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
        s = live_score.get(key)
        if not isinstance(s, dict):
            continue
        h = s.get("home")
        a = s.get("away")
        try:
            ph = int(h) if h is not None and str(h).strip() else 0
            pa = int(a) if a is not None and str(a).strip() else 0
            out.append((ph, pa))
        except (TypeError, ValueError):
            continue
    return out


def _upsert_player(ml_session, external_id: str, name: str) -> tuple[int, bool]:
    """Создаёт или обновляет игрока в ML-БД. Возвращает (id, created)."""
    row = ml_session.execute(
        text("SELECT id FROM players WHERE external_id = :eid"),
        {"eid": external_id},
    ).fetchone()
    if row:
        return row[0], False
    ml_session.execute(
        text(
            "INSERT INTO players (external_id, name) VALUES (:eid, :name) "
            "ON CONFLICT (external_id) DO UPDATE SET name = EXCLUDED.name, updated_at = NOW()"
        ),
        {"eid": external_id, "name": name or "Unknown"},
    )
    r = ml_session.execute(text("SELECT id FROM players WHERE external_id = :eid"), {"eid": external_id}).fetchone()
    pid = r[0] if r else 0
    if pid:
        ml_session.execute(
            text(
                "INSERT INTO player_ratings (player_id, rating, matches_played) "
                "VALUES (:pid, :rating, 0) ON CONFLICT (player_id) DO NOTHING"
            ),
            {"pid": pid, "rating": DEFAULT_ELO},
        )
    return pid, True


def _get_or_create_player(ml_session, external_id: str, name: str) -> int:
    pid, _ = _upsert_player(ml_session, external_id, name)
    return pid


def _get_or_create_rating(ml_session, player_id: int) -> tuple[float, int]:
    """Возвращает (rating, matches_played)."""
    row = ml_session.execute(
        text("SELECT rating, matches_played FROM player_ratings WHERE player_id = :pid"),
        {"pid": player_id},
    ).fetchone()
    if row:
        return float(row[0]), int(row[1] or 0)
    ml_session.execute(
        text(
            "INSERT INTO player_ratings (player_id, rating, matches_played) "
            "VALUES (:pid, :rating, 0) ON CONFLICT (player_id) DO NOTHING"
        ),
        {"pid": player_id, "rating": DEFAULT_ELO},
    )
    return DEFAULT_ELO, 0


def _dynamic_k(matches_played: int) -> float:
    """Dynamic K для TT: <50 → 40, <200 → 24, else 16."""
    if matches_played < 50:
        return 40.0
    if matches_played < 200:
        return 24.0
    return 16.0


def _league_multiplier(league_id: str) -> float:
    """League strength: pro=1.2, mid=1.0, weak=0.8."""
    if not league_id:
        return 1.0
    lid = str(league_id).lower()
    if any(x in lid for x in ("pro", "wtt", "ittf", "world", "championship")):
        return 1.2
    if any(x in lid for x in ("cup", "challenge", "open")):
        return 1.0
    return 0.8


def _update_elo(ml_session, player_id: int, new_rating: float, matches_played: int, last_match_at: datetime) -> None:
    ml_session.execute(
        text(
            "INSERT INTO player_ratings (player_id, rating, matches_played, last_match_at, updated_at) "
            "VALUES (:pid, :rating, :mp, :lma, NOW()) "
            "ON CONFLICT (player_id) DO UPDATE SET "
            "rating = EXCLUDED.rating, matches_played = EXCLUDED.matches_played, "
            "last_match_at = EXCLUDED.last_match_at, updated_at = NOW()"
        ),
        {"pid": player_id, "rating": new_rating, "mp": matches_played, "lma": last_match_at},
    )


def _sync_one_match(ml_session, event: TableTennisLineEvent) -> bool:
    external_id = str(event.id)
    existing = ml_session.execute(
        text("SELECT id FROM matches WHERE external_id = :eid"),
        {"eid": external_id},
    ).fetchone()
    if existing:
        return False

    p1_id = _get_or_create_player(ml_session, event.home_id, event.home_name)
    p2_id = _get_or_create_player(ml_session, event.away_id, event.away_name)
    if not p1_id or not p2_id:
        return False

    hs, as_ = _parse_sets_score(event.live_sets_score)
    if hs is None or as_ is None:
        return False

    duration_min = None
    if getattr(event, "finished_at", None) and event.starts_at:
        delta = event.finished_at - event.starts_at
        duration_min = max(0, int(delta.total_seconds() / 60))
    result = ml_session.execute(
        text(
            "INSERT INTO matches (external_id, league_id, league_name, player1_id, player2_id, "
            "start_time, status, score_sets_p1, score_sets_p2, duration_minutes) "
            "VALUES (:eid, :lid, :lname, :p1, :p2, :st, 'finished', :s1, :s2, :dur) "
            "ON CONFLICT (external_id) DO NOTHING RETURNING id"
        ),
        {
            "eid": external_id,
            "lid": event.league_id or "",
            "lname": event.league_name or "",
            "p1": p1_id,
            "p2": p2_id,
            "st": event.starts_at,
            "s1": hs,
            "s2": as_,
            "dur": duration_min,
        },
    )
    match_row = result.fetchone()
    if not match_row:
        return False  # ON CONFLICT DO NOTHING — матч уже есть
    match_id = match_row[0]

    sets_data = _parse_live_score(event.live_score)
    if not sets_data and hs + as_ > 0:
        sets_data = [(hs, as_)]
    for i, (sp1, sp2) in enumerate(sets_data, start=1):
        ml_session.execute(
            text(
                "INSERT INTO match_sets (match_id, set_number, score_p1, score_p2) "
                "VALUES (:mid, :sn, :s1, :s2) ON CONFLICT (match_id, set_number) DO NOTHING"
            ),
            {"mid": match_id, "sn": i, "s1": sp1, "s2": sp2},
        )

    odds_1 = float(event.odds_1 or 0)
    odds_2 = float(event.odds_2 or 0)
    if odds_1 > 0 and odds_2 > 0:
        ml_session.execute(
            text(
                "INSERT INTO odds (match_id, odds_p1, odds_p2, snapshot_type) VALUES (:mid, :o1, :o2, 'opening')"
            ),
            {"mid": match_id, "o1": odds_1, "o2": odds_2},
        )

    r1, mp1 = _get_or_create_rating(ml_session, p1_id)
    r2, mp2 = _get_or_create_rating(ml_session, p2_id)
    n1, n2 = mp1 + 1, mp2 + 1

    expected = 1.0 / (1.0 + 10.0 ** ((r2 - r1) / 400.0))
    actual = 1.0 if hs > as_ else 0.0

    # Margin Elo: sets_diff важнее point_diff. margin = sets_diff*10 + point_diff
    total_p1 = sum(s[0] for s in sets_data) if sets_data else hs * 11
    total_p2 = sum(s[1] for s in sets_data) if sets_data else as_ * 11
    sets_diff = abs(hs - as_)
    point_diff = abs(total_p1 - total_p2)
    margin = sets_diff * 10 + point_diff
    margin_mult = math.log(margin + 1) * 0.6
    margin_mult = max(0.5, min(2.0, margin_mult))

    # Dynamic K: <50 → 40, <200 → 24, else 16. min(K1,K2) — новичок не меняет рейтинг ветерана
    k1 = _dynamic_k(mp1)
    k2 = _dynamic_k(mp2)
    k = min(k1, k2)

    # Loss streak factor: если проиграл подряд — рейтинг падает быстрее
    def _loss_streak(pid: int) -> int:
        rows = ml_session.execute(
            text("""
                SELECT m.score_sets_p1, m.score_sets_p2, m.player1_id
                FROM matches m
                WHERE m.status = 'finished' AND m.start_time < :cutoff
                  AND (m.player1_id = :pid OR m.player2_id = :pid)
                ORDER BY m.start_time DESC
                LIMIT 15
            """),
            {"pid": pid, "cutoff": event.starts_at},
        ).fetchall()
        streak = 0
        for r in rows:
            is_p1 = r[2] == pid
            won = (r[0] > r[1]) if is_p1 else (r[1] > r[0])
            if won:
                break
            streak += 1
        return streak

    ls1, ls2 = _loss_streak(p1_id), _loss_streak(p2_id)
    loss_factor_p1 = 1.0 + (ls1 * 0.05) if actual == 0 else 1.0
    loss_factor_p2 = 1.0 + (ls2 * 0.05) if actual == 1 else 1.0
    loss_factor = (loss_factor_p1 + loss_factor_p2) / 2.0

    # Recency: матч сегодня — weight 1
    now_utc = datetime.now(timezone.utc)
    days_ago = (now_utc - event.starts_at).days if event.starts_at else 0
    recency = math.exp(-days_ago / 30.0) if days_ago > 0 else 1.0

    # League adjustment
    league_mult = _league_multiplier(event.league_id or "")

    delta = k * margin_mult * loss_factor * recency * league_mult * (actual - expected)
    new_r1 = r1 + delta
    new_r2 = r2 - delta
    _update_elo(ml_session, p1_id, new_r1, n1, event.starts_at)
    _update_elo(ml_session, p2_id, new_r2, n2, event.starts_at)

    # player_elo_history для elo_recent и elo_volatility
    try:
        ml_session.execute(
            text("""
                INSERT INTO player_elo_history (player_id, match_id, elo_before, elo_after, match_date)
                VALUES (:p1, :mid, :r1, :nr1, :dt), (:p2, :mid, :r2, :nr2, :dt)
            """),
            {
                "p1": p1_id, "p2": p2_id, "mid": match_id,
                "r1": r1, "nr1": new_r1, "r2": r2, "nr2": new_r2,
                "dt": event.starts_at,
            },
        )
    except Exception:
        pass

    return True


async def sync_leagues_to_ml() -> dict[str, int]:
    """Синхронизирует лиги из main DB (line_events + table_tennis_leagues) в ML-БД.
    Возвращает {added, total}."""
    async with async_session_maker() as session:
        try:
            result = await session.execute(
                text("""
                    SELECT league_id, league_name FROM table_tennis_line_events
                    WHERE league_id IS NOT NULL AND TRIM(league_id) != ''
                    UNION
                    SELECT id, name FROM table_tennis_leagues
                    WHERE id IS NOT NULL AND TRIM(id) != ''
                """)
            )
        except Exception:
            result = await session.execute(
                text("""
                    SELECT DISTINCT league_id, league_name FROM table_tennis_line_events
                    WHERE league_id IS NOT NULL AND TRIM(league_id) != ''
                """)
            )
        rows = result.fetchall()

    seen: set[str] = set()
    leagues: list[tuple[str, str]] = []
    for r in rows:
        lid = str(r[0] or "").strip()
        name = str(r[1] or "Unknown").strip() or "Unknown"
        if lid and lid not in seen:
            seen.add(lid)
            leagues.append((lid, name))

    ml_session = get_ml_session()
    added = 0
    try:
        ml_session.execute(
            text("""
                CREATE TABLE IF NOT EXISTS leagues (
                    id VARCHAR(64) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
        )
        for lid, name in leagues:
            existing = ml_session.execute(
                text("SELECT id FROM leagues WHERE id = :lid"),
                {"lid": lid},
            ).fetchone()
            if not existing:
                ml_session.execute(
                    text(
                        "INSERT INTO leagues (id, name) VALUES (:lid, :name) "
                        "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, updated_at = NOW()"
                    ),
                    {"lid": lid, "name": name},
                )
                added += 1
        ml_session.commit()
    except Exception:
        ml_session.rollback()
        raise
    finally:
        ml_session.close()

    if added > 0:
        logger.info("ML leagues sync: added=%s, total=%s", added, len(leagues))
    return {"added": added, "total": len(leagues)}


async def sync_players_to_ml() -> dict[str, int]:
    """Синхронизирует всех игроков из main DB (линия, лайв, архив) в ML-БД.
    Новые игроки создаются с дефолтным Elo. Возвращает {added, total}."""
    async with async_session_maker() as session:
        result = await session.execute(
            text("""
                SELECT home_id, home_name FROM table_tennis_line_events
                WHERE home_id IS NOT NULL AND TRIM(home_id) != ''
                UNION
                SELECT away_id, away_name FROM table_tennis_line_events
                WHERE away_id IS NOT NULL AND TRIM(away_id) != ''
            """)
        )
        rows = result.fetchall()

    seen: set[str] = set()
    players: list[tuple[str, str]] = []
    for r in rows:
        eid = str(r[0] or "").strip()
        name = str(r[1] or "Unknown").strip() or "Unknown"
        if eid and eid not in seen:
            seen.add(eid)
            players.append((eid, name))

    ml_session = get_ml_session()
    added = 0
    try:
        for eid, name in players:
            _, created = _upsert_player(ml_session, eid, name)
            if created:
                added += 1
        ml_session.commit()
    except Exception:
        ml_session.rollback()
        raise
    finally:
        ml_session.close()

    logger.info("ML players sync: added=%s, total=%s", added, len(players))
    return {"added": added, "total": len(players)}


async def sync_finished_to_ml_once(
    limit: int = 500,
    days_back: int | None = 365,
    since: datetime | None = None,
    offset: int = 0,
    after_starts_at: datetime | None = None,
    after_event_id: int = 0,
) -> dict[str, int]:
    """Синхронизирует завершённые матчи из основной БД в ML-базу.
    days_back=0 или None — весь архив без ограничения по дате."""
    filters = [
        TableTennisLineEvent.status == LINE_EVENT_STATUS_FINISHED,
        TableTennisLineEvent.live_sets_score.is_not(None),
    ]
    if days_back is not None and days_back > 0:
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(days=days_back)
        filters.append(TableTennisLineEvent.starts_at >= since)
    if after_starts_at is not None:
        filters.append(TableTennisLineEvent.starts_at > after_starts_at)
    async with async_session_maker() as session:
        stmt = (
            select(TableTennisLineEvent)
            .where(*filters)
            .order_by(TableTennisLineEvent.starts_at.asc(), TableTennisLineEvent.id.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(stmt)
        events = list(result.scalars().all())

    if not events:
        return {
            "synced": 0,
            "skipped": 0,
            "fetched": 0,
            "last_event_id": after_event_id or 0,
            "last_starts_at_ts": (
                int(after_starts_at.timestamp()) if after_starts_at else 0
            ),
        }

    ml_session = get_ml_session()
    synced = 0
    commit_batch_size = 500  # коммит каждые N матчей — ускорение
    try:
        for i, event in enumerate(events):
            try:
                if _sync_one_match(ml_session, event):
                    synced += 1
                if (i + 1) % commit_batch_size == 0:
                    ml_session.commit()
            except IntegrityError as e:
                ml_session.rollback()
                logger.debug("Sync skip duplicate match %s: %s", getattr(event, "id", "?"), e)
        ml_session.commit()
    except Exception:
        ml_session.rollback()
        raise
    finally:
        ml_session.close()

    last_event = events[-1]
    return {
        "synced": synced,
        "skipped": len(events) - synced,
        "fetched": len(events),
        "last_event_id": int(last_event.id),
        "last_starts_at_ts": int(last_event.starts_at.timestamp()) if last_event.starts_at else 0,
    }


async def sync_full_main_to_ml(
    batch_size: int = 2000,
    days_back: int | None = 3650,
    progress_callback: Any = None,
) -> dict[str, int]:
    """Полная синхронизация основной БД в ML. Батчами до исчерпания.
    days_back=0 — весь архив без ограничения по дате."""
    total_synced = 0
    total_skipped = 0
    offset = 0
    last_event_id = 0
    last_starts_at_ts = 0
    while True:
        res = await sync_finished_to_ml_once(
            limit=batch_size,
            days_back=days_back,
            offset=offset,
        )
        synced = res.get("synced", 0)
        skipped = res.get("skipped", 0)
        batch_len = synced + skipped
        total_synced += synced
        total_skipped += skipped
        last_event_id = int(res.get("last_event_id", last_event_id) or last_event_id)
        last_starts_at_ts = int(res.get("last_starts_at_ts", last_starts_at_ts) or last_starts_at_ts)
        if progress_callback:
            progress_callback(current=total_synced + total_skipped, total=0, message=f"Синхронизировано: {total_synced}, пропущено: {total_skipped}")
        if batch_len == 0:
            break
        offset += batch_len
        if synced > 0:
            logger.info("Full sync batch: synced=%s, total=%s", synced, total_synced)
    return {
        "synced": total_synced,
        "skipped": total_skipped,
        "last_event_id": last_event_id,
        "last_starts_at_ts": last_starts_at_ts,
    }


async def sync_missing_finished_to_ml_once(limit: int = 10_000) -> dict[str, int]:
    """Догружает в ML матчи, которые есть в main (finished + счёт), но отсутствуют в ML.
    Решает рассинхрон (например, после догрузки результатов в main). Вызывать каждый цикл sync."""
    async with async_session_maker() as session:
        result = await session.execute(
            text("""
                SELECT id FROM table_tennis_line_events
                WHERE status = :status AND live_sets_score IS NOT NULL
            """),
            {"status": LINE_EVENT_STATUS_FINISHED},
        )
        main_ids = {str(r[0]) for r in result.fetchall()}
    if not main_ids:
        return {"synced": 0, "missing": 0}

    ml_session = get_ml_session()
    try:
        # По батчам main_ids спрашиваем ML: какие из них уже есть
        ml_ids: set[str] = set()
        main_list = list(main_ids)
        for i in range(0, len(main_list), 50_000):
            batch = main_list[i : i + 50_000]
            rows = ml_session.execute(
                text("SELECT external_id FROM matches WHERE external_id = ANY(:eids)"),
                {"eids": batch},
            ).fetchall()
            ml_ids.update(str(r[0]) for r in rows)
    finally:
        ml_session.close()

    missing_ids = main_ids - ml_ids
    if not missing_ids:
        return {"synced": 0, "missing": 0}
    to_fetch = list(missing_ids)[:limit]

    async with async_session_maker() as session:
        result = await session.execute(
            select(TableTennisLineEvent).where(
                TableTennisLineEvent.id.in_(to_fetch),
                TableTennisLineEvent.status == LINE_EVENT_STATUS_FINISHED,
                TableTennisLineEvent.live_sets_score.is_not(None),
            )
        )
        events = list(result.scalars().all())

    if not events:
        return {"synced": 0, "missing": len(missing_ids)}

    ml_session = get_ml_session()
    synced = 0
    try:
        for event in events:
            try:
                if _sync_one_match(ml_session, event):
                    synced += 1
            except IntegrityError:
                ml_session.rollback()
        ml_session.commit()
    except Exception:
        ml_session.rollback()
        raise
    finally:
        ml_session.close()

    if synced > 0:
        logger.info("ML sync missing: synced=%s (main has %s not in ML)", synced, len(missing_ids))
    return {"synced": synced, "missing": len(missing_ids)}


def backfill_odds_from_main_once(limit: int = 50000) -> int:
    """Дозаполняет ML odds из основной БД (table_tennis_line_events.odds_1/odds_2).
    Для матчей в ML без коэффициентов берёт их из main.
    Использует sync-движок, чтобы избежать конфликта event loop при вызове из worker_cli (asyncio.run)."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    main_engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        poolclass=NullPool,
    )
    with main_engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT id, odds_1, odds_2
                FROM table_tennis_line_events
                WHERE status = 'finished'
                  AND odds_1 IS NOT NULL AND odds_1 > 0
                  AND odds_2 IS NOT NULL AND odds_2 > 0
                ORDER BY starts_at DESC
                LIMIT :lim
            """),
            {"lim": limit},
        )
        main_rows = result.fetchall()

    if not main_rows:
        return 0

    ml_session = get_ml_session()
    try:
        count = 0
        for i in range(0, len(main_rows), 5000):
            batch = main_rows[i : i + 5000]
            external_ids = [str(r[0]) for r in batch]
            odds_by_eid = {str(r[0]): (float(r[1]), float(r[2])) for r in batch}

            ml_matches = ml_session.execute(
                text("SELECT id, external_id FROM matches WHERE external_id = ANY(:eids)"),
                {"eids": external_ids},
            ).fetchall()

            existing = ml_session.execute(
                text("""
                    SELECT match_id FROM odds o
                    JOIN matches m ON m.id = o.match_id
                    WHERE m.external_id = ANY(:eids)
                """),
                {"eids": external_ids},
            ).fetchall()
            has_odds = {r[0] for r in existing}

            for ml_id, eid in ml_matches:
                if ml_id in has_odds:
                    continue
                o1, o2 = odds_by_eid.get(eid, (None, None))
                if o1 is None or o2 is None or o1 <= 0 or o2 <= 0:
                    continue
                ml_session.execute(
                    text(
                        "INSERT INTO odds (match_id, odds_p1, odds_p2, snapshot_type) "
                        "VALUES (:mid, :o1, :o2, 'opening')"
                    ),
                    {"mid": ml_id, "o1": o1, "o2": o2},
                )
                count += 1
                has_odds.add(ml_id)
        ml_session.commit()
        if count > 0:
            logger.info("ML odds backfill from main: %s rows", count)
        return count
    except Exception:
        ml_session.rollback()
        raise
    finally:
        ml_session.close()
        main_engine.dispose()


def backfill_odds_from_main_incremental_once(limit: int = 50000, after_match_id: int = 0) -> dict[str, int | bool]:
    """Инкрементальная догрузка odds с курсором по matches.id (только для матчей без odds)."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    def _load_missing(min_id: int) -> list[tuple[int, str]]:
        s = get_ml_session()
        try:
            return s.execute(
                text(
                    """
                    SELECT m.id, m.external_id
                    FROM matches m
                    WHERE m.status = 'finished'
                      AND m.id > :min_id
                      AND NOT EXISTS (SELECT 1 FROM odds o WHERE o.match_id = m.id)
                    ORDER BY m.id ASC
                    LIMIT :lim
                    """
                ),
                {"min_id": int(min_id or 0), "lim": limit},
            ).fetchall()
        finally:
            s.close()

    rows = _load_missing(after_match_id)
    wrapped = False
    if not rows and int(after_match_id or 0) > 0:
        rows = _load_missing(0)
        wrapped = True
    if not rows:
        return {"added": 0, "fetched": 0, "last_match_id": int(after_match_id or 0), "wrapped": wrapped}

    external_ids = [str(r[1]) for r in rows if r[1]]
    odds_by_external: dict[str, tuple[float, float]] = {}
    fetched_from_api = 0
    if external_ids:
        main_engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            poolclass=NullPool,
        )
        with main_engine.connect() as conn:
            main_rows = conn.execute(
                text(
                    """
                    SELECT CAST(id AS TEXT) AS eid, odds_1, odds_2
                    FROM table_tennis_line_events
                    WHERE CAST(id AS TEXT) = ANY(:ids)
                      AND odds_1 IS NOT NULL AND odds_1 > 0
                      AND odds_2 IS NOT NULL AND odds_2 > 0
                    """
                ),
                {"ids": external_ids},
            ).fetchall()
        for r in main_rows:
            odds_by_external[str(r[0])] = (float(r[1]), float(r[2]))

        # Fallback: для части матчей без odds в main пробуем добрать через BetsAPI /event/odds.
        missing_in_main = [eid for eid in external_ids if eid not in odds_by_external]
        if missing_in_main:
            max_api_fetch = min(200, len(missing_in_main))
            to_fetch = missing_in_main[:max_api_fetch]
            try:
                import asyncio
                import httpx
                from app.services.betsapi_table_tennis import _fetch_event_odds

                async def _fetch_many(event_ids: list[str]) -> dict[str, tuple[float, float]]:
                    out: dict[str, tuple[float, float]] = {}
                    sem = asyncio.Semaphore(10)
                    async with httpx.AsyncClient() as client:
                        async def _one(eid: str) -> None:
                            async with sem:
                                try:
                                    r = await _fetch_event_odds(client, eid)
                                except Exception:
                                    return
                                if r is not None and r[0] > 0 and r[1] > 0:
                                    out[eid] = (float(r[0]), float(r[1]))

                        await asyncio.gather(*(_one(eid) for eid in event_ids))
                    return out

                api_odds = asyncio.run(_fetch_many(to_fetch))
                if api_odds:
                    now_db = datetime.now(timezone.utc)
                    with main_engine.begin() as conn:
                        for eid, (o1, o2) in api_odds.items():
                            conn.execute(
                                text(
                                    "UPDATE table_tennis_line_events "
                                    "SET odds_1 = :o1, odds_2 = :o2, updated_at = :now "
                                    "WHERE CAST(id AS TEXT) = :eid "
                                    "AND (odds_1 IS NULL OR odds_1 <= 0 OR odds_2 IS NULL OR odds_2 <= 0)"
                                ),
                                {"eid": eid, "o1": float(o1), "o2": float(o2), "now": now_db},
                            )
                    odds_by_external.update(api_odds)
                    fetched_from_api = len(api_odds)
            except Exception:
                fetched_from_api = 0

    ml_session = get_ml_session()
    try:
        added = 0
        for mid, external_id in rows:
            e = str(external_id or "")
            if not e or e not in odds_by_external:
                continue
            o1, o2 = odds_by_external[e]
            ml_session.execute(
                text(
                    "INSERT INTO odds (match_id, odds_p1, odds_p2, snapshot_type) "
                    "VALUES (:mid, :o1, :o2, 'opening')"
                ),
                {"mid": int(mid), "o1": float(o1), "o2": float(o2)},
            )
            added += 1
        ml_session.commit()
        return {
            "added": int(added),
            "fetched": int(len(rows)),
            "last_match_id": int(rows[-1][0] or after_match_id or 0),
            "wrapped": wrapped,
            "fetched_from_api": int(fetched_from_api),
        }
    except Exception:
        ml_session.rollback()
        raise
    finally:
        ml_session.close()
        if external_ids:
            try:
                main_engine.dispose()
            except Exception:
                pass


async def backfill_duration_from_main_once(limit: int = 5000) -> int:
    """Обновляет duration_minutes в ML matches из main DB (finished_at - starts_at)."""
    from sqlalchemy import text

    async with async_session_maker() as main_session:
        result = await main_session.execute(
            text("""
                SELECT id, starts_at, finished_at
                FROM table_tennis_line_events
                WHERE status = 'finished' AND finished_at IS NOT NULL AND starts_at IS NOT NULL
                ORDER BY starts_at DESC
                LIMIT :lim
            """),
            {"lim": limit},
        )
        rows = result.fetchall()

    if not rows:
        return 0
    ml_session = get_ml_session()
    try:
        count = 0
        for r in rows:
            eid, starts_at, finished_at = str(r[0]), r[1], r[2]
            if not starts_at or not finished_at:
                continue
            delta = finished_at - starts_at
            dur = max(0, min(180, int(delta.total_seconds() / 60)))
            res = ml_session.execute(
                text("UPDATE matches SET duration_minutes = :dur WHERE external_id = :eid AND (duration_minutes IS NULL OR duration_minutes = 0)"),
                {"dur": dur, "eid": eid},
            )
            if getattr(res, "rowcount", 0) and res.rowcount > 0:
                count += 1
        ml_session.commit()
        return count
    except Exception:
        ml_session.rollback()
        raise
    finally:
        ml_session.close()


def _duration_load_missing_ml(limit: int, after_match_id: int) -> tuple[list, bool]:
    """Синхронно загружает из ML список матчей без duration. Для вызова из to_thread."""
    from sqlalchemy import text

    s = get_ml_session()
    try:
        rows = s.execute(
            text(
                """
                SELECT id, external_id
                FROM matches
                WHERE status = 'finished'
                  AND id > :min_id
                  AND (duration_minutes IS NULL OR duration_minutes = 0)
                ORDER BY id ASC
                LIMIT :lim
                """
            ),
            {"min_id": int(after_match_id or 0), "lim": limit},
        ).fetchall()
    finally:
        s.close()
    wrapped = False
    if not rows and int(after_match_id or 0) > 0:
        s2 = get_ml_session()
        try:
            rows = s2.execute(
                text(
                    """
                    SELECT id, external_id
                    FROM matches
                    WHERE status = 'finished'
                      AND (duration_minutes IS NULL OR duration_minutes = 0)
                    ORDER BY id ASC
                    LIMIT :lim
                    """
                ),
                {"lim": limit},
            ).fetchall()
            wrapped = True
        finally:
            s2.close()
    return (rows or [], wrapped)


def _duration_apply_ml_updates_sync(
    rows: list,
    main_by_external: dict[str, tuple[datetime, datetime]],
    after_match_id: int,
    wrapped: bool,
) -> dict[str, int | bool]:
    """Синхронно применяет duration в ML. Для вызова из to_thread."""
    from sqlalchemy import text

    ml_session = get_ml_session()
    try:
        updated = 0
        for mid, external_id in rows:
            e = str(external_id or "")
            if e not in main_by_external:
                continue
            starts_at, finished_at = main_by_external[e]
            if not starts_at or not finished_at:
                continue
            delta = finished_at - starts_at
            dur = max(0, min(180, int(delta.total_seconds() / 60)))
            res = ml_session.execute(
                text(
                    "UPDATE matches SET duration_minutes = :dur "
                    "WHERE id = :mid AND (duration_minutes IS NULL OR duration_minutes = 0)"
                ),
                {"dur": dur, "mid": int(mid)},
            )
            if getattr(res, "rowcount", 0) and res.rowcount > 0:
                updated += 1
        ml_session.commit()
        return {
            "updated": int(updated),
            "fetched": int(len(rows)),
            "last_match_id": int(rows[-1][0] or after_match_id or 0) if rows else int(after_match_id or 0),
            "wrapped": wrapped,
        }
    except Exception:
        ml_session.rollback()
        raise
    finally:
        ml_session.close()


async def backfill_duration_from_main_incremental_once(limit: int = 5000, after_match_id: int = 0) -> dict[str, int | bool]:
    """Инкрементальная догрузка duration_minutes с курсором по matches.id.
    Тяжёлые sync-операции с ML выполняются в пуле потоков, чтобы не блокировать прогнозы."""
    import asyncio
    from sqlalchemy import text

    rows, wrapped = await asyncio.to_thread(_duration_load_missing_ml, limit, after_match_id)
    if not rows:
        return {"updated": 0, "fetched": 0, "last_match_id": int(after_match_id or 0), "wrapped": wrapped}

    external_ids = [str(r[1]) for r in rows if r[1]]
    main_by_external: dict[str, tuple[datetime, datetime]] = {}
    if external_ids:
        async with async_session_maker() as main_session:
            result = await main_session.execute(
                text(
                    """
                    SELECT CAST(id AS TEXT) AS eid, starts_at, finished_at
                    FROM table_tennis_line_events
                    WHERE CAST(id AS TEXT) = ANY(:ids)
                      AND status = 'finished'
                      AND finished_at IS NOT NULL
                      AND starts_at IS NOT NULL
                    """
                ),
                {"ids": external_ids},
            )
            for r in result.fetchall():
                main_by_external[str(r[0])] = (r[1], r[2])

    return await asyncio.to_thread(
        _duration_apply_ml_updates_sync,
        rows,
        main_by_external,
        int(after_match_id or 0),
        wrapped,
    )


def _backfill_chunk(chunk: list[tuple]) -> int:
    """Обрабатывает чанк матчей в отдельном потоке. Возвращает количество добавленных фичей."""
    from app.ml.feature_engine import FeatureEngine

    engine = FeatureEngine()
    session = get_ml_session()
    count = 0
    try:
        for r in chunk:
            try:
                match_id, p1, p2, st, o1, o2, lid = r
                if not p1 or not p2:
                    continue
                f = engine.compute_for_match(match_id, p1, p2, st, o1, o2, lid or "")
                if f:
                    engine.upsert_match_features(match_id, f)
                    count += 1
            except Exception as e:
                session.rollback()
                logger.debug("Backfill match %s: %s", r[0] if r else "?", e)
        session.commit()
    finally:
        session.close()
    return count


def backfill_features_once(limit: int = 5000, progress_callback: Any = None, workers: int = 1) -> int:
    """Расчёт match_features для матчей без фичей. workers>1 — параллельная обработка."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from sqlalchemy import text

    session = get_ml_session()
    try:
        rows = session.execute(
            text("""
                SELECT m.id, m.player1_id, m.player2_id, m.start_time, m.league_id
                FROM matches m
                LEFT JOIN match_features mf ON mf.match_id = m.id
                WHERE m.status = 'finished' AND mf.match_id IS NULL
                ORDER BY m.start_time ASC
                LIMIT :lim
            """),
            {"lim": limit},
        ).fetchall()
    finally:
        session.close()

    total = len(rows)
    if total == 0:
        return 0

    match_ids = [r[0] for r in rows]
    odds_map: dict[int, tuple[float, float]] = {}
    if match_ids:
        session = get_ml_session()
        try:
            for i in range(0, len(match_ids), 5000):
                batch = match_ids[i : i + 5000]
                odds_rows = session.execute(
                    text("""
                        SELECT DISTINCT ON (match_id) match_id, odds_p1, odds_p2
                        FROM odds WHERE match_id = ANY(:ids)
                        ORDER BY match_id, created_at ASC
                    """),
                    {"ids": batch},
                ).fetchall()
                for o in odds_rows:
                    odds_map[o[0]] = (float(o[1] or 1.9), float(o[2] or 1.9))
        finally:
            session.close()

    tasks: list[tuple] = []
    for r in rows:
        match_id, p1, p2, st, lid = r[0], r[1], r[2], r[3], r[4]
        o1, o2 = odds_map.get(match_id, (1.9, 1.9))
        tasks.append((match_id, p1, p2, st, o1, o2, lid or ""))

    num_workers = max(1, min(workers, 16))
    chunk_size = max(50, (len(tasks) + num_workers - 1) // num_workers)
    chunks = [tasks[i:i + chunk_size] for i in range(0, len(tasks), chunk_size)]

    if num_workers <= 1 or len(chunks) <= 1:
        return _backfill_chunk(tasks)

    count = 0
    with ThreadPoolExecutor(max_workers=num_workers) as ex:
        futures = {ex.submit(_backfill_chunk, c): i for i, c in enumerate(chunks)}
        done = 0
        for fut in as_completed(futures):
            count += fut.result()
            done += 1
            if progress_callback and done % max(1, len(chunks) // 20) == 0:
                progress_callback(current=done * chunk_size, total=total, message=f"Backfill: {count} фичей")
    if progress_callback:
        progress_callback(current=total, total=total, message=f"Готово: {count} фичей")
    return count


def backfill_features_incremental_once(
    limit: int = 5000,
    after_match_id: int = 0,
    progress_callback: Any = None,
    workers: int = 1,
) -> dict[str, int | bool]:
    """Инкрементальный расчёт match_features с курсором по matches.id.

    Берёт матчи без фичей, у которых id > after_match_id. Если таких нет, делает один проход с начала
    (wrap), чтобы догрызть «дырки» в старых данных.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from sqlalchemy import text

    def _load_rows(min_id: int) -> list[tuple]:
        s = get_ml_session()
        try:
            return s.execute(
                text(
                    """
                    SELECT m.id, m.player1_id, m.player2_id, m.start_time, m.league_id
                    FROM matches m
                    LEFT JOIN match_features mf ON mf.match_id = m.id
                    WHERE m.status = 'finished' AND mf.match_id IS NULL
                      AND m.id > :min_id
                    ORDER BY m.id ASC
                    LIMIT :lim
                    """
                ),
                {"min_id": int(min_id or 0), "lim": limit},
            ).fetchall()
        finally:
            s.close()

    rows = _load_rows(after_match_id)
    wrapped = False
    if not rows and int(after_match_id or 0) > 0:
        rows = _load_rows(0)
        wrapped = True

    total = len(rows)
    if total == 0:
        return {
            "features_added": 0,
            "fetched": 0,
            "last_match_id": int(after_match_id or 0),
            "wrapped": wrapped,
        }

    match_ids = [r[0] for r in rows]
    odds_map: dict[int, tuple[float, float]] = {}
    if match_ids:
        session = get_ml_session()
        try:
            for i in range(0, len(match_ids), 5000):
                batch = match_ids[i : i + 5000]
                odds_rows = session.execute(
                    text("""
                        SELECT DISTINCT ON (match_id) match_id, odds_p1, odds_p2
                        FROM odds WHERE match_id = ANY(:ids)
                        ORDER BY match_id, created_at ASC
                    """),
                    {"ids": batch},
                ).fetchall()
                for o in odds_rows:
                    odds_map[o[0]] = (float(o[1] or 1.9), float(o[2] or 1.9))
        finally:
            session.close()

    tasks: list[tuple] = []
    for r in rows:
        match_id, p1, p2, st, lid = r[0], r[1], r[2], r[3], r[4]
        o1, o2 = odds_map.get(match_id, (1.9, 1.9))
        tasks.append((match_id, p1, p2, st, o1, o2, lid or ""))

    num_workers = max(1, min(workers, 16))
    chunk_size = max(50, (len(tasks) + num_workers - 1) // num_workers)
    chunks = [tasks[i:i + chunk_size] for i in range(0, len(tasks), chunk_size)]

    if num_workers <= 1 or len(chunks) <= 1:
        count = _backfill_chunk(tasks)
        return {
            "features_added": int(count),
            "fetched": total,
            "last_match_id": int(rows[-1][0] or after_match_id or 0),
            "wrapped": wrapped,
        }

    count = 0
    with ThreadPoolExecutor(max_workers=num_workers) as ex:
        futures = {ex.submit(_backfill_chunk, c): i for i, c in enumerate(chunks)}
        done = 0
        for fut in as_completed(futures):
            count += int(fut.result() or 0)
            done += 1
            if progress_callback and done % max(1, len(chunks) // 20) == 0:
                progress_callback(current=done * chunk_size, total=total, message=f"Backfill: {count} фичей")
    if progress_callback:
        progress_callback(current=total, total=total, message=f"Готово: {count} фичей")
    return {
        "features_added": int(count),
        "fetched": total,
        "last_match_id": int(rows[-1][0] or after_match_id or 0),
        "wrapped": wrapped,
    }


def check_suspicious_matches_once(limit: int = 2000) -> int:
    """Проверка договорных матчей. Isolation Forest при наличии, иначе heuristic."""
    from app.ml.anomaly import (
        compute_suspicion_score,
        compute_suspicion_score_isolation_forest,
        anomaly_features,
        load_anomaly_model,
        save_suspicious,
        SUSPICIOUS_THRESHOLD,
    )
    from app.ml.feature_engine import FeatureEngine
    from app.ml.model_trainer import load_models, predict_proba, FEATURE_COLS
    from app.ml.inference import _feat_dict

    session = get_ml_session()
    try:
        rows = session.execute(
            text("""
                SELECT m.id, m.score_sets_p1, m.score_sets_p2, mf.elo_diff, mf.form_diff,
                       mf.fatigue_diff, mf.h2h_diff, mf.winrate_10_diff, mf.odds_diff, mf.h2h_count,
                       mf.avg_sets_per_match_diff, mf.sets_over35_rate_diff, mf.streak_score,
                       mf.minutes_since_last_match_diff, mf.dominance_diff,
                       mf.std_points_diff_last10_p1, mf.std_points_diff_last10_p2,
                       mf.log_odds_ratio, mf.implied_prob_p1, mf.market_margin,
                       mf.momentum_today_diff, mf.set1_strength_diff, mf.comeback_rate_diff
                FROM matches m
                JOIN match_features mf ON mf.match_id = m.id
                WHERE m.status = 'finished' AND m.score_sets_p1 IS NOT NULL AND m.score_sets_p2 IS NOT NULL
                ORDER BY m.start_time DESC
                LIMIT :lim
            """),
            {"lim": limit},
        ).fetchall()
        odds = session.execute(text("SELECT match_id, odds_p1, odds_p2 FROM odds")).fetchall()
        odds_map = {}
        for o in odds:
            if o[0] not in odds_map:
                odds_map[o[0]] = (o[1], o[2])

        try:
            _, model_set1, _, _ = load_models()
        except Exception:
            return 0
        anomaly_model = load_anomaly_model()

        col_order = [
            "elo_diff", "form_diff", "fatigue_diff", "h2h_diff", "winrate_10_diff", "odds_diff", "h2h_count",
            "avg_sets_per_match_diff", "sets_over35_rate_diff", "streak_score",
            "minutes_since_last_match_diff", "dominance_diff",
            "std_points_diff_last10_p1", "std_points_diff_last10_p2",
            "log_odds_ratio", "implied_prob_p1", "market_margin",
            "momentum_today_diff", "set1_strength_diff", "comeback_rate_diff",
        ]
        count = 0
        for r in rows:
            match_id = r[0]
            p1_won = r[1] > r[2]
            o1, o2 = odds_map.get(match_id, (1.9, 1.9))
            odds_open_p1 = float(o1 or 1.9)
            odds_close_p1 = float(o1 or 1.9)

            set_rows = session.execute(
                text("SELECT score_p1, score_p2 FROM match_sets WHERE match_id = :mid ORDER BY set_number"),
                {"mid": match_id},
            ).fetchall()
            sets = [(sr[0] or 0, sr[1] or 0) for sr in set_rows]

            feat_dict = {c: float(r[3 + i]) if 3 + i < len(r) and r[3 + i] is not None else 0.0 for i, c in enumerate(col_order)}
            for c in FEATURE_COLS:
                if c not in feat_dict:
                    feat_dict[c] = 0.0
            try:
                p_model = predict_proba(model_set1, feat_dict)
            except Exception:
                p_model = 0.5

            if anomaly_model is not None:
                feat_vec = anomaly_features(odds_open_p1, odds_close_p1, sets, p_model, p1_won)
                score, reason = compute_suspicion_score_isolation_forest(feat_vec, anomaly_model)
                odds_shift = abs(odds_close_p1 - odds_open_p1)
                comeback = False
                model_err = 0.0
            else:
                score, reason, odds_shift, comeback, model_err = compute_suspicion_score(
                    odds_open_p1, odds_close_p1, sets, p_model, p1_won
                )
            if score >= SUSPICIOUS_THRESHOLD:
                save_suspicious(match_id, score, reason, odds_shift, comeback, model_err)
                count += 1
        return count
    finally:
        session.close()
