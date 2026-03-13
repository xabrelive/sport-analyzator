"""Probability Engine: Monte Carlo симуляция сетов и матчей."""
from __future__ import annotations

import random
from dataclasses import dataclass
from math import exp

import numpy as np


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + exp(-x))


def p_point_from_features(
    elo_diff: float,
    form_diff: float,
    fatigue_diff: float,
    h2h_diff: float,
    momentum_diff: float = 0.0,
    fatigue_decay_diff: float | None = None,
    hours_since_last_h2h: float = 999.0,
    matchup_strength_diff: float = 0.0,
) -> float:
    """Вероятность выиграть очко. point→set→match (не match напрямую).
    logit = 0.004*elo + 1.8*form + 0.9*momentum + 0.5*fatigue + 0.6*h2h.
    hours_since_last_h2h < 24 → repeat opponent, сильнее вес H2H."""
    logit = 0.004 * elo_diff
    logit += 1.8 * form_diff
    logit += 0.9 * momentum_diff
    fatigue = fatigue_decay_diff if fatigue_decay_diff is not None else fatigue_diff
    logit += 0.5 * (fatigue / 25.0)  # fatigue_decay: 10/5/2 → ~0-50
    h2h_mult = 1.0 + max(0.0, (24.0 - min(24.0, hours_since_last_h2h)) / 24.0) * 0.5  # 1.0–1.5
    logit += 0.6 * (h2h_diff * 2.0) * h2h_mult  # h2h_diff в [-0.5,0.5] -> [-1,1]
    logit += 0.4 * (matchup_strength_diff * 2.0)  # matchup_strength: h2h weighted by recency
    return sigmoid(logit)


def _simulate_set(p_point: float, rng: random.Random | None = None) -> bool:
    """Симулирует один сет до 11 с разницей 2. Возвращает True если P1 выиграл."""
    rng = rng or random.Random()
    a, b = 0, 0
    while True:
        if a >= 11 and a - b >= 2:
            return True
        if b >= 11 and b - a >= 2:
            return False
        if rng.random() < p_point:
            a += 1
        else:
            b += 1


def _simulate_match(p_set: float, sets_to_win: int = 3, rng: random.Random | None = None) -> tuple[int, int]:
    """Симулирует матч до sets_to_win сетов. Возвращает (score_p1, score_p2)."""
    rng = rng or random.Random()
    s1, s2 = 0, 0
    while s1 < sets_to_win and s2 < sets_to_win:
        if rng.random() < p_set:
            s1 += 1
        else:
            s2 += 1
    return s1, s2


@dataclass
class MonteCarloResult:
    p_match: float
    p_set1: float
    p_set2: float
    p_3_0: float
    p_3_1: float
    p_3_2: float
    p_total_over_35: float
    p_total_under_35: float


class MonteCarloSimulator:
    """Monte Carlo симуляция: 50k итераций (рекомендуется для TT)."""

    DEFAULT_N_SIMS = 50_000

    def __init__(self, n_sims: int | None = None, seed: int | None = None):
        self.n_sims = n_sims or self.DEFAULT_N_SIMS
        self.seed = seed

    def run(self, p_point: float, sets_to_win: int = 3) -> MonteCarloResult:
        return run_monte_carlo(p_point, self.n_sims, self.seed)


def _simulate_set_bernoulli(p_set: float, rng: random.Random) -> bool:
    """Один сет как Bernoulli(p_set). Для LightGBM p_set."""
    return rng.random() < p_set


def _simulate_match_simple_from_p_set(p_set: float, rng: random.Random) -> tuple[bool, int, bool, bool]:
    """Симулирует матч по p_set (LightGBM). Каждый сет = Bernoulli(p_set)."""
    s1 = _simulate_set_bernoulli(p_set, rng)
    s2 = _simulate_set_bernoulli(p_set, rng)
    p1_sets = int(s1) + int(s2)
    p2_sets = 2 - p1_sets
    if p1_sets == 2 and p2_sets == 0:
        return True, 3, s1, s2
    if p1_sets == 0 and p2_sets == 2:
        return False, 3, s1, s2
    s3 = _simulate_set_bernoulli(p_set, rng)
    p1_sets += int(s3)
    p2_sets += 1 - int(s3)
    if p1_sets == 3 or p2_sets == 3:
        return p1_sets == 3, 3, s1, s2
    s4 = _simulate_set_bernoulli(p_set, rng)
    p1_sets += int(s4)
    p2_sets += 1 - int(s4)
    if p1_sets == 3 or p2_sets == 3:
        return p1_sets == 3, 4, s1, s2
    s5 = _simulate_set_bernoulli(p_set, rng)
    return int(s5) == 1, 5, s1, s2


def _simulate_match_simple(p_point: float, rng: random.Random) -> tuple[bool, int, bool, bool]:
    """Симулирует матч point-by-point. p_point = P(выиграть очко). Возвращает (p1_won, total_sets, set1_won, set2_won)."""
    s1 = _simulate_set(p_point, rng)
    s2 = _simulate_set(p_point, rng)
    p1_sets = int(s1) + int(s2)
    p2_sets = 2 - p1_sets
    if p1_sets == 2 and p2_sets == 0:
        return True, 3, s1, s2
    if p1_sets == 0 and p2_sets == 2:
        return False, 3, s1, s2
    s3 = _simulate_set(p_point, rng)
    p1_sets += int(s3)
    p2_sets += 1 - int(s3)
    if p1_sets == 3 or p2_sets == 3:
        return p1_sets == 3, 3, s1, s2
    s4 = _simulate_set(p_point, rng)
    p1_sets += int(s4)
    p2_sets += 1 - int(s4)
    if p1_sets == 3 or p2_sets == 3:
        return p1_sets == 3, 4, s1, s2
    s5 = _simulate_set(p_point, rng)
    return int(s5) == 1, 5, s1, s2


def p_match_from_p_set_analytical(p_set: float, sets_to_win: int = 3) -> float:
    """Аналитический P(победа в матче) из P(победа в сете). BO5: P(3-0)+P(3-1)+P(3-2)."""
    if sets_to_win != 3:
        return 0.5  # fallback
    # P(3-0) = p^3
    # P(3-1) = C(3,2) * p^2 * (1-p) * p = 3 * p^3 * (1-p)
    # P(3-2) = C(4,2) * p^2 * (1-p)^2 * p = 6 * p^3 * (1-p)^2
    q = 1.0 - p_set
    p_30 = p_set ** 3
    p_31 = 3 * (p_set ** 3) * q
    p_32 = 6 * (p_set ** 3) * (q ** 2)
    return p_30 + p_31 + p_32


def run_monte_carlo(
    p_point: float | None = None,
    p_set: float | None = None,
    n_sims: int = 50_000,
    seed: int | None = None,
) -> MonteCarloResult:
    """Monte Carlo: p_point (point-by-point) или p_set (LightGBM)."""
    if p_set is not None:
        return _run_monte_carlo_from_p_set(p_set, n_sims, seed)
    if p_point is not None:
        return _run_monte_carlo_from_p_point(p_point, n_sims, seed)
    raise ValueError("p_point or p_set required")


def _run_monte_carlo_from_p_set(p_set: float, n_sims: int, seed: int | None) -> MonteCarloResult:
    """Симуляция матча из p_set (LightGBM). Каждый сет = Bernoulli(p_set)."""
    rng = random.Random(seed)
    wins_match = wins_set1 = wins_set2 = 0
    count_3_0 = count_3_1 = count_3_2 = 0
    count_over = 0
    for _ in range(n_sims):
        p1_won, total_sets, s1, s2 = _simulate_match_simple_from_p_set(p_set, rng)
        wins_match += int(p1_won)
        wins_set1 += int(s1)
        wins_set2 += int(s2)
        if total_sets == 3:
            count_3_0 += 1
        elif total_sets == 4:
            count_3_1 += 1
        else:
            count_3_2 += 1
        count_over += int(total_sets > 3.5)
    return MonteCarloResult(
        p_match=wins_match / n_sims,
        p_set1=wins_set1 / n_sims,
        p_set2=wins_set2 / n_sims,
        p_3_0=count_3_0 / n_sims,
        p_3_1=count_3_1 / n_sims,
        p_3_2=count_3_2 / n_sims,
        p_total_over_35=count_over / n_sims,
        p_total_under_35=1.0 - count_over / n_sims,
    )


def _run_monte_carlo_from_p_point(p_point: float, n_sims: int, seed: int | None) -> MonteCarloResult:
    """Упрощённая Monte Carlo симуляция (point-by-point)."""
    rng = random.Random(seed)
    wins_match = wins_set1 = wins_set2 = 0
    count_3_0 = count_3_1 = count_3_2 = 0
    count_over = 0
    for _ in range(n_sims):
        p1_won, total_sets, s1, s2 = _simulate_match_simple(p_point, rng)
        wins_match += int(p1_won)
        wins_set1 += int(s1)
        wins_set2 += int(s2)
        if total_sets == 3:
            count_3_0 += 1
        elif total_sets == 4:
            count_3_1 += 1
        else:
            count_3_2 += 1
        count_over += int(total_sets > 3.5)
    return MonteCarloResult(
        p_match=wins_match / n_sims,
        p_set1=wins_set1 / n_sims,
        p_set2=wins_set2 / n_sims,
        p_3_0=count_3_0 / n_sims,
        p_3_1=count_3_1 / n_sims,
        p_3_2=count_3_2 / n_sims,
        p_total_over_35=count_over / n_sims,
        p_total_under_35=1.0 - count_over / n_sims,
    )
