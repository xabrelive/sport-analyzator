"""League ROI tracking: league_performance, upset_rate, rolling ROI (last 500 matches)."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text

from app.ml.db import get_ml_session

ROLLING_MATCHES = 500  # ROI по последним 500 матчам лиги (стабильнее all-time)


@dataclass
class LeagueStats:
    league_id: str
    matches: int
    wins: int
    losses: int
    roi_pct: float
    avg_ev: float
    avg_odds: float
    upset_rate: float
    underdog_wins: int


MIN_LEAGUE_MATCHES = 500  # стабильнее при 500+
MIN_LEAGUE_ROI_PCT = 7.0  # roi > 7% — сильнее фильтр
MAX_LEAGUE_UPSET_RATE = 0.40


def get_league_stats(league_id: str) -> LeagueStats | None:
    """Возвращает статистику лиги или None если недостаточно данных."""
    session = get_ml_session()
    try:
        row = session.execute(
            text("""
                SELECT league_id, matches, wins, losses, roi_pct, avg_ev, avg_odds,
                       upset_rate, underdog_wins
                FROM league_performance
                WHERE league_id = :lid
            """),
            {"lid": league_id},
        ).fetchone()
        if not row:
            return None
        return LeagueStats(
            league_id=row[0],
            matches=int(row[1] or 0),
            wins=int(row[2] or 0),
            losses=int(row[3] or 0),
            roi_pct=float(row[4] or 0),
            avg_ev=float(row[5] or 0),
            avg_odds=float(row[6] or 0),
            upset_rate=float(row[7] or 0),
            underdog_wins=int(row[8] or 0),
        )
    finally:
        session.close()


def league_passes_filter(league_id: str) -> bool:
    """Сигнал только если league_roi > 7%, matches > 500, upset_rate < 40%."""
    if not league_id:
        return True
    stats = get_league_stats(league_id)
    if not stats:
        return True
    if stats.matches < MIN_LEAGUE_MATCHES:
        return False
    if stats.roi_pct < MIN_LEAGUE_ROI_PCT:
        return False
    if stats.upset_rate > MAX_LEAGUE_UPSET_RATE:
        return False
    return True


def league_confidence_reduction(league_id: str) -> float:
    """Снижение confidence для нестабильных лиг (upset_rate > 40%). 0 = no reduction, 1 = max."""
    stats = get_league_stats(league_id)
    if not stats or stats.matches < 50:
        return 0.0
    if stats.upset_rate <= MAX_LEAGUE_UPSET_RATE:
        return 0.0
    return min(1.0, (stats.upset_rate - MAX_LEAGUE_UPSET_RATE) * 0.5)


def update_league_performance_once(limit: int = 100_000) -> int:
    """Пересчёт league_performance из finished matches + match_features.
    Симулирует сигналы (EV>0.08), считает ROI и upset_rate по лигам."""
    from app.ml.model_trainer import load_models, predict_proba, FEATURE_COLS
    from app.ml.value_detector import expected_value

    session = get_ml_session()
    try:
        rows = session.execute(
            text("""
                SELECT m.id, m.league_id, m.score_sets_p1, m.score_sets_p2,
                       mf.elo_diff, mf.form_diff, mf.fatigue_diff, mf.h2h_diff,
                       mf.winrate_10_diff, mf.odds_diff, mf.h2h_count,
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
            {"lim": min(limit, 100_000)},
        ).fetchall()
        odds_rows = session.execute(
            text("SELECT match_id, odds_p1, odds_p2 FROM odds")
        ).fetchall()
        odds_map = {r[0]: (float(r[1] or 1.9), float(r[2] or 1.9)) for r in odds_rows}

        try:
            _, model_set1, _, _ = load_models()
        except Exception:
            return 0

        col_order = [
            "elo_diff", "form_diff", "fatigue_diff", "h2h_diff", "winrate_10_diff", "odds_diff", "h2h_count",
            "avg_sets_per_match_diff", "sets_over35_rate_diff", "streak_score",
            "minutes_since_last_match_diff", "dominance_diff",
            "std_points_diff_last10_p1", "std_points_diff_last10_p2",
            "log_odds_ratio", "implied_prob_p1", "market_margin",
            "momentum_today_diff", "set1_strength_diff", "comeback_rate_diff",
        ]
        from app.ml.probability import p_match_from_p_set_analytical

        by_league: dict[str, list[tuple[bool, float, float]]] = {}
        upset_by_league: dict[str, list[bool]] = {}
        # Ограничиваем последними N матчами на лигу (rolling ROI)
        league_order: dict[str, list[int]] = {}  # league -> [match_ids] в порядке убывания времени
        for r in rows:
            match_id, league_id, s1, s2 = r[0], r[1] or "", r[2], r[3]
            if not league_id:
                continue
            league_order.setdefault(league_id, []).append(match_id)
        # Берём только последние ROLLING_MATCHES матчей на лигу
        recent_by_league: dict[str, set[int]] = {}
        for lid, mids in league_order.items():
            recent_by_league[lid] = set(mids[:ROLLING_MATCHES])

        for r in rows:
            match_id, league_id, s1, s2 = r[0], r[1] or "", r[2], r[3]
            if not league_id or match_id not in recent_by_league.get(league_id, set()):
                continue
            o1, o2 = odds_map.get(match_id, (1.9, 1.9))
            p1_won = s1 > s2
            fav_p1 = o1 < o2
            underdog_won = (fav_p1 and not p1_won) or (not fav_p1 and p1_won)
            upset_by_league.setdefault(league_id, []).append(underdog_won)

            feat_dict = {c: float(r[4 + i]) if 4 + i < len(r) and r[4 + i] is not None else 0.0 for i, c in enumerate(col_order)}
            for c in FEATURE_COLS:
                if c not in feat_dict:
                    feat_dict[c] = 0.0
            try:
                p_set1 = predict_proba(model_set1, feat_dict)
                p_match = p_match_from_p_set_analytical(p_set1)
            except Exception:
                continue

            for side, p, odds in [("p1", p_match, o1), ("p2", 1 - p_match, o2)]:
                ev = expected_value(p, odds)
                if ev >= 0.08 and 1.6 <= odds <= 2.6:
                    won = (side == "p1" and p1_won) or (side == "p2" and not p1_won)
                    profit = (odds - 1) if won else -1
                    by_league.setdefault(league_id, []).append((won, ev, odds))

        for league_id, outcomes in upset_by_league.items():
            underdog_wins = sum(1 for x in outcomes if x)
            upset_rate = underdog_wins / len(outcomes) if outcomes else 0
            matches_count = len(outcomes)

            wins, losses, stake, profit, ev_sum, odds_sum = 0, 0, 0.0, 0.0, 0.0, 0.0
            for o in by_league.get(league_id, []):
                won, ev, odds = o[0], o[1], o[2]
                if won:
                    wins += 1
                    profit += odds - 1
                else:
                    losses += 1
                    profit -= 1
                stake += 1
                ev_sum += ev
                odds_sum += odds

            roi = (profit / stake * 100) if stake > 0 else 0
            n_signals = len(by_league.get(league_id, []))
            avg_ev = ev_sum / n_signals if n_signals else 0
            avg_odds = odds_sum / n_signals if n_signals else 0

            session.execute(
                text("""
                    INSERT INTO league_performance (
                        league_id, matches, wins, losses, stake_total, profit_total,
                        roi_pct, avg_ev, avg_odds, upset_rate, underdog_wins, updated_at
                    ) VALUES (
                        :lid, :matches, :wins, :losses, :stake, :profit,
                        :roi, :avg_ev, :avg_odds, :upset_rate, :underdog_wins, NOW()
                    )
                    ON CONFLICT (league_id) DO UPDATE SET
                        matches = EXCLUDED.matches,
                        wins = EXCLUDED.wins,
                        losses = EXCLUDED.losses,
                        stake_total = EXCLUDED.stake_total,
                        profit_total = EXCLUDED.profit_total,
                        roi_pct = EXCLUDED.roi_pct,
                        avg_ev = EXCLUDED.avg_ev,
                        avg_odds = EXCLUDED.avg_odds,
                        upset_rate = EXCLUDED.upset_rate,
                        underdog_wins = EXCLUDED.underdog_wins,
                        updated_at = NOW()
                """),
                {
                    "lid": league_id,
                    "matches": matches_count,
                    "wins": wins,
                    "losses": losses,
                    "stake": stake,
                    "profit": profit,
                    "roi": roi,
                    "avg_ev": avg_ev,
                    "avg_odds": avg_odds,
                    "upset_rate": upset_rate,
                    "underdog_wins": underdog_wins,
                },
            )
        session.commit()
        return len(by_league)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
