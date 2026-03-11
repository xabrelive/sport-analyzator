"""Local deterministic scorer for forecast V2."""
from __future__ import annotations

from dataclasses import dataclass
from math import exp


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + exp(-x))


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


def score_match_features(features: dict) -> ScoredForecast:
    """Compute calibrated probabilities from snapshot features."""
    form_delta = float(features.get("form_delta") or 0.0)
    h2h_home_wr = float(features.get("h2h_home_wr") or 0.5)
    fatigue_delta = float(features.get("fatigue_delta") or 0.0)
    home_samples = float(features.get("home_samples") or 0.0)
    away_samples = float(features.get("away_samples") or 0.0)
    h2h_count = float(features.get("h2h_count") or 0.0)

    # Blend model signal: форма + очные встречи + усталость (без линии букмекера)
    model_signal = (
        1.9 * form_delta
        + 0.9 * (h2h_home_wr - 0.5)
        + 0.008 * fatigue_delta
    )
    p_home = _sigmoid(model_signal)
    p_away = 1.0 - p_home

    set_adjust = min(0.08, abs(form_delta) * 0.2 + h2h_count * 0.002)
    p_home_set1 = max(0.05, min(0.95, p_home + set_adjust * 0.5))
    p_away_set1 = 1.0 - p_home_set1
    p_home_set2 = max(0.05, min(0.95, p_home + set_adjust * 0.3))
    p_away_set2 = 1.0 - p_home_set2

    sample_score = min(1.0, (home_samples + away_samples) / 50.0)
    h2h_score = min(1.0, h2h_count / 12.0)
    quality_score = round(0.65 * sample_score + 0.35 * h2h_score, 4)

    factors = [
        {
            "factor_key": "form_delta",
            "factor_label": "Форма игроков за 90 дней",
            "factor_value": f"{form_delta:+.3f}",
            "contribution": round(1.9 * form_delta, 4),
        },
        {
            "factor_key": "h2h_home_wr",
            "factor_label": "Очные встречи между игроками",
            "factor_value": f"{h2h_home_wr:.2f}",
            "contribution": round(0.9 * (h2h_home_wr - 0.5), 4),
        },
        {
            "factor_key": "fatigue_delta",
            "factor_label": "Разница в усталости",
            "factor_value": f"{fatigue_delta:+.2f}",
            "contribution": round(0.008 * fatigue_delta, 4),
        },
    ]
    for idx, f in enumerate(factors, start=1):
        f["rank"] = idx
        f["direction"] = "home" if float(f["contribution"]) > 0 else "away"

    return ScoredForecast(
        p_home_match=round(p_home, 6),
        p_away_match=round(p_away, 6),
        p_home_set1=round(p_home_set1, 6),
        p_away_set1=round(p_away_set1, 6),
        p_home_set2=round(p_home_set2, 6),
        p_away_set2=round(p_away_set2, 6),
        quality_score=quality_score,
        factors=factors,
    )
