"""ML-скоринг для прематч: только XGBoost/LightGBM + Monte Carlo."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.table_tennis_line_event import TableTennisLineEvent

logger = logging.getLogger(__name__)


@dataclass
class ScoredForecast:
    p_home_match: float
    p_away_match: float
    p_home_set1: float
    p_away_set1: float
    p_home_set2: float
    p_away_set2: float
    quality_score: float
    factors: list[dict]
    suspicious: bool = False
    suspicious_score: float = 0.0
    suspicious_reason: str = ""


def score_match_for_forecast(event: "TableTennisLineEvent") -> tuple[ScoredForecast, bool] | None:
    """Скор для прематча: только ML. При неудаче (игроки не в ML-БД) — None.

    Returns:
        (ScoredForecast, use_ml: bool) или None
    """
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
            logger.debug("ML returned None for %s (players not in ML DB)", event.id)
            return None

        sample_size = pred.features.sample_size if pred.features else 0
        sample_score = min(1.0, sample_size / 60.0)
        h2h_score = min(1.0, (pred.features.h2h_count if pred.features else 0) / 12.0)
        quality_score = round(0.65 * sample_score + 0.35 * h2h_score, 4)

        factors = []
        if pred.features:
            f = pred.features
            factors = [
                {"factor_key": "elo_diff", "factor_label": "Разница Elo", "factor_value": f"{f.elo_diff:+.0f}", "contribution": f.elo_diff / 100, "rank": 1, "direction": "home" if f.elo_diff > 0 else "away"},
                {"factor_key": "form_diff", "factor_label": "Форма (5/10 матчей)", "factor_value": f"{f.form_diff:+.3f}", "contribution": f.form_diff * 2, "rank": 2, "direction": "home" if f.form_diff > 0 else "away"},
                {"factor_key": "fatigue_diff", "factor_label": "Усталость за 24ч", "factor_value": f"{f.fatigue_diff:+.1f}", "contribution": f.fatigue_diff * 0.01, "rank": 3, "direction": "home" if f.fatigue_diff < 0 else "away"},
                {"factor_key": "h2h_diff", "factor_label": "Очные встречи", "factor_value": f"{f.h2h_p1_wr:.2f}" if f.h2h_count else "—", "contribution": (f.h2h_p1_wr - 0.5) * 1.5 if f.h2h_count else 0, "rank": 4, "direction": "home" if (f.h2h_p1_wr or 0.5) > 0.5 else "away"},
            ]

        return (
            ScoredForecast(
                p_home_match=round(pred.p_match, 6),
                p_away_match=round(1.0 - pred.p_match, 6),
                p_home_set1=round(pred.p_set1, 6),
                p_away_set1=round(1.0 - pred.p_set1, 6),
                p_home_set2=round(pred.p_set2, 6),
                p_away_set2=round(1.0 - pred.p_set2, 6),
                quality_score=quality_score,
                factors=factors[:5],
                suspicious=getattr(pred, "suspicious", False),
                suspicious_score=getattr(pred, "suspicious_score", 0.0),
                suspicious_reason=getattr(pred, "suspicious_reason", ""),
            ),
            pred.model_used,
        )
    except Exception as e:
        logger.debug("ML scoring failed for %s: %s", event.id, e)
        return None
