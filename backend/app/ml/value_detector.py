"""Value Detector: EV = P_model × Odds - 1."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ValueResult:
    market: str
    side: str
    odds: float
    probability: float
    expected_value: float
    implied_market: float
    kelly_fraction: float = 0.0  # full Kelly: (P*odds-1)/(odds-1), capped [0, 0.25]
    bet_size_fraction: float = 0.0  # 0.25 Kelly: stake = bankroll * bet_size_fraction


def p_market_from_odds(odds: float) -> float:
    """Имплицитная вероятность букмекера: P = 1/Odds (без маржи)."""
    if odds < 1e-9:
        return 0.5
    return 1.0 / odds


def expected_value(probability: float, odds: float) -> float:
    """EV = P × Odds - 1."""
    return probability * odds - 1.0


def kelly_fraction(probability: float, odds: float) -> float:
    """Full Kelly: k = (P*odds - 1) / (odds - 1). Ограничиваем [0, 0.25]."""
    if odds <= 1.0:
        return 0.0
    k = (probability * odds - 1.0) / (odds - 1.0)
    return max(0.0, min(0.25, k))


def bet_size_quarter_kelly(probability: float, odds: float) -> float:
    """0.25 Kelly: stake = bankroll * 0.25 * full_kelly."""
    k = (probability * odds - 1.0) / (odds - 1.0) if odds > 1.0 else 0.0
    return max(0.0, min(0.25, 0.25 * k))


def bet_size_kelly(bankroll: float, probability: float, odds: float, fraction: float = 0.25) -> float:
    """bet_size = bankroll * kelly * fraction (fraction=0.25 уменьшает риск)."""
    k = kelly_fraction(probability, odds)
    return bankroll * k * fraction


class ValueDetector:
    """Поиск value ставок: EV > 0."""

    def __init__(self, min_ev: float = 0.08, min_odds: float = 1.6, max_odds: float = 2.6):
        self.min_ev = min_ev
        self.min_odds = min_odds
        self.max_odds = max_odds

    def detect(
        self,
        p_match: float,
        p_set1: float,
        p_set2: float,
        odds_p1: float,
        odds_p2: float,
    ) -> list[ValueResult]:
        """Возвращает список value-ставок. Золотая зона: 1.6–2.6."""
        results = []
        for market, p in [("match", p_match), ("set1", p_set1), ("set2", p_set2)]:
            for side, prob, odds in [("p1", p, odds_p1), ("p2", 1 - p, odds_p2)]:
                if odds < self.min_odds or odds > self.max_odds:
                    continue
                ev = expected_value(prob, odds)
                if ev >= self.min_ev:
                    implied = p_market_from_odds(odds)
                    kelly = kelly_fraction(prob, odds)
                    bet_frac = bet_size_quarter_kelly(prob, odds)
                    results.append(
                        ValueResult(
                            market=market,
                            side=side,
                            odds=odds,
                            probability=prob,
                            expected_value=ev,
                            implied_market=implied,
                            kelly_fraction=kelly,
                            bet_size_fraction=bet_frac,
                        )
                    )
        return results
