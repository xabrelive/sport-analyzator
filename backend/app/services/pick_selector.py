"""Pick selection logic for forecast V2."""
from __future__ import annotations

from dataclasses import dataclass

from app.services.ml_scorer import ScoredForecast


@dataclass
class SelectedPick:
    market: str  # match|set1|set2
    side: str  # home|away
    probability_pct: float
    edge_pct: float
    confidence_score: float
    odds_used: float
    forecast_text: str
    quality_tier: str


def _quality_tier(score: float) -> str:
    if score >= 0.75:
        return "A"
    if score >= 0.55:
        return "B"
    if score >= 0.35:
        return "C"
    return "D"


def select_pick(
    scored: ScoredForecast,
    odds_home: float | None,
    odds_away: float | None,
    min_odds: float,
    min_confidence_pct: float,
    min_edge_pct: float,
) -> SelectedPick | None:
    oh = float(odds_home or 0.0)
    oa = float(odds_away or 0.0)
    if oh < min_odds and oa < min_odds:
        return None

    candidates: list[SelectedPick] = []

    def _add(market: str, side: str, p: float, odds: float, label: str):
        if odds < min_odds:
            return
        implied = (1.0 / odds) if odds > 1e-9 else 0.0
        edge = (p - implied) * 100.0
        confidence = p * 100.0
        if confidence < min_confidence_pct or edge < min_edge_pct:
            return
        candidates.append(
            SelectedPick(
                market=market,
                side=side,
                probability_pct=round(confidence, 2),
                edge_pct=round(edge, 2),
                confidence_score=round(confidence * (0.4 + 0.6 * scored.quality_score), 2),
                odds_used=round(odds, 3),
                forecast_text=f"{label} ({round(confidence, 1)}%)",
                quality_tier=_quality_tier(scored.quality_score),
            )
        )

    _add("match", "home", scored.p_home_match, oh, "П1 победа в матче")
    _add("match", "away", scored.p_away_match, oa, "П2 победа в матче")
    _add("set1", "home", scored.p_home_set1, oh, "П1 выиграет 1-й сет")
    _add("set1", "away", scored.p_away_set1, oa, "П2 выиграет 1-й сет")
    _add("set2", "home", scored.p_home_set2, oh, "П1 выиграет 2-й сет")
    _add("set2", "away", scored.p_away_set2, oa, "П2 выиграет 2-й сет")

    if not candidates:
        return None

    def _value_score(p: SelectedPick) -> float:
        """
        Оцениваем сигнал по ожидаемой выгоде:
        - edge (value) важнее просто вероятности,
        - даём бонус за более крупный кф (но без перекоса в заведомо лютые андердоги).
        """
        # Нормируем odds в зоне 1.6–2.5 как «сладкое место»
        odds_bonus = 0.0
        if p.odds_used >= 1.6:
            # до 2.5 растёт бонус, дальше — плато
            capped = min(p.odds_used, 2.5)
            odds_bonus = (capped - 1.6) * 1.5  # максимум ~1.35
        return p.edge_pct + odds_bonus

    candidates.sort(
        key=lambda x: (
            x.quality_tier,           # A/B/C/D
            _value_score(x),          # сначала лучшие по value и кф
            x.confidence_score,       # затем по уверенности
            0 if x.market == "match" else 1,  # матчевые чуть выше сетов
        ),
        reverse=True,
    )
    return candidates[0]
