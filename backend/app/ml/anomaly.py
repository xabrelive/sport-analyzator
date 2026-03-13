"""Anomaly detection: подозрительные/договорные матчи. Isolation Forest + heuristic fallback."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from app.ml.db import get_ml_session


@dataclass
class SuspiciousMatch:
    match_id: int
    score: float
    reason: str
    odds_shift: float
    comeback_flag: bool
    model_error: float


SUSPICIOUS_THRESHOLD = 0.65


def _odds_shift_score(odds_open_p1: float, odds_close_p1: float) -> float:
    """Massive odds shift: |open - close| > 0.7 → подозрительно."""
    if odds_open_p1 < 1e-9:
        return 0.0
    shift = abs(odds_close_p1 - odds_open_p1)
    if shift > 0.7:
        return min(1.0, 0.5 + (shift - 0.7))
    return min(1.0, shift / 0.7)


def _odds_crash_score(odds_open_p1: float, odds_close_p1: float) -> float:
    """Odds crash: падение > 40% за короткое время — почти всегда инсайд."""
    if odds_open_p1 < 1e-9:
        return 0.0
    drop = (odds_open_p1 - odds_close_p1) / odds_open_p1
    if drop > 0.4:
        return min(1.0, 0.6 + (drop - 0.4))
    return 0.0


def _reverse_line_score(odds_open_p1: float, odds_close_p1: float, p1_won: bool) -> float:
    """Reverse line: коэф падал на аутсайдера, но он проиграл."""
    if odds_open_p1 < 1e-9 or odds_close_p1 < 1e-9:
        return 0.0
    fav_open = odds_open_p1 < 1.9
    fav_close = odds_close_p1 < 1.9
    if fav_open and not fav_close and not p1_won:
        return 0.9
    if not fav_open and fav_close and p1_won:
        return 0.9
    return 0.0


def _set_pattern_score(sets: list[tuple[int, int]]) -> float:
    """Flip pattern: 11-2, 2-11, 11-3 — подозрительно."""
    if len(sets) < 2:
        return 0.0
    scores = [s[0] - s[1] for s in sets]
    alternations = sum(1 for i in range(1, len(scores)) if (scores[i] > 0) != (scores[i - 1] > 0))
    return min(1.0, alternations / (len(scores) - 1) * 1.5)


def _absurd_set_score(sets: list[tuple[int, int]]) -> float:
    """Absurd set scores: 11-2, 3-11, 11-2, 2-11 — очень подозрительно."""
    if len(sets) < 2:
        return 0.0
    blowout_margin = 8  # 11-2, 11-3
    absurd_count = 0
    for s in sets:
        a, b = s[0], s[1]
        if (a >= 11 and a - b >= blowout_margin) or (b >= 11 and b - a >= blowout_margin):
            absurd_count += 1
    if absurd_count >= 2 and alternations_from_sets(sets) >= 1:
        return min(1.0, 0.5 + absurd_count * 0.2)
    return absurd_count / max(len(sets), 1) * 0.5


def alternations_from_sets(sets: list[tuple[int, int]]) -> int:
    scores = [s[0] - s[1] for s in sets]
    return sum(1 for i in range(1, len(scores)) if (scores[i] > 0) != (scores[i - 1] > 0))


def _comeback_score(sets: list[tuple[int, int]], p1_won: bool) -> tuple[float, bool]:
    """Suspicious comeback: 0:2 → 3:2 при высоких live odds."""
    if len(sets) < 3:
        return 0.0, False
    p1_sets = sum(1 for s in sets if s[0] > s[1])
    p2_sets = sum(1 for s in sets if s[1] > s[0])
    first_two_p1 = sum(1 for s in sets[:2] if s[0] > s[1])
    first_two_p2 = sum(1 for s in sets[:2] if s[1] > s[0])
    comeback = (first_two_p1 == 0 and p1_sets == 3) or (first_two_p2 == 0 and p2_sets == 3)
    if comeback:
        return 0.8, True
    return 0.0, False


def _model_error_score(p_model: float, actual: int) -> float:
    """P_model=0.88 но результат противоположный."""
    if actual == 1:
        err = 1.0 - p_model
    else:
        err = p_model
    return min(1.0, err * 1.5)


def _point_diff_variance(sets: list[tuple[int, int]]) -> float:
    """Волатильность разницы очков по сетам. Высокая = чередование побед."""
    if len(sets) < 2:
        return 0.0
    diffs = [s[0] - s[1] for s in sets]
    mean = sum(diffs) / len(diffs)
    var = sum((x - mean) ** 2 for x in diffs) / len(diffs)
    return min(1.0, math.sqrt(var) / 15.0)  # нормализуем


def anomaly_features(
    odds_open_p1: float,
    odds_close_p1: float,
    sets: list[tuple[int, int]],
    p_model: float,
    p1_won: bool,
) -> list[float]:
    """Вектор фичей для Isolation Forest: odds_shift, set_pattern, model_error, comeback, point_diff_variance."""
    odds_shift = _odds_shift_score(odds_open_p1, odds_close_p1)
    set_pat = _set_pattern_score(sets)
    comeback_sc, _ = _comeback_score(sets, p1_won)
    model_err = _model_error_score(p_model, 1 if p1_won else 0)
    pt_var = _point_diff_variance(sets)
    return [odds_shift, set_pat, model_err, comeback_sc, pt_var]


def compute_suspicion_score_isolation_forest(
    features_vec: list[float],
    model: Any | None = None,
) -> tuple[float, str]:
    """Isolation Forest: anomaly score. model=None → fallback на heuristic."""
    if model is not None and hasattr(model, "decision_function"):
        try:
            import numpy as np
            X = np.array([features_vec]).reshape(1, -1)
            score = -model.decision_function(X)[0]
            score_norm = min(1.0, max(0.0, (score + 0.5) / 1.5))
            return score_norm, f"isolation_forest={score_norm:.2f}"
        except Exception:
            pass
    return 0.5, "isolation_forest_fallback"


def compute_suspicion_score(
    odds_open_p1: float,
    odds_close_p1: float,
    sets: list[tuple[int, int]],
    p_model: float,
    p1_won: bool,
) -> tuple[float, str, float, bool, float]:
    """suspicious_score = odds_shift + odds_crash + absurd_sets + comeback + model_error + reverse_line."""
    odds_shift = _odds_shift_score(odds_open_p1, odds_close_p1)
    odds_crash = _odds_crash_score(odds_open_p1, odds_close_p1)
    reverse = _reverse_line_score(odds_open_p1, odds_close_p1, p1_won)
    set_pat = _set_pattern_score(sets)
    absurd_sets = _absurd_set_score(sets)
    comeback_sc, comeback_flag = _comeback_score(sets, p1_won)
    model_err = _model_error_score(p_model, 1 if p1_won else 0)

    total = (
        0.2 * odds_shift + 0.2 * odds_crash + 0.15 * reverse
        + 0.15 * set_pat + 0.15 * absurd_sets + 0.1 * comeback_sc + 0.05 * model_err
    )
    total = min(1.0, total * 1.2)
    reason = f"odds_shift={odds_shift:.2f} odds_crash={odds_crash:.2f} absurd_sets={absurd_sets:.2f} reverse={reverse:.2f} comeback={comeback_flag} model_err={model_err:.2f}"
    return total, reason, odds_shift, comeback_flag, model_err


def save_suspicious(match_id: int, score: float, reason: str, odds_shift: float = 0, comeback: bool = False, model_error: float = 0) -> None:
    session = get_ml_session()
    try:
        existing = session.execute(
            text("SELECT id FROM suspicious_matches WHERE match_id = :mid"),
            {"mid": match_id},
        ).fetchone()
        if existing:
            try:
                session.execute(
                    text("""
                        UPDATE suspicious_matches SET score = :score, reason = :reason,
                            odds_shift = :odds_shift, comeback_flag = :comeback, model_error = :model_err
                        WHERE match_id = :mid
                    """),
                    {"mid": match_id, "score": score, "reason": reason, "odds_shift": odds_shift, "comeback": comeback, "model_err": model_error},
                )
            except Exception:
                session.execute(
                    text("UPDATE suspicious_matches SET score = :score, reason = :reason WHERE match_id = :mid"),
                    {"mid": match_id, "score": score, "reason": reason},
                )
        else:
            try:
                session.execute(
                    text("""
                        INSERT INTO suspicious_matches (match_id, score, reason, odds_shift, comeback_flag, model_error)
                        VALUES (:mid, :score, :reason, :odds_shift, :comeback, :model_err)
                    """),
                    {"mid": match_id, "score": score, "reason": reason, "odds_shift": odds_shift, "comeback": comeback, "model_err": model_error},
                )
            except Exception:
                session.execute(
                    text("INSERT INTO suspicious_matches (match_id, score, reason) VALUES (:mid, :score, :reason)"),
                    {"mid": match_id, "score": score, "reason": reason},
                )
        session.commit()
    finally:
        session.close()


def fit_anomaly_model(limit: int = 10_000) -> Any | None:
    """Обучает Isolation Forest на исторических матчах. Сохраняет в ML_MODEL_DIR."""
    import os
    from pathlib import Path
    try:
        from sklearn.ensemble import IsolationForest
        import numpy as np
        import joblib
    except ImportError:
        return None
    session = get_ml_session()
    try:
        from app.ml.model_trainer import load_models, predict_proba, FEATURE_COLS
        _, model_set1, _, _ = load_models()
        col_order = [
            "elo_diff", "form_diff", "fatigue_diff", "h2h_diff", "winrate_10_diff", "odds_diff", "h2h_count",
            "avg_sets_per_match_diff", "sets_over35_rate_diff", "streak_score",
            "minutes_since_last_match_diff", "dominance_diff",
            "std_points_diff_last10_p1", "std_points_diff_last10_p2",
            "log_odds_ratio", "implied_prob_p1", "market_margin",
            "momentum_today_diff", "set1_strength_diff", "comeback_rate_diff",
        ]
        rows = session.execute(
            text("""
                SELECT m.id, m.score_sets_p1, m.score_sets_p2,
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
            {"lim": limit},
        ).fetchall()
        odds_rows = session.execute(text("SELECT match_id, odds_p1, odds_p2 FROM odds")).fetchall()
        odds_map = {r[0]: (float(r[1] or 1.9), float(r[2] or 1.9)) for r in odds_rows}
        X_list = []
        for r in rows:
            match_id, s1, s2 = r[0], r[1], r[2]
            p1_won = s1 > s2
            o1, o2 = odds_map.get(match_id, (1.9, 1.9))
            odds_open = float(o1 or 1.9)
            odds_close = float(o1 or 1.9)
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
            X_list.append(anomaly_features(odds_open, odds_close, sets, p_model, p1_won))
        if len(X_list) < 100:
            return None
        X = np.array(X_list)
        model = IsolationForest(contamination=0.1, random_state=42, n_estimators=100)
        model.fit(X)
        model_dir = Path(os.environ.get("ML_MODEL_DIR", "/tmp/pingwin_ml_models"))
        model_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, model_dir / "anomaly_isolation_forest.joblib")
        return model
    finally:
        session.close()


def load_anomaly_model() -> Any | None:
    """Загружает Isolation Forest из диска."""
    import os
    from pathlib import Path
    try:
        import joblib
        path = Path(os.environ.get("ML_MODEL_DIR", "/tmp/pingwin_ml_models")) / "anomaly_isolation_forest.joblib"
        if path.exists():
            return joblib.load(path)
    except Exception:
        pass
    return None


def is_match_suspicious(match_id: int) -> tuple[bool, float, str]:
    """Проверяет, есть ли матч в suspicious_matches. Возвращает (is_suspicious, score, reason)."""
    session = get_ml_session()
    try:
        row = session.execute(
            text("SELECT score, reason FROM suspicious_matches WHERE match_id = :mid"),
            {"mid": match_id},
        ).fetchone()
        if row:
            return True, float(row[0]), str(row[1] or "")
        return False, 0.0, ""
    finally:
        session.close()
