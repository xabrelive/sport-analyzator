"""ML-скоринг для прематч: только XGBoost/LightGBM + Monte Carlo."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.config import settings

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
    regime_bucket: str | None = None  # "rookie"|"low"|"mid"|"pro" при использовании bucket-модели ML v2


def score_match_for_forecast(event: "TableTennisLineEvent") -> tuple[ScoredForecast, bool] | None:
    """Скор для прематча: только ML. При неудаче (игроки не в ML-БД) — None.

    Returns:
        (ScoredForecast, use_ml: bool) или None
    """
    try:
        if str(getattr(settings, "ml_engine", "v1")).lower() == "v2":
            from app.ml_v2.inference import predict_for_upcoming_v2

            pred_v2 = predict_for_upcoming_v2(
                home_id=event.home_id,
                away_id=event.away_id,
                league_id=event.league_id or "",
                odds_p1=float(event.odds_1 or 1.9),
                odds_p2=float(event.odds_2 or 1.9),
                start_time=event.starts_at,
            )
            if pred_v2 is None:
                logger.info("ML v2 returned None for event %s (home=%s away=%s) — проверьте: модели в ML_MODEL_DIR, игроки в ML-БД", event.id, getattr(event, "home_id", ""), getattr(event, "away_id", ""))
                return None
            return (
                ScoredForecast(
                    p_home_match=round(pred_v2.p_match, 6),
                    p_away_match=round(1.0 - pred_v2.p_match, 6),
                    p_home_set1=round(pred_v2.p_set1, 6),
                    p_away_set1=round(1.0 - pred_v2.p_set1, 6),
                    p_home_set2=round(pred_v2.p_set2, 6),
                    p_away_set2=round(1.0 - pred_v2.p_set2, 6),
                    quality_score=float(pred_v2.quality_score),
                    factors=list(pred_v2.factors[:5]),
                    regime_bucket=pred_v2.regime_bucket,
                ),
                True,
            )

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
        logger.warning("ML scoring failed for event %s (home=%s away=%s): %s", event.id, getattr(event, "home_id", ""), getattr(event, "away_id", ""), e)
        return None


def score_match_for_forecast_nn(event: "TableTennisLineEvent") -> tuple[ScoredForecast, bool] | None:
    """NN-скоринг для прематча (MLP в ML v2 feature space)."""
    try:
        from app.ml_v2.inference import predict_for_upcoming_nn_v2

        pred = predict_for_upcoming_nn_v2(
            home_id=event.home_id,
            away_id=event.away_id,
            league_id=event.league_id or "",
            odds_p1=float(event.odds_1 or 1.9),
            odds_p2=float(event.odds_2 or 1.9),
            start_time=event.starts_at,
        )
        if pred is None:
            return None
        return (
            ScoredForecast(
                p_home_match=round(pred.p_match, 6),
                p_away_match=round(1.0 - pred.p_match, 6),
                p_home_set1=round(pred.p_set1, 6),
                p_away_set1=round(1.0 - pred.p_set1, 6),
                p_home_set2=round(pred.p_set2, 6),
                p_away_set2=round(1.0 - pred.p_set2, 6),
                quality_score=float(pred.quality_score),
                factors=list(pred.factors[:5]),
            ),
            True,
        )
    except Exception as e:
        logger.warning(
            "NN scoring failed for event %s (home=%s away=%s): %s",
            event.id,
            getattr(event, "home_id", ""),
            getattr(event, "away_id", ""),
            e,
        )
        return None
