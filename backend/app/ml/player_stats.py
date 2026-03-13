"""player_daily_stats, player_style, player_elo_history: backfill и использование в фичах."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

from app.ml.db import get_ml_session

DEFAULT_ELO = 1500.0


def backfill_player_daily_stats_once(limit: int = 50_000) -> int:
    """Заполняет player_daily_stats из finished matches. Возвращает число обновлённых строк."""
    session = get_ml_session()
    try:
        rows = session.execute(
            text("""
                SELECT m.id, m.player1_id, m.player2_id, m.start_time,
                       m.score_sets_p1, m.score_sets_p2
                FROM matches m
                WHERE m.status = 'finished' AND m.score_sets_p1 IS NOT NULL
                ORDER BY m.start_time ASC
                LIMIT :lim
            """),
            {"lim": limit},
        ).fetchall()

        dur_rows = session.execute(
            text("SELECT id, duration_minutes FROM matches WHERE duration_minutes IS NOT NULL")
        ).fetchall()
        dur_by_match = {r[0]: r[1] for r in dur_rows}
        set_rows = session.execute(
            text("SELECT match_id, score_p1, score_p2 FROM match_sets")
        ).fetchall()
        set_by_match: dict[int, list[tuple[int, int]]] = {}
        for sr in set_rows:
            mid = sr[0]
            set_by_match.setdefault(mid, []).append((sr[1] or 0, sr[2] or 0))

        by_player_date: dict[tuple[int, date], dict] = {}
        for r in rows:
            mid, p1, p2, st = r[0], r[1], r[2], r[3]
            s1, s2 = r[4] or 0, r[5] or 0
            if not p1 or not p2:
                continue
            d = st.date() if hasattr(st, "date") else date(st.year, st.month, st.day)
            mins = dur_by_match.get(mid) or 0

            for pid, is_p1 in [(p1, True), (p2, False)]:
                key = (pid, d)
                if key not in by_player_date:
                    by_player_date[key] = {
                        "matches": 0, "wins": 0, "losses": 0,
                        "sets_won": 0, "sets_lost": 0, "points_won": 0, "points_lost": 0,
                        "minutes": 0,
                    }
                rec = by_player_date[key]
                rec["matches"] += 1
                rec["minutes"] += mins
                won = (s1 > s2) if is_p1 else (s2 > s1)
                if won:
                    rec["wins"] += 1
                    rec["sets_won"] += s1 if is_p1 else s2
                    rec["sets_lost"] += s2 if is_p1 else s1
                else:
                    rec["losses"] += 1
                    rec["sets_won"] += s2 if is_p1 else s1
                    rec["sets_lost"] += s1 if is_p1 else s2

        for r in rows:
            mid, p1, p2 = r[0], r[1], r[2]
            s1, s2 = r[4] or 0, r[5] or 0
            st = r[3]
            d = st.date() if hasattr(st, "date") else date(st.year, st.month, st.day)
            sets_data = set_by_match.get(mid, [])
            for sp1, sp2 in sets_data:
                for pid, is_p1 in [(p1, True), (p2, False)]:
                    key = (pid, d)
                    if key in by_player_date:
                        if is_p1:
                            by_player_date[key]["points_won"] += sp1
                            by_player_date[key]["points_lost"] += sp2
                        else:
                            by_player_date[key]["points_won"] += sp2
                            by_player_date[key]["points_lost"] += sp1
            if not sets_data:
                for pid, is_p1 in [(p1, True), (p2, False)]:
                    key = (pid, d)
                    if key in by_player_date:
                        pts = (s1 + s2) * 20
                        by_player_date[key]["points_won"] += int(pts / 2)
                        by_player_date[key]["points_lost"] += int(pts / 2)
            if not dur_by_match.get(mid) and sets_data:
                total_pts = sum(sp1 + sp2 for sp1, sp2 in sets_data)
                est_mins = max(5, min(90, int(total_pts * 0.5)))
                for pid in (p1, p2):
                    key = (pid, d)
                    if key in by_player_date:
                        by_player_date[key]["minutes"] += est_mins

        count = 0
        for (pid, d), rec in by_player_date.items():
            momentum = rec["wins"] - rec["losses"]
            fatigue = min(30.0, rec["matches"] * 3.0)
            mins = rec.get("minutes", 0)
            if mins == 0 and (rec["points_won"] + rec["points_lost"]) > 0:
                mins = max(5, min(90, int((rec["points_won"] + rec["points_lost"]) * 0.5)))
            session.execute(
                text("""
                    INSERT INTO player_daily_stats (
                        player_id, date, matches_played, wins, losses,
                        sets_won, sets_lost, points_won, points_lost,
                        minutes_played, fatigue_index, momentum, updated_at
                    ) VALUES (
                        :pid, :d, :matches, :wins, :losses,
                        :sets_won, :sets_lost, :pts_won, :pts_lost,
                        :mins, :fatigue, :momentum, NOW()
                    )
                    ON CONFLICT (player_id, date) DO UPDATE SET
                        matches_played = EXCLUDED.matches_played,
                        wins = EXCLUDED.wins, losses = EXCLUDED.losses,
                        sets_won = EXCLUDED.sets_won, sets_lost = EXCLUDED.sets_lost,
                        points_won = EXCLUDED.points_won, points_lost = EXCLUDED.points_lost,
                        minutes_played = EXCLUDED.minutes_played,
                        fatigue_index = EXCLUDED.fatigue_index,
                        momentum = EXCLUDED.momentum,
                        updated_at = NOW()
                """),
                {
                    "pid": pid, "d": d,
                    "matches": rec["matches"], "wins": rec["wins"], "losses": rec["losses"],
                    "sets_won": rec["sets_won"], "sets_lost": rec["sets_lost"],
                    "pts_won": rec["points_won"], "pts_lost": rec["points_lost"],
                    "mins": mins, "fatigue": fatigue, "momentum": momentum,
                },
            )
            count += 1
        session.commit()
        return count
    except Exception as e:
        session.rollback()
        if "does not exist" in str(e).lower() or "player_daily_stats" in str(e):
            return 0
        raise
    finally:
        session.close()


def backfill_player_style_once(limit: int = 10_000) -> int:
    """Заполняет player_style из истории матчей. tempo, aggression, comeback, close_match."""
    session = get_ml_session()
    try:
        rows = session.execute(
            text("""
                SELECT DISTINCT p.id FROM players p
                JOIN matches m ON (m.player1_id = p.id OR m.player2_id = p.id)
                WHERE m.status = 'finished'
                LIMIT :lim
            """),
            {"lim": limit},
        ).fetchall()
        player_ids = [r[0] for r in rows if r[0]]

        count = 0
        for pid in player_ids:
            matches = session.execute(
                text("""
                    SELECT m.id, m.score_sets_p1, m.score_sets_p2, m.player1_id
                    FROM matches m
                    WHERE m.status = 'finished' AND (m.player1_id = :pid OR m.player2_id = :pid)
                    ORDER BY m.start_time DESC
                    LIMIT 30
                """),
                {"pid": pid},
            ).fetchall()

            if not matches:
                continue
            sets_list = []
            dominance_sum = 0.0
            dominance_n = 0
            comebacks = 0
            lost_first = 0
            close_matches = 0
            for r in matches:
                mid, s1, s2, p1_id = r[0], r[1], r[2], r[3]
                if s1 is None or s2 is None:
                    continue
                is_p1 = p1_id == pid
                total_sets = s1 + s2
                sets_list.append(total_sets)
                set_rows = session.execute(
                    text("SELECT score_p1, score_p2 FROM match_sets WHERE match_id = :mid"),
                    {"mid": mid},
                ).fetchall()
                for sr in set_rows:
                    sp1, sp2 = sr[0] or 0, sr[1] or 0
                    tot = sp1 + sp2
                    if tot > 0:
                        dominance_sum += (sp1 if is_p1 else sp2) / tot
                        dominance_n += 1
                if total_sets >= 5:
                    close_matches += 1
                set1_won = (s1 > s2) if is_p1 else (s2 > s1)
                if not set1_won:
                    lost_first += 1
                    match_won = (s1 > s2) if is_p1 else (s2 > s1)
                    if match_won:
                        comebacks += 1

            tempo = sum(sets_list) / len(sets_list) if sets_list else 3.5
            aggression = dominance_sum / dominance_n if dominance_n else 0.5
            comeback = comebacks / lost_first if lost_first > 0 else 0.5
            close_match = close_matches / len(matches) if matches else 0.5

            session.execute(
                text("""
                    INSERT INTO player_style (player_id, tempo_index, aggression_index,
                                             comeback_index, close_match_index, updated_at)
                    VALUES (:pid, :tempo, :aggression, :comeback, :close, NOW())
                    ON CONFLICT (player_id) DO UPDATE SET
                        tempo_index = EXCLUDED.tempo_index,
                        aggression_index = EXCLUDED.aggression_index,
                        comeback_index = EXCLUDED.comeback_index,
                        close_match_index = EXCLUDED.close_match_index,
                        updated_at = NOW()
                """),
                {"pid": pid, "tempo": tempo, "aggression": aggression, "comeback": comeback, "close": close_match},
            )
            count += 1
        session.commit()
        return count
    except Exception as e:
        session.rollback()
        if "does not exist" in str(e).lower() or "player_style" in str(e):
            return 0
        raise
    finally:
        session.close()


def backfill_player_elo_history_once(limit: int = 100_000) -> int:
    """Заполняет player_elo_history, пересчитывая Elo по всем матчам в хронологическом порядке.
    Нужно для elo_recent и elo_volatility. Возвращает число записей."""
    session = get_ml_session()
    try:
        session.execute(text("SELECT 1 FROM player_elo_history LIMIT 1"))
    except Exception:
        return 0
    try:
        rows = session.execute(
            text("""
                SELECT m.id, m.player1_id, m.player2_id, m.start_time,
                       m.score_sets_p1, m.score_sets_p2
                FROM matches m
                WHERE m.status = 'finished' AND m.score_sets_p1 IS NOT NULL
                ORDER BY m.start_time ASC
                LIMIT :lim
            """),
            {"lim": limit},
        ).fetchall()
        ratings: dict[int, float] = {}
        count = 0
        for r in rows:
            mid, p1, p2, st = r[0], r[1], r[2], r[3]
            s1, s2 = r[4] or 0, r[5] or 0
            if not p1 or not p2:
                continue
            r1 = ratings.get(p1, DEFAULT_ELO)
            r2 = ratings.get(p2, DEFAULT_ELO)
            expected = 1.0 / (1.0 + 10.0 ** ((r2 - r1) / 400.0))
            actual = 1.0 if s1 > s2 else 0.0
            k = 24.0
            delta = k * (actual - expected)
            new_r1 = r1 + delta
            new_r2 = r2 - delta
            ratings[p1] = new_r1
            ratings[p2] = new_r2
            session.execute(
                text("""
                    INSERT INTO player_elo_history (player_id, match_id, elo_before, elo_after, match_date)
                    VALUES (:p1, :mid, :r1, :nr1, :dt), (:p2, :mid, :r2, :nr2, :dt)
                    ON CONFLICT (player_id, match_id) DO NOTHING
                """),
                {"p1": p1, "p2": p2, "mid": mid, "r1": r1, "nr1": new_r1, "r2": r2, "nr2": new_r2, "dt": st},
            )
            count += 2
        session.commit()
        return count
    except Exception as e:
        session.rollback()
        if "does not exist" in str(e).lower() or "player_elo_history" in str(e):
            return 0
        raise
    finally:
        session.close()
