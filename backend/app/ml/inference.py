"""Inference: p_point → Monte Carlo (основной путь). XGB+аналитика — fallback."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.ml.feature_engine import FeatureEngine, MatchFeatures
from app.ml.model_trainer import FEATURE_COLS
from app.ml.probability import p_point_from_features, run_monte_carlo
from app.ml.value_detector import ValueDetector, expected_value
from app.ml.signal_filter import SignalFilter, confidence_score


@dataclass
class MLPrediction:
    p_match: float
    p_set1: float
    p_set2: float
    p_point: float  # legacy, для совместимости
    features: MatchFeatures | None
    model_used: bool
    value_signals: list[dict]
    suspicious: bool = False
    suspicious_score: float = 0.0
    suspicious_reason: str = ""


def _feat_dict(features: MatchFeatures) -> dict[str, float]:
    """Словарь фичей для модели (базовые + v3 сильные фичи)."""
    base = {
        "elo_diff": features.elo_diff,
        "form_diff": features.form_diff,
        "fatigue_diff": features.fatigue_diff,
        "h2h_diff": features.h2h_diff,
        "winrate_10_diff": features.winrate_10_diff,
        "odds_diff": features.odds_diff,
        "h2h_count": float(features.h2h_count),
        "avg_sets_per_match_diff": features.avg_sets_per_match_diff,
        "sets_over35_rate_diff": features.sets_over35_rate_diff,
        "streak_score": features.streak_score,
        "minutes_since_last_match_diff": features.minutes_since_last_match_diff,
        "dominance_diff": features.dominance_diff,
        "std_points_diff_last10_p1": features.std_points_diff_last10_p1,
        "std_points_diff_last10_p2": features.std_points_diff_last10_p2,
        "log_odds_ratio": features.log_odds_ratio,
        "implied_prob_p1": features.implied_prob_p1,
        "market_margin": features.market_margin,
        "momentum_today_diff": features.momentum_today_diff,
        "set1_strength_diff": features.set1_strength_diff,
        "comeback_rate_diff": features.comeback_rate_diff,
        "dominance_last_50_diff": features.dominance_last_50_diff,
        "fatigue_index_diff": features.fatigue_index_diff,
        "fatigue_ratio": features.fatigue_ratio,
        "minutes_to_match": features.minutes_to_match,
        "odds_shift_p1": features.odds_shift_p1,
        "odds_shift_p2": features.odds_shift_p2,
        "elo_volatility_diff": getattr(features, "elo_volatility_diff", 0.0),
        "daily_performance_trend_diff": features.daily_performance_trend_diff,
        "dominance_trend_diff": getattr(features, "dominance_trend_diff", 0.0),
        "style_clash": getattr(features, "style_clash", 0.0),
    }
    return {c: base.get(c, 0.0) for c in FEATURE_COLS}


def predict_for_upcoming(
    home_id: str,
    away_id: str,
    league_id: str,
    odds_p1: float,
    odds_p2: float,
    start_time: Any,
    match_id: int | None = None,
    line_age_seconds: float | None = None,
    as_of_time: Any | None = None,
    odds_open_p1: float | None = None,
    odds_open_p2: float | None = None,
) -> MLPrediction | None:
    """Предсказание: XGBoost → P_set, аналитический P_match."""
    from datetime import datetime
    from app.ml.db import get_ml_session
    from sqlalchemy import text

    session = get_ml_session()
    try:
        p1_row = session.execute(
            text("SELECT id FROM players WHERE external_id = :eid"),
            {"eid": home_id},
        ).fetchone()
        p2_row = session.execute(
            text("SELECT id FROM players WHERE external_id = :eid"),
            {"eid": away_id},
        ).fetchone()
        if not p1_row or not p2_row:
            return None
        p1_id, p2_id = p1_row[0], p2_row[0]

        if isinstance(start_time, str):
            from datetime import timezone
            try:
                start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            except ValueError:
                start_time = datetime.now(timezone.utc)
        elif start_time is None:
            from datetime import timezone
            start_time = datetime.now(timezone.utc)

        from datetime import timezone
        ref = as_of_time if as_of_time else datetime.now(timezone.utc)
        if isinstance(ref, str):
            try:
                ref = datetime.fromisoformat(ref.replace("Z", "+00:00"))
            except ValueError:
                ref = datetime.now(timezone.utc)

        engine = FeatureEngine()
        features = engine.compute_for_match(
            match_id or 0,
            p1_id,
            p2_id,
            start_time,
            odds_p1 or 1.9,
            odds_p2 or 1.9,
            league_id or "",
            as_of_time=ref,
            odds_open_p1=odds_open_p1,
            odds_open_p2=odds_open_p2,
        )
        if not features:
            return None

        feat_dict = _feat_dict(features)

        # Приоритет: set_model (tree) → p_point_model (logistic) → ручная формула
        # XGBoost predict не thread-safe — блокируем для GPU/CPU
        p_match = p_set1 = p_set2 = 0.5
        mc = None
        try:
            from app.ml.model_trainer import load_models, predict_proba
            _, _, set_model, p_point_model = load_models()
            if set_model is not None:
                p_set = predict_proba(set_model, feat_dict)
                mc = run_monte_carlo(p_set=p_set, n_sims=20_000)
                p_match, p_set1, p_set2 = mc.p_match, mc.p_set1, mc.p_set2
            elif p_point_model is not None:
                p_set = predict_proba(p_point_model, feat_dict)
                mc = run_monte_carlo(p_set=p_set, n_sims=20_000)
                p_match, p_set1, p_set2 = mc.p_match, mc.p_set1, mc.p_set2
        except Exception:
            pass
        if mc is None or p_match == 0.5:
            p_point = p_point_from_features(
                features.elo_diff,
                features.form_diff,
                features.fatigue_diff,
                features.h2h_diff,
                momentum_diff=features.momentum_today_diff,
                fatigue_decay_diff=features.fatigue_decay_diff,
                hours_since_last_h2h=getattr(features, "hours_since_last_h2h", 999.0),
                matchup_strength_diff=getattr(features, "matchup_strength_diff", 0.0),
            )
            mc = run_monte_carlo(p_point=p_point, n_sims=20_000)
            p_match, p_set1, p_set2 = mc.p_match, mc.p_set1, mc.p_set2
        p_match = mc.p_match
        p_set1 = mc.p_set1
        p_set2 = mc.p_set2
        model_used = True

        detector = ValueDetector(min_ev=0.08, min_odds=1.6, max_odds=2.6)
        values = detector.detect(p_match, p_set1, p_set2, odds_p1, odds_p2)
        filter_obj = SignalFilter()
        perf_volatility = max(0.3, 1.0 - (features.std_points_diff_last10_p1 + features.std_points_diff_last10_p2) / 20.0)
        league_penalty = 0.0
        # Early line inefficiency: line_age < 90 sec → коэффициенты часто ошибочные, больше value
        early_line_boost = 0.1 if (line_age_seconds is not None and line_age_seconds < 90) else 0.0
        if features.league_id:
            from app.ml.league_performance import league_confidence_reduction
            league_penalty = league_confidence_reduction(features.league_id)
        conf = confidence_score(
            features.sample_size,
            form_consistency=perf_volatility,
            league_penalty=league_penalty,
            market_agreement=0.5 + early_line_boost,
        )
        player_std_sum = features.std_points_diff_last10_p1 + features.std_points_diff_last10_p2
        elo_vol_sum = getattr(features, "elo_volatility_p1", 0) + getattr(features, "elo_volatility_p2", 0)
        if elo_vol_sum > 50:
            perf_volatility *= max(0.5, 1.0 - (elo_vol_sum - 50) / 100.0)
        signals = []
        for v in values:
            if filter_obj.passes(
                v, features.sample_size, conf,
                league_id=features.league_id or None,
                player_std_sum=player_std_sum,
                daily_performance_trend_p1=getattr(features, "daily_performance_trend_p1", None),
                daily_performance_trend_p2=getattr(features, "daily_performance_trend_p2", None),
                matches_played_p1=features.matches_played_p1,
                matches_played_p2=features.matches_played_p2,
            ):
                signals.append({
                    "market": v.market,
                    "side": v.side,
                    "odds": v.odds,
                    "probability": v.probability,
                    "ev": v.expected_value,
                    "kelly_fraction": v.kelly_fraction,
                    "bet_size_fraction": getattr(v, "bet_size_fraction", v.kelly_fraction * 0.25),
                    "confidence": conf,
                })

        p_point = 0.5  # legacy, не используется
        suspicious, susp_score, susp_reason = False, 0.0, ""
        if match_id:
            from app.ml.anomaly import is_match_suspicious
            ml_match = session.execute(
                text("SELECT id FROM matches WHERE external_id = :eid"),
                {"eid": str(match_id)},
            ).fetchone()
            if ml_match:
                suspicious, susp_score, susp_reason = is_match_suspicious(ml_match[0])
        return MLPrediction(
            p_match=p_match,
            p_set1=p_set1,
            p_set2=p_set2,
            p_point=p_point,
            features=features,
            model_used=model_used,
            value_signals=signals,
            suspicious=suspicious,
            suspicious_score=susp_score,
            suspicious_reason=susp_reason,
        )
    finally:
        session.close()
