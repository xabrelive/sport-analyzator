"""Feature Engine v2: Elo, Form, Tempo, Streak, Density, Dominance, Volatility, League, Odds."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.ml.db import get_ml_session


@dataclass
class MatchFeatures:
    """Фичи для ML. Все diff = P1 - P2 (положительно = преимущество P1)."""
    # Базовые
    elo_diff: float
    form_diff: float
    fatigue_diff: float
    h2h_diff: float
    winrate_10_diff: float
    odds_diff: float
    elo_p1: float
    elo_p2: float
    form_p1: float
    form_p2: float
    fatigue_p1: float
    fatigue_p2: float
    h2h_count: int
    h2h_p1_wr: float
    winrate_10_p1: float
    winrate_10_p2: float
    odds_p1: float
    odds_p2: float
    league_id: str
    sample_size: int
    matches_played_p1: int
    matches_played_p2: int
    # Tempo (быстрые/медленные игроки)
    avg_sets_per_match_p1: float
    avg_sets_per_match_p2: float
    avg_sets_per_match_diff: float
    sets_over35_rate_p1: float
    sets_over35_rate_p2: float
    sets_over35_rate_diff: float
    # Streak
    streak_score: float  # min(5, win_streak) - min(5, loss_streak) для P1 минус для P2
    # Time since last match (минуты)
    minutes_since_last_match_p1: float
    minutes_since_last_match_p2: float
    minutes_since_last_match_diff: float
    # Match density (нелинейная усталость)
    matches_last_1h_p1: int
    matches_last_1h_p2: int
    matches_last_3h_p1: int
    matches_last_3h_p2: int
    matches_last_6h_p1: int
    matches_last_6h_p2: int
    matches_today_p1: int
    matches_today_p2: int
    # fatigue_index: matches_last_1h*12 + matches_last_3h*8 + matches_last_6h*4 + matches_today*1.5
    fatigue_index_p1: float
    fatigue_index_p2: float
    fatigue_index_diff: float
    # minutes_to_match: помогает модели понимать актуальность данных
    minutes_to_match: float
    # Dominance (points_won / total_points, стабильнее avg_point_diff)
    dominance_p1: float
    dominance_p2: float
    dominance_diff: float
    # Volatility
    std_points_diff_last10_p1: float
    std_points_diff_last10_p2: float
    std_sets_last10_p1: float
    std_sets_last10_p2: float
    # Upset rate (частота побед над фаворитом по Elo)
    upset_rate_p1: float
    upset_rate_p2: float
    upset_rate_diff: float
    # League normalization
    league_strength: float
    league_avg_sets: float
    league_avg_point_diff: float
    # Odds extended
    log_odds_ratio: float
    implied_prob_p1: float
    implied_prob_p2: float
    market_margin: float
    # Momentum today (критическая фича)
    wins_today_p1: int
    wins_today_p2: int
    momentum_today_diff: float  # (wins - losses) today, P1 - P2
    # Set1 strength: set1_winrate - overall_winrate
    set1_strength_p1: float
    set1_strength_p2: float
    set1_strength_diff: float
    # Comeback: проиграл 1-й сет, но выиграл матч
    comeback_rate_p1: float
    comeback_rate_p2: float
    comeback_rate_diff: float
    # Типы матчей (прибыльные)
    is_repeat_meeting: bool  # игроки играли вчера
    is_series_match: bool   # player plays 8+ matches today
    style_mismatch: float  # |avg_sets_p1 - avg_sets_p2|, attacker vs defender proxy
    # fatigue_decay: усталость с учётом времени между матчами
    fatigue_decay_p1: float  # matches_last3h*5 + matches_last6h*3 + matches_today
    fatigue_decay_p2: float
    fatigue_decay_diff: float
    # opponent_strength: сила соперников (avg_opponent_elo_last10)
    opponent_strength_p1: float
    opponent_strength_p2: float
    opponent_strength_diff: float
    # set_length_pattern: короткие/длинные сеты
    avg_points_per_set_p1: float
    avg_points_per_set_p2: float
    avg_points_per_set_diff: float
    # time_of_day_winrate: утренняя/вечерняя форма (TT — спорт формы внутри дня)
    time_of_day_winrate_p1: float
    time_of_day_winrate_p2: float
    time_of_day_winrate_diff: float
    # elo_recent: Elo за последние 30 дней (игроки TT часто резко меняют форму)
    elo_recent_p1: float
    elo_recent_p2: float
    elo_recent_diff: float
    # elo_volatility: std(elo_last20) — высокая волатильность → confidence ↓
    elo_volatility_p1: float
    elo_volatility_p2: float
    # daily_performance_trend: win_rate_last_3 - win_rate_today (trend < -0.3 → сливает)
    daily_performance_trend_p1: float
    daily_performance_trend_p2: float
    daily_performance_trend_diff: float
    # hours_since_last_h2h: repeat opponent < 24h — очень сильный сигнал
    hours_since_last_h2h: float
    # matchup_strength: h2h_winrate weighted by recency (некоторые игроки неудобны друг другу)
    matchup_strength_p1: float
    matchup_strength_p2: float
    matchup_strength_diff: float
    # fatigue_ratio: fatigue_p1/(fatigue_p2+1) — один свежий, другой 10 матчей
    fatigue_ratio: float
    # dominance_last_50: points_won/total_points за последние ~50 сетов (стабильнее)
    dominance_last_50_p1: float
    dominance_last_50_p2: float
    dominance_last_50_diff: float
    # closing_line_value: odds_open/odds_close, CLV>1.1 — рынок сильно двигался
    closing_line_value_p1: float
    closing_line_value_p2: float
    # odds_shift = odds_open / odds_current. > 1.1 — рынок уже что-то знает
    odds_shift_p1: float
    odds_shift_p2: float
    # elo_volatility_diff: std(elo_last20) P1 - P2
    elo_volatility_diff: float
    # dominance_trend: dominance_last_5 - dominance_last_20 (trend < -0.05 → проседает)
    dominance_trend_p1: float
    dominance_trend_p2: float
    dominance_trend_diff: float
    # style_clash: |tempo_p1 - tempo_p2| (attacker vs defender proxy)
    style_clash: float


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    var = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(var) if var > 0 else 0.0


class FeatureEngine:
    """Расчёт фичей для матча на основе истории в ML-БД."""

    def __init__(self, default_elo: float = 1500.0):
        self.default_elo = default_elo

    def _win_rate(self, wins: int, total: int) -> float:
        return wins / total if total else 0.5

    def _form_index(self, wr5: float, wr10: float, dominance: float) -> float:
        """Form = 0.4×wr5 + 0.3×wr10 + 0.3×dominance. dominance в [0,1]."""
        return 0.4 * wr5 + 0.3 * wr10 + 0.3 * dominance

    def compute_for_match(
        self,
        match_id: int,
        player1_id: int,
        player2_id: int,
        start_time: datetime,
        odds_p1: float,
        odds_p2: float,
        league_id: str,
        as_of_time: datetime | None = None,
        odds_open_p1: float | None = None,
        odds_open_p2: float | None = None,
    ) -> MatchFeatures | None:
        """Считает фичи для матча по данным до start_time.
        as_of_time: когда делаем прогноз (для minutes_to_match).
        odds_open_p1/p2: opening odds для odds_shift."""
        session = get_ml_session()
        try:
            cutoff = start_time - timedelta(seconds=1)
            ref = as_of_time or start_time
            minutes_to_match = max(0.0, (start_time - ref).total_seconds() / 60.0)
            day_start = start_time.replace(hour=0, minute=0, second=0, microsecond=0)

            ratings_rows = session.execute(
                text("SELECT player_id, rating, matches_played FROM player_ratings WHERE player_id = ANY(:pids)"),
                {"pids": [player1_id, player2_id]},
            ).fetchall()
            ratings = {r[0]: (float(r[1] or self.default_elo), int(r[2] or 0)) for r in ratings_rows}
            elo_p1, matches_played_p1 = ratings.get(player1_id, (self.default_elo, 0))
            elo_p2, matches_played_p2 = ratings.get(player2_id, (self.default_elo, 0))
            elo_diff = elo_p1 - elo_p2

            def _player_history(pid: int, limit: int) -> list[tuple[int, int, int, int, int, float, int, int, datetime | None]]:
                """(won, point_diff, total_sets, sets_over35, total_points, points_won, set1_won, opponent_id, start_time)"""
                rows = session.execute(
                    text("""
                        SELECT m.id, m.score_sets_p1, m.score_sets_p2, m.player1_id, m.player2_id, m.start_time
                        FROM matches m
                        WHERE m.status = 'finished' AND m.start_time < :cutoff
                          AND (m.player1_id = :pid OR m.player2_id = :pid)
                        ORDER BY m.start_time DESC
                        LIMIT :lim
                    """),
                    {"pid": pid, "cutoff": cutoff, "lim": limit},
                ).fetchall()
                match_ids = [r[0] for r in rows]
                sets_by_match: dict[int, list[tuple]] = {}
                if match_ids:
                    all_sets = session.execute(
                        text("SELECT match_id, set_number, score_p1, score_p2 FROM match_sets WHERE match_id = ANY(:ids) ORDER BY match_id, set_number"),
                        {"ids": match_ids},
                    ).fetchall()
                    for sr in all_sets:
                        mid = sr[0]
                        if mid not in sets_by_match:
                            sets_by_match[mid] = []
                        sets_by_match[mid].append((sr[1], sr[2], sr[3]))
                out = []
                for r in rows:
                    mid, s1, s2, p1_id, p2_id, st = r[0], r[1], r[2], r[3], r[4], r[5]
                    if s1 is None or s2 is None:
                        continue
                    is_p1 = p1_id == pid
                    opp_id = p2_id if is_p1 else p1_id
                    won = (s1 > s2) if is_p1 else (s2 > s1)
                    set_diff = (s1 - s2) if is_p1 else (s2 - s1)
                    total_sets = s1 + s2
                    sets_over35 = 1 if total_sets > 3.5 else 0
                    point_diff = set_diff * 5
                    total_points = 0
                    points_won = 0
                    set_rows = sets_by_match.get(mid, [])
                    set1_won = 0
                    if set_rows:
                        for sr in set_rows:
                            snum, sp1, sp2 = sr[0] or 0, sr[1] or 0, sr[2] or 0
                            total_points += sp1 + sp2
                            points_won += (sp1 if is_p1 else sp2)
                            if snum == 1:
                                set1_won = 1 if (sp1 > sp2 and is_p1) or (sp2 > sp1 and not is_p1) else 0
                        if not any(sr[0] == 1 for sr in set_rows):
                            set1_won = 1 if (won and is_p1) or (not won and not is_p1) else 0
                        point_diff = (sum(sr[1] or 0 for sr in set_rows) - sum(sr[2] or 0 for sr in set_rows)) if is_p1 else (sum(sr[2] or 0 for sr in set_rows) - sum(sr[1] or 0 for sr in set_rows))
                    else:
                        total_points = total_sets * 20
                        points_won = int(total_points * (0.5 + 0.05 * set_diff))
                        set1_won = 1 if (won and is_p1) or (not won and not is_p1) else 0
                    out.append((1 if won else 0, point_diff, total_sets, sets_over35, total_points, points_won, set1_won, opp_id or 0, st))
                return out

            h1_10 = _player_history(player1_id, 10)
            h2_10 = _player_history(player2_id, 10)
            h1_5 = h1_10[:5]
            h2_5 = h2_10[:5]

            def _weighted_win_rate(hist: list, half_life: float = 14.0) -> float:
                """win_rate с time decay: weight = exp(-days/half_life)."""
                total_w, total_weight = 0.0, 0.0
                for x in hist:
                    st = x[8] if len(x) > 8 else None
                    days = (cutoff - st).days if st else 0
                    w = math.exp(-days / half_life)
                    total_w += x[0] * w
                    total_weight += w
                return total_w / total_weight if total_weight > 1e-9 else 0.5

            wr5_p1 = _weighted_win_rate(h1_5) if h1_5 else 0.5
            wr5_p2 = _weighted_win_rate(h2_5) if h2_5 else 0.5
            wr10_p1 = _weighted_win_rate(h1_10) if h1_10 else 0.5
            wr10_p2 = _weighted_win_rate(h2_10) if h2_10 else 0.5
            winrate_10_diff = wr10_p1 - wr10_p2

            # Dominance: points_won / total_points
            tot_pts_p1 = sum(x[5] for x in h1_10)
            tot_pts_p1_all = sum(x[4] for x in h1_10)
            tot_pts_p2 = sum(x[5] for x in h2_10)
            tot_pts_p2_all = sum(x[4] for x in h2_10)
            dominance_p1 = tot_pts_p1 / tot_pts_p1_all if tot_pts_p1_all > 0 else 0.5
            dominance_p2 = tot_pts_p2 / tot_pts_p2_all if tot_pts_p2_all > 0 else 0.5
            dominance_diff = dominance_p1 - dominance_p2

            avg_diff_p1 = sum(x[1] for x in h1_10) / len(h1_10) if h1_10 else 0.0
            avg_diff_p2 = sum(x[1] for x in h2_10) / len(h2_10) if h2_10 else 0.0
            form_p1 = self._form_index(wr5_p1, wr10_p1, dominance_p1)
            form_p2 = self._form_index(wr5_p2, wr10_p2, dominance_p2)
            form_diff = form_p1 - form_p2

            # Tempo: avg_sets_per_match, sets_over35_rate
            sets_list_p1 = [x[2] for x in h1_10]
            sets_list_p2 = [x[2] for x in h2_10]
            avg_sets_p1 = sum(sets_list_p1) / len(sets_list_p1) if sets_list_p1 else 3.5
            avg_sets_p2 = sum(sets_list_p2) / len(sets_list_p2) if sets_list_p2 else 3.5
            over35_p1 = sum(1 for x in h1_10 if x[2] > 3.5) / len(h1_10) if h1_10 else 0.5
            over35_p2 = sum(1 for x in h2_10 if x[2] > 3.5) / len(h2_10) if h2_10 else 0.5
            avg_sets_per_match_diff = avg_sets_p1 - avg_sets_p2
            sets_over35_rate_diff = over35_p1 - over35_p2

            # Streak
            def _streak(hist: list) -> tuple[int, int]:
                win_s, loss_s = 0, 0
                for x in hist:
                    if x[0] == 1:
                        if loss_s > 0:
                            break
                        win_s += 1
                    else:
                        if win_s > 0:
                            break
                        loss_s += 1
                return win_s, loss_s

            ws1, ls1 = _streak(h1_10)
            ws2, ls2 = _streak(h2_10)
            streak_score = (min(5, ws1) - min(5, ls1)) - (min(5, ws2) - min(5, ls2))

            # Time since last match
            def _mins_since_last(pid: int) -> float:
                row = session.execute(
                    text("""
                        SELECT MAX(m.start_time) FROM matches m
                        WHERE m.status = 'finished' AND m.start_time < :cutoff
                          AND (m.player1_id = :pid OR m.player2_id = :pid)
                    """),
                    {"pid": pid, "cutoff": cutoff},
                ).fetchone()
                if not row or not row[0]:
                    return 7 * 24 * 60  # 7 дней default
                delta = cutoff - row[0]
                return max(0, delta.total_seconds() / 60)

            mins_p1 = _mins_since_last(player1_id)
            mins_p2 = _mins_since_last(player2_id)
            minutes_since_last_match_diff = mins_p2 - mins_p1  # P2 дольше не играл = усталость P1 меньше

            # Match density (добавляем 1h для fatigue_index)
            one_h_ago = cutoff - timedelta(hours=1)
            three_h_ago = cutoff - timedelta(hours=3)
            six_h_ago = cutoff - timedelta(hours=6)

            def _density(pid: int) -> tuple[int, int, int, int]:
                r1 = session.execute(
                    text("""
                        SELECT COUNT(*) FROM matches m
                        WHERE m.status = 'finished' AND m.start_time >= :since
                          AND (m.player1_id = :pid OR m.player2_id = :pid)
                    """),
                    {"pid": pid, "since": one_h_ago},
                ).scalar_one() or 0
                r3 = session.execute(
                    text("""
                        SELECT COUNT(*) FROM matches m
                        WHERE m.status = 'finished' AND m.start_time >= :since
                          AND (m.player1_id = :pid OR m.player2_id = :pid)
                    """),
                    {"pid": pid, "since": three_h_ago},
                ).scalar_one() or 0
                r6 = session.execute(
                    text("""
                        SELECT COUNT(*) FROM matches m
                        WHERE m.status = 'finished' AND m.start_time >= :since
                          AND (m.player1_id = :pid OR m.player2_id = :pid)
                    """),
                    {"pid": pid, "since": six_h_ago},
                ).scalar_one() or 0
                rday = session.execute(
                    text("""
                        SELECT COUNT(*) FROM matches m
                        WHERE m.status = 'finished' AND m.start_time >= :since
                          AND (m.player1_id = :pid OR m.player2_id = :pid)
                    """),
                    {"pid": pid, "since": day_start},
                ).scalar_one() or 0
                return int(r1), int(r3), int(r6), int(rday)

            d1_p1, d3_p1, d6_p1, dday_p1 = _density(player1_id)
            d1_p2, d3_p2, d6_p2, dday_p2 = _density(player2_id)
            fatigue_index_p1 = d1_p1 * 12.0 + d3_p1 * 8.0 + d6_p1 * 4.0 + dday_p1 * 1.5
            fatigue_index_p2 = d1_p2 * 12.0 + d3_p2 * 8.0 + d6_p2 * 4.0 + dday_p2 * 1.5
            fatigue_index_diff = fatigue_index_p2 - fatigue_index_p1

            # fatigue_decay: 8+ матчей → winrate падает 15-25%. 10/5/2 — усиленные веса
            fatigue_decay_p1 = d3_p1 * 10.0 + d6_p1 * 5.0 + dday_p1 * 2.0
            fatigue_decay_p2 = d3_p2 * 10.0 + d6_p2 * 5.0 + dday_p2 * 2.0
            fatigue_decay_diff = fatigue_decay_p2 - fatigue_decay_p1

            # dominance_last_50: points_won/total_points за последние ~50 сетов (стабильнее)
            h1_20 = _player_history(player1_id, 20)
            h2_20 = _player_history(player2_id, 20)
            def _dominance_last_n_sets(hist: list, n_sets: int = 50) -> float:
                pts_won, pts_tot, sets_count = 0, 0, 0
                for x in hist:
                    if sets_count >= n_sets:
                        break
                    pts_won += x[5]
                    pts_tot += x[4]
                    sets_count += x[2]
                return pts_won / pts_tot if pts_tot > 0 else 0.5
            dominance_last_50_p1 = _dominance_last_n_sets(h1_20)
            dominance_last_50_p2 = _dominance_last_n_sets(h2_20)
            dominance_last_50_diff = dominance_last_50_p1 - dominance_last_50_p2

            # dominance_trend: dominance_last_5 - dominance_last_20 (trend < -0.05 → проседает)
            def _dominance_last_n_matches(hist: list, n_matches: int) -> float:
                sub = hist[:n_matches] if len(hist) >= n_matches else hist
                return _dominance_last_n_sets(sub, n_sets=999)  # все сеты из n матчей
            dominance_last_5_p1 = _dominance_last_n_matches(h1_10, 5)
            dominance_last_5_p2 = _dominance_last_n_matches(h2_10, 5)
            dominance_last_20_p1 = _dominance_last_n_matches(h1_20, 20)
            dominance_last_20_p2 = _dominance_last_n_matches(h2_20, 20)
            dominance_trend_p1 = dominance_last_5_p1 - dominance_last_20_p1
            dominance_trend_p2 = dominance_last_5_p2 - dominance_last_20_p2
            dominance_trend_diff = dominance_trend_p1 - dominance_trend_p2

            # style_clash: |tempo_p1 - tempo_p2| из player_style
            def _get_tempo(pid: int) -> float:
                try:
                    r = session.execute(
                        text("SELECT tempo_index FROM player_style WHERE player_id = :pid"),
                        {"pid": pid},
                    ).fetchone()
                    return float(r[0] or 0) if r else 0.0
                except Exception:
                    return 0.0
            tempo_p1 = _get_tempo(player1_id)
            tempo_p2 = _get_tempo(player2_id)
            style_clash = abs(tempo_p1 - tempo_p2)

            # opponent_strength: avg_opponent_elo_last10
            def _avg_opponent_elo(hist: list, default: float = 1500.0) -> float:
                opp_ids = [x[7] for x in hist if x[7]]
                if not opp_ids:
                    return default
                placeholders = ", ".join(f":id{i}" for i in range(len(opp_ids)))
                params = {f"id{i}": oid for i, oid in enumerate(opp_ids)}
                rows = session.execute(
                    text(f"SELECT player_id, rating FROM player_ratings WHERE player_id IN ({placeholders})"),
                    params,
                ).fetchall()
                elo_map = {r[0]: float(r[1] or default) for r in rows}
                return sum(elo_map.get(oid, default) for oid in opp_ids) / len(opp_ids)
            opponent_strength_p1 = _avg_opponent_elo(h1_10, elo_p2)
            opponent_strength_p2 = _avg_opponent_elo(h2_10, elo_p1)
            opponent_strength_diff = opponent_strength_p1 - opponent_strength_p2

            # avg_points_per_set: set_length_pattern
            def _avg_pts_per_set(hist: list) -> float:
                tot_pts = sum(x[4] for x in hist)
                tot_sets = sum(x[2] for x in hist)
                return tot_pts / tot_sets if tot_sets > 0 else 20.0
            avg_points_per_set_p1 = _avg_pts_per_set(h1_10)
            avg_points_per_set_p2 = _avg_pts_per_set(h2_10)
            avg_points_per_set_diff = avg_points_per_set_p1 - avg_points_per_set_p2

            # time_of_day_winrate: winrate в тот же 4-часовой слот (morning/evening)
            hour_slot = start_time.hour // 4
            slot_start = hour_slot * 4
            slot_end = slot_start + 4

            def _time_of_day_winrate(pid: int) -> float:
                rows = session.execute(
                    text("""
                        SELECT m.score_sets_p1, m.score_sets_p2, m.player1_id,
                               EXTRACT(HOUR FROM m.start_time)::int as h
                        FROM matches m
                        WHERE m.status = 'finished' AND m.start_time < :cutoff
                          AND (m.player1_id = :pid OR m.player2_id = :pid)
                          AND EXTRACT(HOUR FROM m.start_time) >= :h1
                          AND EXTRACT(HOUR FROM m.start_time) < :h2
                    """),
                    {"pid": pid, "cutoff": cutoff, "h1": slot_start, "h2": slot_end},
                ).fetchall()
                if not rows:
                    return 0.5
                wins = sum(1 for r in rows if (r[2] == pid and r[0] > r[1]) or (r[2] != pid and r[1] > r[0]))
                return wins / len(rows)
            time_of_day_winrate_p1 = _time_of_day_winrate(player1_id)
            time_of_day_winrate_p2 = _time_of_day_winrate(player2_id)
            time_of_day_winrate_diff = time_of_day_winrate_p1 - time_of_day_winrate_p2

            # elo_recent (last 30 days) и elo_volatility (std last 20)
            def _elo_recent_volatility(pid: int) -> tuple[float, float]:
                try:
                    hist = session.execute(
                        text("""
                            SELECT elo_after FROM player_elo_history
                            WHERE player_id = :pid AND match_date < :cutoff
                            ORDER BY match_date DESC
                            LIMIT 30
                        """),
                        {"pid": pid, "cutoff": cutoff},
                    ).fetchall()
                    if not hist:
                        return elo_p1 if pid == player1_id else elo_p2, 0.0
                    elos = [float(r[0]) for r in hist]
                    recent = elos[0] if elos else 1500.0
                    last20 = elos[:20]
                    vol = _safe_std(last20) if len(last20) >= 2 else 0.0
                    return recent, vol
                except Exception:
                    return elo_p1 if pid == player1_id else elo_p2, 0.0
            elo_recent_p1, elo_volatility_p1 = _elo_recent_volatility(player1_id)
            elo_recent_p2, elo_volatility_p2 = _elo_recent_volatility(player2_id)
            elo_recent_diff = elo_recent_p1 - elo_recent_p2
            elo_volatility_diff = elo_volatility_p1 - elo_volatility_p2

            # Fatigue (day-based, как раньше)
            day_ago = day_start - timedelta(days=1)
            f1 = session.execute(
                text("""
                    SELECT COUNT(*) FROM matches m
                    WHERE m.status = 'finished' AND m.start_time >= :since
                      AND (m.player1_id = :pid OR m.player2_id = :pid)
                """),
                {"pid": player1_id, "since": day_ago},
            ).scalar_one() or 0
            f2 = session.execute(
                text("""
                    SELECT COUNT(*) FROM matches m
                    WHERE m.status = 'finished' AND m.start_time >= :since
                      AND (m.player1_id = :pid OR m.player2_id = :pid)
                """),
                {"pid": player2_id, "since": day_ago},
            ).scalar_one() or 0
            fatigue_p1 = min(100.0, f1 * 12.0)
            fatigue_p2 = min(100.0, f2 * 12.0)
            fatigue_diff = fatigue_p2 - fatigue_p1

            # fatigue_ratio: fatigue_p1/(fatigue_p2+1) — ловит «один свежий, другой 10 матчей»
            fatigue_ratio = fatigue_p1 / (fatigue_p2 + 1.0)

            # Volatility
            pt_diffs_p1 = [x[1] for x in h1_10]
            pt_diffs_p2 = [x[1] for x in h2_10]
            std_pt_p1 = _safe_std(pt_diffs_p1)
            std_pt_p2 = _safe_std(pt_diffs_p2)
            std_sets_p1 = _safe_std([float(x[2]) for x in h1_10])
            std_sets_p2 = _safe_std([float(x[2]) for x in h2_10])

            # Upset rate: победы когда соперник был фаворитом по Elo
            def _upset_rate(pid: int, hist: list) -> float:
                if not hist:
                    return 0.5
                upsets = 0
                total = 0
                for x in hist:
                    # Упрощённо: считаем по point_diff. Отрицательный diff при победе = upset
                    # Нужен elo_opp. Пропустим для первой версии — используем point_diff как прокси
                    total += 1
                return upsets / total if total else 0.5
            upset_rate_p1 = 0.5  # TODO: нужен elo на момент матча
            upset_rate_p2 = 0.5
            upset_rate_diff = 0.0

            # League aggregates
            league_strength = 0.0
            league_avg_sets = 3.5
            league_avg_point_diff = 0.0
            if league_id:
                row = session.execute(
                    text("""
                        SELECT AVG(m.score_sets_p1 + m.score_sets_p2), COUNT(*)
                        FROM matches m
                        WHERE m.league_id = :lid AND m.status = 'finished'
                          AND m.start_time >= :since
                    """),
                    {"lid": league_id, "since": cutoff - timedelta(days=365)},
                ).fetchone()
                if row and row[1] and row[1] > 10:
                    league_avg_sets = float(row[0] or 3.5)

            # H2H (с start_time для hours_since_last_h2h)
            h2h_rows = session.execute(
                text("""
                    SELECT score_sets_p1, score_sets_p2, player1_id, start_time
                    FROM matches
                    WHERE status = 'finished' AND start_time < :cutoff
                      AND ((player1_id = :p1 AND player2_id = :p2) OR (player1_id = :p2 AND player2_id = :p1))
                    ORDER BY start_time DESC
                """),
                {"cutoff": cutoff, "p1": player1_id, "p2": player2_id},
            ).fetchall()
            h2h_count = len(h2h_rows)
            h2h_p1_wins = sum(
                1 for r in h2h_rows
                if (r[2] == player1_id and r[0] > r[1]) or (r[2] == player2_id and r[1] > r[0])
            )
            h2h_p1_wr = self._win_rate(h2h_p1_wins, h2h_count) if h2h_count else 0.5
            h2h_diff = h2h_p1_wr - 0.5
            # matchup_strength: h2h weighted by recency exp(-days/30)
            matchup_strength_p1 = matchup_strength_p2 = 0.5
            if h2h_rows:
                w_sum, wr_weighted = 0.0, 0.0
                for r in h2h_rows:
                    won = (r[2] == player1_id and r[0] > r[1]) or (r[2] == player2_id and r[1] > r[0])
                    days = (cutoff - r[3]).days if r[3] else 0
                    w = math.exp(-days / 30.0)
                    wr_weighted += (1.0 if won else 0.0) * w
                    w_sum += w
                matchup_strength_p1 = wr_weighted / w_sum if w_sum > 1e-9 else 0.5
                matchup_strength_p2 = 1.0 - matchup_strength_p1
            matchup_strength_diff = matchup_strength_p1 - matchup_strength_p2
            hours_since_last_h2h = (
                (cutoff - h2h_rows[0][3]).total_seconds() / 3600.0
                if h2h_rows and h2h_rows[0][3] else 999.0
            )

            # Momentum today: wins_today, losses_today (матчи за сегодня до cutoff)
            day_start = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
            def _momentum_today(pid: int) -> tuple[int, int]:
                rows = session.execute(
                    text("""
                        SELECT m.score_sets_p1, m.score_sets_p2, m.player1_id
                        FROM matches m
                        WHERE m.status = 'finished' AND m.start_time >= :since AND m.start_time < :cutoff
                          AND (m.player1_id = :pid OR m.player2_id = :pid)
                    """),
                    {"pid": pid, "since": day_start, "cutoff": cutoff},
                ).fetchall()
                wins = losses = 0
                for r in rows:
                    is_p1 = r[2] == pid
                    won = (r[0] > r[1]) if is_p1 else (r[1] > r[0])
                    if won:
                        wins += 1
                    else:
                        losses += 1
                return wins, losses
            w1, l1 = _momentum_today(player1_id)
            w2, l2 = _momentum_today(player2_id)
            momentum_today_diff = (w1 - l1) - (w2 - l2)

            # daily_performance_trend: win_rate_last_3 - win_rate_today (trend < -0.3 → сливает)
            wr_last3_p1 = sum(x[0] for x in h1_10[:3]) / 3 if len(h1_10) >= 3 else 0.5
            wr_last3_p2 = sum(x[0] for x in h2_10[:3]) / 3 if len(h2_10) >= 3 else 0.5
            wr_today_p1 = w1 / (w1 + l1) if (w1 + l1) > 0 else 0.5
            wr_today_p2 = w2 / (w2 + l2) if (w2 + l2) > 0 else 0.5
            daily_performance_trend_p1 = wr_last3_p1 - wr_today_p1
            daily_performance_trend_p2 = wr_last3_p2 - wr_today_p2
            daily_performance_trend_diff = daily_performance_trend_p1 - daily_performance_trend_p2

            # Set1 strength: set1_winrate - overall_winrate
            set1_wr_p1 = sum(x[6] for x in h1_10) / len(h1_10) if h1_10 else 0.5
            set1_wr_p2 = sum(x[6] for x in h2_10) / len(h2_10) if h2_10 else 0.5
            set1_strength_p1 = set1_wr_p1 - wr10_p1
            set1_strength_p2 = set1_wr_p2 - wr10_p2
            set1_strength_diff = set1_strength_p1 - set1_strength_p2

            # Comeback rate: проиграл 1-й сет, но выиграл матч
            def _comeback_rate(hist: list) -> float:
                lost_first = sum(1 for x in hist if x[6] == 0)
                comebacks = sum(1 for x in hist if x[6] == 0 and x[0] == 1)
                return comebacks / lost_first if lost_first > 0 else 0.5
            comeback_rate_p1 = _comeback_rate(h1_10)
            comeback_rate_p2 = _comeback_rate(h2_10)
            comeback_rate_diff = comeback_rate_p1 - comeback_rate_p2

            # odds_shift = odds_open / odds_current. > 1.1 — рынок уже что-то знает
            odds_shift_p1 = odds_shift_p2 = 1.0
            if odds_open_p1 is not None and odds_open_p1 > 1e-9 and odds_p1 > 1e-9:
                odds_shift_p1 = odds_open_p1 / odds_p1
            if odds_open_p2 is not None and odds_open_p2 > 1e-9 and odds_p2 > 1e-9:
                odds_shift_p2 = odds_open_p2 / odds_p2

            # closing_line_value: odds_open/odds_close. CLV>1.1 — рынок сильно двигался
            closing_line_value_p1 = closing_line_value_p2 = 1.0
            if match_id and match_id > 0:
                odds_rows = session.execute(
                    text("SELECT odds_p1, odds_p2 FROM odds WHERE match_id = :mid ORDER BY created_at ASC"),
                    {"mid": match_id},
                ).fetchall()
                if len(odds_rows) >= 2:
                    oo1, oo2 = float(odds_rows[0][0] or 1.9), float(odds_rows[0][1] or 1.9)
                    oc1, oc2 = float(odds_rows[-1][0] or 1.9), float(odds_rows[-1][1] or 1.9)
                    closing_line_value_p1 = oo1 / oc1 if oc1 > 1e-9 else 1.0
                    closing_line_value_p2 = oo2 / oc2 if oc2 > 1e-9 else 1.0

            # Odds
            odds_diff = 0.0
            log_odds_ratio = 0.0
            implied_prob_p1 = 0.5
            implied_prob_p2 = 0.5
            market_margin = 0.0
            if odds_p1 > 1e-9 and odds_p2 > 1e-9:
                imp1 = 1.0 / odds_p1
                imp2 = 1.0 / odds_p2
                norm = imp1 + imp2
                if norm > 1e-9:
                    odds_diff = (imp1 - imp2) / norm
                    implied_prob_p1 = imp1
                    implied_prob_p2 = imp2
                    market_margin = norm - 1.0
                if odds_p2 > 1e-9:
                    log_odds_ratio = math.log(odds_p2 / odds_p1) if odds_p1 > 1e-9 else 0.0

            sample_size = len(h1_10) + len(h2_10) + h2h_count

            # Типы матчей (прибыльные)
            yesterday_start = day_start - timedelta(days=1)
            repeat_row = session.execute(
                text("""
                    SELECT 1 FROM matches m
                    WHERE m.status = 'finished' AND m.start_time >= :since AND m.start_time < :cutoff
                      AND ((m.player1_id = :p1 AND m.player2_id = :p2) OR (m.player1_id = :p2 AND m.player2_id = :p1))
                    LIMIT 1
                """),
                {"since": yesterday_start, "cutoff": cutoff, "p1": player1_id, "p2": player2_id},
            ).fetchone()
            is_repeat_meeting = repeat_row is not None
            is_series_match = dday_p1 >= 8 or dday_p2 >= 8
            style_mismatch = abs(avg_sets_p1 - avg_sets_p2)

            return MatchFeatures(
                elo_diff=elo_diff,
                form_diff=form_diff,
                fatigue_diff=fatigue_diff,
                h2h_diff=h2h_diff,
                winrate_10_diff=winrate_10_diff,
                odds_diff=odds_diff,
                elo_p1=elo_p1,
                elo_p2=elo_p2,
                form_p1=form_p1,
                form_p2=form_p2,
                fatigue_p1=fatigue_p1,
                fatigue_p2=fatigue_p2,
                h2h_count=h2h_count,
                h2h_p1_wr=h2h_p1_wr,
                winrate_10_p1=wr10_p1,
                winrate_10_p2=wr10_p2,
                odds_p1=odds_p1,
                odds_p2=odds_p2,
                league_id=league_id or "",
                sample_size=sample_size,
                matches_played_p1=matches_played_p1,
                matches_played_p2=matches_played_p2,
                avg_sets_per_match_p1=avg_sets_p1,
                avg_sets_per_match_p2=avg_sets_p2,
                avg_sets_per_match_diff=avg_sets_per_match_diff,
                sets_over35_rate_p1=over35_p1,
                sets_over35_rate_p2=over35_p2,
                sets_over35_rate_diff=sets_over35_rate_diff,
                streak_score=streak_score,
                minutes_since_last_match_p1=mins_p1,
                minutes_since_last_match_p2=mins_p2,
                minutes_since_last_match_diff=minutes_since_last_match_diff,
                matches_last_1h_p1=d1_p1,
                matches_last_1h_p2=d1_p2,
                matches_last_3h_p1=d3_p1,
                matches_last_3h_p2=d3_p2,
                matches_last_6h_p1=d6_p1,
                matches_last_6h_p2=d6_p2,
                matches_today_p1=dday_p1,
                matches_today_p2=dday_p2,
                dominance_p1=dominance_p1,
                dominance_p2=dominance_p2,
                dominance_diff=dominance_diff,
                std_points_diff_last10_p1=std_pt_p1,
                std_points_diff_last10_p2=std_pt_p2,
                std_sets_last10_p1=std_sets_p1,
                std_sets_last10_p2=std_sets_p2,
                upset_rate_p1=upset_rate_p1,
                upset_rate_p2=upset_rate_p2,
                upset_rate_diff=upset_rate_diff,
                league_strength=league_strength,
                league_avg_sets=league_avg_sets,
                league_avg_point_diff=league_avg_point_diff,
                log_odds_ratio=log_odds_ratio,
                implied_prob_p1=implied_prob_p1,
                implied_prob_p2=implied_prob_p2,
                market_margin=market_margin,
                wins_today_p1=w1,
                wins_today_p2=w2,
                momentum_today_diff=momentum_today_diff,
                set1_strength_p1=set1_strength_p1,
                set1_strength_p2=set1_strength_p2,
                set1_strength_diff=set1_strength_diff,
                comeback_rate_p1=comeback_rate_p1,
                comeback_rate_p2=comeback_rate_p2,
                comeback_rate_diff=comeback_rate_diff,
                is_repeat_meeting=is_repeat_meeting,
                is_series_match=is_series_match,
                style_mismatch=style_mismatch,
                fatigue_decay_p1=fatigue_decay_p1,
                fatigue_decay_p2=fatigue_decay_p2,
                fatigue_decay_diff=fatigue_decay_diff,
                opponent_strength_p1=opponent_strength_p1,
                opponent_strength_p2=opponent_strength_p2,
                opponent_strength_diff=opponent_strength_diff,
                avg_points_per_set_p1=avg_points_per_set_p1,
                avg_points_per_set_p2=avg_points_per_set_p2,
                avg_points_per_set_diff=avg_points_per_set_diff,
            time_of_day_winrate_p1=time_of_day_winrate_p1,
            time_of_day_winrate_p2=time_of_day_winrate_p2,
            time_of_day_winrate_diff=time_of_day_winrate_diff,
            elo_recent_p1=elo_recent_p1,
            elo_recent_p2=elo_recent_p2,
            elo_recent_diff=elo_recent_diff,
            elo_volatility_p1=elo_volatility_p1,
            elo_volatility_p2=elo_volatility_p2,
            elo_volatility_diff=elo_volatility_diff,
            dominance_trend_p1=dominance_trend_p1,
            dominance_trend_p2=dominance_trend_p2,
            dominance_trend_diff=dominance_trend_diff,
            style_clash=style_clash,
            daily_performance_trend_p1=daily_performance_trend_p1,
            daily_performance_trend_p2=daily_performance_trend_p2,
            daily_performance_trend_diff=daily_performance_trend_diff,
            hours_since_last_h2h=hours_since_last_h2h,
            matchup_strength_p1=matchup_strength_p1,
            matchup_strength_p2=matchup_strength_p2,
            matchup_strength_diff=matchup_strength_diff,
                fatigue_index_p1=fatigue_index_p1,
                fatigue_index_p2=fatigue_index_p2,
                fatigue_index_diff=fatigue_index_diff,
                minutes_to_match=minutes_to_match,
                odds_shift_p1=odds_shift_p1,
                odds_shift_p2=odds_shift_p2,
                fatigue_ratio=fatigue_ratio,
            dominance_last_50_p1=dominance_last_50_p1,
            dominance_last_50_p2=dominance_last_50_p2,
            dominance_last_50_diff=dominance_last_50_diff,
            closing_line_value_p1=closing_line_value_p1,
            closing_line_value_p2=closing_line_value_p2,
            )
        finally:
            try:
                session.rollback()
            except Exception:
                pass
            session.close()

    def upsert_match_features(self, match_id: int, features: MatchFeatures) -> None:
        """Сохраняет фичи (базовые + v2 колонки при наличии)."""
        session = get_ml_session()
        try:
            session.execute(
                text("""
                    INSERT INTO match_features (
                        match_id, elo_p1, elo_p2, elo_diff, form_p1, form_p2, form_diff,
                        fatigue_p1, fatigue_p2, fatigue_diff, h2h_count, h2h_p1_wr, h2h_diff,
                        winrate_10_p1, winrate_10_p2, winrate_10_diff, odds_p1, odds_p2, odds_diff, league_id,
                        avg_sets_per_match_diff, sets_over35_rate_diff, streak_score,
                        minutes_since_last_match_diff, dominance_diff,
                        std_points_diff_last10_p1, std_points_diff_last10_p2,
                        log_odds_ratio, implied_prob_p1, implied_prob_p2, market_margin,
                        momentum_today_diff, set1_strength_diff, comeback_rate_diff,
                        dominance_last_50_diff, fatigue_index_diff, fatigue_ratio, minutes_to_match,
                        odds_shift_p1, odds_shift_p2, elo_volatility_p1, elo_volatility_p2, elo_volatility_diff,
                        daily_performance_trend_diff, dominance_trend_diff, style_clash
                    ) VALUES (
                        :mid, :e1, :e2, :ed, :f1, :f2, :fd, :g1, :g2, :gd, :hc, :hw, :hd,
                        :w1, :w2, :wd, :o1, :o2, :od, :lid,
                        :avg_sets_diff, :over35_diff, :streak, :mins_diff, :dom_diff,
                        :std_p1, :std_p2, :log_odds, :imp_p1, :imp_p2, :margin,
                        :momentum_diff, :set1_str, :comeback_diff,
                        :dom50_diff, :fatigue_idx_diff, :fatigue_ratio, :mins_to_match,
                        :odds_shift_p1, :odds_shift_p2, :elo_vol_p1, :elo_vol_p2, :elo_vol_diff,
                        :daily_trend_diff, :dom_trend_diff, :style_clash
                    )
                    ON CONFLICT (match_id) DO UPDATE SET
                        elo_p1 = EXCLUDED.elo_p1, elo_p2 = EXCLUDED.elo_p2, elo_diff = EXCLUDED.elo_diff,
                        form_p1 = EXCLUDED.form_p1, form_p2 = EXCLUDED.form_p2, form_diff = EXCLUDED.form_diff,
                        fatigue_p1 = EXCLUDED.fatigue_p1, fatigue_p2 = EXCLUDED.fatigue_p2, fatigue_diff = EXCLUDED.fatigue_diff,
                        h2h_count = EXCLUDED.h2h_count, h2h_p1_wr = EXCLUDED.h2h_p1_wr, h2h_diff = EXCLUDED.h2h_diff,
                        winrate_10_p1 = EXCLUDED.winrate_10_p1, winrate_10_p2 = EXCLUDED.winrate_10_p2, winrate_10_diff = EXCLUDED.winrate_10_diff,
                        odds_p1 = EXCLUDED.odds_p1, odds_p2 = EXCLUDED.odds_p2, odds_diff = EXCLUDED.odds_diff,
                        league_id = EXCLUDED.league_id,
                        avg_sets_per_match_diff = EXCLUDED.avg_sets_per_match_diff,
                        sets_over35_rate_diff = EXCLUDED.sets_over35_rate_diff,
                        streak_score = EXCLUDED.streak_score,
                        minutes_since_last_match_diff = EXCLUDED.minutes_since_last_match_diff,
                        dominance_diff = EXCLUDED.dominance_diff,
                        std_points_diff_last10_p1 = EXCLUDED.std_points_diff_last10_p1,
                        std_points_diff_last10_p2 = EXCLUDED.std_points_diff_last10_p2,
                        log_odds_ratio = EXCLUDED.log_odds_ratio,
                        implied_prob_p1 = EXCLUDED.implied_prob_p1,
                        implied_prob_p2 = EXCLUDED.implied_prob_p2,
                        market_margin = EXCLUDED.market_margin,
                        momentum_today_diff = EXCLUDED.momentum_today_diff,
                        set1_strength_diff = EXCLUDED.set1_strength_diff,
                        comeback_rate_diff = EXCLUDED.comeback_rate_diff,
                        dominance_last_50_diff = EXCLUDED.dominance_last_50_diff,
                        fatigue_index_diff = EXCLUDED.fatigue_index_diff,
                        fatigue_ratio = EXCLUDED.fatigue_ratio,
                        minutes_to_match = EXCLUDED.minutes_to_match,
                        odds_shift_p1 = EXCLUDED.odds_shift_p1,
                        odds_shift_p2 = EXCLUDED.odds_shift_p2,
                        elo_volatility_p1 = EXCLUDED.elo_volatility_p1,
                        elo_volatility_p2 = EXCLUDED.elo_volatility_p2,
                        elo_volatility_diff = EXCLUDED.elo_volatility_diff,
                        daily_performance_trend_diff = EXCLUDED.daily_performance_trend_diff,
                        dominance_trend_diff = EXCLUDED.dominance_trend_diff,
                        style_clash = EXCLUDED.style_clash,
                        created_at = NOW()
                """),
                {
                    "mid": match_id,
                    "e1": features.elo_p1, "e2": features.elo_p2, "ed": features.elo_diff,
                    "f1": features.form_p1, "f2": features.form_p2, "fd": features.form_diff,
                    "g1": features.fatigue_p1, "g2": features.fatigue_p2, "gd": features.fatigue_diff,
                    "hc": features.h2h_count, "hw": features.h2h_p1_wr, "hd": features.h2h_diff,
                    "w1": features.winrate_10_p1, "w2": features.winrate_10_p2, "wd": features.winrate_10_diff,
                    "o1": features.odds_p1, "o2": features.odds_p2, "od": features.odds_diff,
                    "lid": features.league_id,
                    "avg_sets_diff": features.avg_sets_per_match_diff,
                    "over35_diff": features.sets_over35_rate_diff,
                    "streak": features.streak_score,
                    "mins_diff": features.minutes_since_last_match_diff,
                    "dom_diff": features.dominance_diff,
                    "std_p1": features.std_points_diff_last10_p1,
                    "std_p2": features.std_points_diff_last10_p2,
                    "log_odds": features.log_odds_ratio,
                    "imp_p1": features.implied_prob_p1,
                    "imp_p2": features.implied_prob_p2,
                    "margin": features.market_margin,
                    "momentum_diff": features.momentum_today_diff,
                    "set1_str": features.set1_strength_diff,
                    "comeback_diff": features.comeback_rate_diff,
                    "dom50_diff": features.dominance_last_50_diff,
                    "fatigue_idx_diff": features.fatigue_index_diff,
                    "fatigue_ratio": features.fatigue_ratio,
                    "mins_to_match": features.minutes_to_match,
                    "odds_shift_p1": features.odds_shift_p1,
                    "odds_shift_p2": features.odds_shift_p2,
                    "elo_vol_p1": features.elo_volatility_p1,
                    "elo_vol_p2": features.elo_volatility_p2,
                    "elo_vol_diff": features.elo_volatility_diff,
                    "daily_trend_diff": features.daily_performance_trend_diff,
                    "dom_trend_diff": features.dominance_trend_diff,
                    "style_clash": features.style_clash,
                },
            )
            session.commit()
        except Exception:
            session.rollback()
            try:
                _upsert_match_features_v2_only(session, match_id, features)
                session.commit()
            except Exception:
                session.rollback()
                _upsert_match_features_legacy(session, match_id, features)
                session.commit()
        finally:
            session.close()


def _upsert_match_features_v2_only(session, match_id: int, features: MatchFeatures) -> None:
    """Fallback: v2 колонки без v3 (если миграция 10 ещё не применена)."""
    session.execute(
        text("""
            INSERT INTO match_features (
                match_id, elo_p1, elo_p2, elo_diff, form_p1, form_p2, form_diff,
                fatigue_p1, fatigue_p2, fatigue_diff, h2h_count, h2h_p1_wr, h2h_diff,
                winrate_10_p1, winrate_10_p2, winrate_10_diff, odds_p1, odds_p2, odds_diff, league_id,
                avg_sets_per_match_diff, sets_over35_rate_diff, streak_score,
                minutes_since_last_match_diff, dominance_diff,
                std_points_diff_last10_p1, std_points_diff_last10_p2,
                log_odds_ratio, implied_prob_p1, implied_prob_p2, market_margin,
                momentum_today_diff, set1_strength_diff, comeback_rate_diff
            ) VALUES (
                :mid, :e1, :e2, :ed, :f1, :f2, :fd, :g1, :g2, :gd, :hc, :hw, :hd,
                :w1, :w2, :wd, :o1, :o2, :od, :lid,
                :avg_sets_diff, :over35_diff, :streak, :mins_diff, :dom_diff,
                :std_p1, :std_p2, :log_odds, :imp_p1, :imp_p2, :margin,
                :momentum_diff, :set1_str, :comeback_diff
            )
            ON CONFLICT (match_id) DO UPDATE SET
                elo_p1 = EXCLUDED.elo_p1, elo_p2 = EXCLUDED.elo_p2, elo_diff = EXCLUDED.elo_diff,
                form_p1 = EXCLUDED.form_p1, form_p2 = EXCLUDED.form_p2, form_diff = EXCLUDED.form_diff,
                fatigue_p1 = EXCLUDED.fatigue_p1, fatigue_p2 = EXCLUDED.fatigue_p2, fatigue_diff = EXCLUDED.fatigue_diff,
                h2h_count = EXCLUDED.h2h_count, h2h_p1_wr = EXCLUDED.h2h_p1_wr, h2h_diff = EXCLUDED.h2h_diff,
                winrate_10_p1 = EXCLUDED.winrate_10_p1, winrate_10_p2 = EXCLUDED.winrate_10_p2, winrate_10_diff = EXCLUDED.winrate_10_diff,
                odds_p1 = EXCLUDED.odds_p1, odds_p2 = EXCLUDED.odds_p2, odds_diff = EXCLUDED.odds_diff,
                league_id = EXCLUDED.league_id,
                avg_sets_per_match_diff = EXCLUDED.avg_sets_per_match_diff,
                sets_over35_rate_diff = EXCLUDED.sets_over35_rate_diff,
                streak_score = EXCLUDED.streak_score,
                minutes_since_last_match_diff = EXCLUDED.minutes_since_last_match_diff,
                dominance_diff = EXCLUDED.dominance_diff,
                std_points_diff_last10_p1 = EXCLUDED.std_points_diff_last10_p1,
                std_points_diff_last10_p2 = EXCLUDED.std_points_diff_last10_p2,
                log_odds_ratio = EXCLUDED.log_odds_ratio,
                implied_prob_p1 = EXCLUDED.implied_prob_p1,
                implied_prob_p2 = EXCLUDED.implied_prob_p2,
                market_margin = EXCLUDED.market_margin,
                momentum_today_diff = EXCLUDED.momentum_today_diff,
                set1_strength_diff = EXCLUDED.set1_strength_diff,
                comeback_rate_diff = EXCLUDED.comeback_rate_diff,
                created_at = NOW()
        """),
        {
            "mid": match_id,
            "e1": features.elo_p1, "e2": features.elo_p2, "ed": features.elo_diff,
            "f1": features.form_p1, "f2": features.form_p2, "fd": features.form_diff,
            "g1": features.fatigue_p1, "g2": features.fatigue_p2, "gd": features.fatigue_diff,
            "hc": features.h2h_count, "hw": features.h2h_p1_wr, "hd": features.h2h_diff,
            "w1": features.winrate_10_p1, "w2": features.winrate_10_p2, "wd": features.winrate_10_diff,
            "o1": features.odds_p1, "o2": features.odds_p2, "od": features.odds_diff,
            "lid": features.league_id,
            "avg_sets_diff": features.avg_sets_per_match_diff,
            "over35_diff": features.sets_over35_rate_diff,
            "streak": features.streak_score,
            "mins_diff": features.minutes_since_last_match_diff,
            "dom_diff": features.dominance_diff,
            "std_p1": features.std_points_diff_last10_p1,
            "std_p2": features.std_points_diff_last10_p2,
            "log_odds": features.log_odds_ratio,
            "imp_p1": features.implied_prob_p1,
            "imp_p2": features.implied_prob_p2,
            "margin": features.market_margin,
            "momentum_diff": features.momentum_today_diff,
            "set1_str": features.set1_strength_diff,
            "comeback_diff": features.comeback_rate_diff,
        },
    )


def _upsert_match_features_legacy(session, match_id: int, features: MatchFeatures) -> None:
    """Fallback: только базовые колонки (если v2 ещё не применена)."""
    session.execute(
        text("""
            INSERT INTO match_features (
                match_id, elo_p1, elo_p2, elo_diff, form_p1, form_p2, form_diff,
                fatigue_p1, fatigue_p2, fatigue_diff, h2h_count, h2h_p1_wr, h2h_diff,
                winrate_10_p1, winrate_10_p2, winrate_10_diff, odds_p1, odds_p2, odds_diff, league_id
            ) VALUES (
                :mid, :e1, :e2, :ed, :f1, :f2, :fd, :g1, :g2, :gd, :hc, :hw, :hd,
                :w1, :w2, :wd, :o1, :o2, :od, :lid
            )
            ON CONFLICT (match_id) DO UPDATE SET
                elo_p1 = EXCLUDED.elo_p1, elo_p2 = EXCLUDED.elo_p2, elo_diff = EXCLUDED.elo_diff,
                form_p1 = EXCLUDED.form_p1, form_p2 = EXCLUDED.form_p2, form_diff = EXCLUDED.form_diff,
                fatigue_p1 = EXCLUDED.fatigue_p1, fatigue_p2 = EXCLUDED.fatigue_p2, fatigue_diff = EXCLUDED.fatigue_diff,
                h2h_count = EXCLUDED.h2h_count, h2h_p1_wr = EXCLUDED.h2h_p1_wr, h2h_diff = EXCLUDED.h2h_diff,
                winrate_10_p1 = EXCLUDED.winrate_10_p1, winrate_10_p2 = EXCLUDED.winrate_10_p2, winrate_10_diff = EXCLUDED.winrate_10_diff,
                odds_p1 = EXCLUDED.odds_p1, odds_p2 = EXCLUDED.odds_p2, odds_diff = EXCLUDED.odds_diff,
                league_id = EXCLUDED.league_id, created_at = NOW()
        """),
        {
            "mid": match_id,
            "e1": features.elo_p1, "e2": features.elo_p2, "ed": features.elo_diff,
            "f1": features.form_p1, "f2": features.form_p2, "fd": features.form_diff,
            "g1": features.fatigue_p1, "g2": features.fatigue_p2, "gd": features.fatigue_diff,
            "hc": features.h2h_count, "hw": features.h2h_p1_wr, "hd": features.h2h_diff,
            "w1": features.winrate_10_p1, "w2": features.winrate_10_p2, "wd": features.winrate_10_diff,
            "o1": features.odds_p1, "o2": features.odds_p2, "od": features.odds_diff,
            "lid": features.league_id,
        },
    )
