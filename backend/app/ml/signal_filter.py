"""Signal Filter: edge > 0.05, EV > 0.08, odds 1.5–3.0, fatigue_ratio < 2, league_upset_rate < 40%.

После фильтрации остаётся 8–15% матчей, ROI резко растёт."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.ml.value_detector import ValueResult


@dataclass
class FilterConfig:
    min_probability: float = 0.72
    min_ev: float = 0.08  # EV > 0.08
    min_edge: float = 0.05  # edge = P_model - P_market
    min_confidence: float = 0.7
    min_sample_size: int = 50
    min_player_matches: int = 100  # новые игроки ломают модель
    min_odds: float = 1.5  # золотая зона 1.5–3.0
    max_odds: float = 3.0
    require_league_roi: bool = True
    max_fatigue_ratio: float = 2.0  # fatigue_ratio >= 2 → один игрок сильно уставший, скип
    max_league_upset_rate: float = 0.4  # league_upset_rate > 40% → нестабильная лига, скип


def confidence_score(
    sample_size: int,
    model_stability: float = 0.8,
    form_consistency: float = 0.8,
    market_agreement: float = 0.5,
    league_penalty: float = 0.0,
) -> float:
    """confidence = 0.4×sample + 0.3×stability + 0.2×form + 0.1×market - league_penalty."""
    sample_norm = min(1.0, sample_size / 60.0)
    base = 0.4 * sample_norm + 0.3 * model_stability + 0.2 * form_consistency + 0.1 * market_agreement
    return max(0.0, base - league_penalty)


class SignalFilter:
    """Фильтр сигналов: league_roi > 5%, matches > 300, upset_rate < 40%."""

    def __init__(self, config: FilterConfig | None = None):
        self.config = config or FilterConfig()

    def passes(
        self,
        value: ValueResult,
        sample_size: int,
        confidence: float,
        league_id: str | None = None,
        player_std_sum: float | None = None,
        daily_performance_trend_p1: float | None = None,
        daily_performance_trend_p2: float | None = None,
        matches_played_p1: int | None = None,
        matches_played_p2: int | None = None,
        fatigue_ratio: float | None = None,
        league_upset_rate: float | None = None,
    ) -> bool:
        """Проверяет, проходит ли сигнал фильтр.
        Обязательно: edge > 0.05, EV > 0.08, odds 1.5–3.0, fatigue_ratio < 2, league_upset_rate < 40%."""
        if value.probability < self.config.min_probability:
            return False
        if value.expected_value < self.config.min_ev:
            return False
        edge = value.probability - (1.0 / value.odds) if value.odds > 1e-9 else 0.0
        if edge < self.config.min_edge:
            return False
        if value.odds < self.config.min_odds or value.odds > self.config.max_odds:
            return False
        if fatigue_ratio is not None and fatigue_ratio >= self.config.max_fatigue_ratio:
            return False  # один игрок сильно уставший — нестабильный сигнал
        if league_upset_rate is not None and league_upset_rate > self.config.max_league_upset_rate:
            return False  # лига с >40% апсетов — нестабильная, скип

        conf = confidence
        if daily_performance_trend_p1 is not None and daily_performance_trend_p2 is not None:
            trend = daily_performance_trend_p1 if value.side == "p1" else daily_performance_trend_p2
            if trend < -0.3:
                conf *= 0.7  # игрок начал сливать
        if player_std_sum is not None and player_std_sum > 15.0:
            conf *= max(0.5, 1.0 - (player_std_sum - 15.0) / 30.0)
        if conf < self.config.min_confidence:
            return False
        if sample_size < self.config.min_sample_size:
            return False
        if matches_played_p1 is not None and matches_played_p2 is not None:
            if min(matches_played_p1, matches_played_p2) < self.config.min_player_matches:
                return False
        if self.config.require_league_roi and league_id:
            from app.ml.league_performance import league_passes_filter
            if not league_passes_filter(league_id):
                return False
        return True
