"""Probability Engine for table tennis: Beta-Bayes (point) + Markov (set)."""
from decimal import Decimal
from typing import NamedTuple


class MatchFormat(NamedTuple):
    """Формат матча: 3/5/7 сетов, до 11 или 6 очков."""
    sets_to_win: int = 2   # 2 = BO3, 3 = BO5, 4 = BO7
    points_per_set: int = 11  # 11 или 6
    win_by: int = 2


FORMAT_BO3_11 = MatchFormat(sets_to_win=2, points_per_set=11, win_by=2)
FORMAT_BO5_11 = MatchFormat(sets_to_win=3, points_per_set=11, win_by=2)
FORMAT_BO5_6 = MatchFormat(sets_to_win=3, points_per_set=6, win_by=2)
FORMAT_BO7_11 = MatchFormat(sets_to_win=4, points_per_set=11, win_by=2)


class MatchProbability(NamedTuple):
    """Probabilities for a match."""
    p_home_win: Decimal
    p_away_win: Decimal
    p_home_current_set: Decimal
    p_away_current_set: Decimal
    p_home_next_set: Decimal | None
    p_away_next_set: Decimal | None


def point_win_probability_beta(
    home_points_won: int,
    home_points_lost: int,
    away_points_won: int,
    away_points_lost: int,
    prior_alpha: float = 1.0,
    prior_beta: float = 1.0,
) -> tuple[float, float]:
    """
    Beta-Bayes: P(home wins next point), P(away wins next point).
    alpha += points won, beta += points lost for that player.
    """
    home_alpha = prior_alpha + home_points_won
    home_beta = prior_beta + home_points_lost
    away_alpha = prior_alpha + away_points_won
    away_beta = prior_beta + away_points_lost
    p_home = home_alpha / (home_alpha + home_beta)
    p_away = away_alpha / (away_alpha + away_beta)
    # Normalize to sum to 1
    total = p_home + p_away
    if total <= 0:
        return 0.5, 0.5
    return p_home / total, p_away / total


def set_win_probability_markov(
    home_score: int,
    away_score: int,
    p_point_home: float,
    first_to: int = 11,
    win_by: int = 2,
) -> float:
    """
    Markov model: probability that home wins the current set from (home_score, away_score).
    Simplified: first to 11, win by 2; no cap (e.g. 15-13). For exact deuce handling
    we could use recursion; here we use a simple state probability propagation.
    """
    if home_score >= first_to and home_score - away_score >= win_by:
        return 1.0
    if away_score >= first_to and away_score - home_score >= win_by:
        return 0.0
    # Recursive: P(win) = p_point * P(win from home+1, away) + (1-p_point) * P(win from home, away+1)
    # Memoized recursion to avoid stack overflow
    from functools import lru_cache
    max_points = first_to + win_by + 10  # safety

    @lru_cache(maxsize=500)
    def p_win(h: int, a: int) -> float:
        if h >= first_to and h - a >= win_by:
            return 1.0
        if a >= first_to and a - h >= win_by:
            return 0.0
        if h + a >= max_points:
            return 0.5
        return p_point_home * p_win(h + 1, a) + (1.0 - p_point_home) * p_win(h, a + 1)

    return p_win(home_score, away_score)


def match_win_probability(
    sets_home: list[tuple[int, int]],
    sets_away: list[tuple[int, int]],
    current_set_home: int,
    current_set_away: int,
    sets_to_win: int = 2,
    first_to: int = 11,
    win_by: int = 2,
    prior_alpha: float = 1.0,
    prior_beta: float = 1.0,
) -> MatchProbability:
    """
    Compute P(home wins match), P(away wins match), P(home wins current set), P(away wins current set).
    sets_home / sets_away: list of (home_pts, away_pts) per set (completed sets).
    current_set_*: score in the current set.
    first_to/win_by: формат сета (11/2 или 6/2).
    """
    home_points_won = sum(s[0] for s in sets_home) + current_set_home
    home_points_lost = sum(s[1] for s in sets_home) + current_set_away
    away_points_won = sum(s[1] for s in sets_home) + current_set_away
    away_points_lost = sum(s[0] for s in sets_home) + current_set_home

    p_pt_home, p_pt_away = point_win_probability_beta(
        home_points_won, home_points_lost, away_points_won, away_points_lost,
        prior_alpha, prior_beta,
    )
    p_home_current_set = set_win_probability_markov(
        current_set_home, current_set_away, p_pt_home, first_to, win_by
    )
    p_away_current_set = 1.0 - p_home_current_set

    home_sets_won = sum(1 for (h, a) in sets_home if h > a)
    away_sets_won = sum(1 for (h, a) in sets_home if a > h)
    # If match is in progress, we need P(home wins match) = P(home wins enough remaining sets)
    # Simplified: assume current set winner gets the set with prob p_home_current_set, then
    # remaining sets 50/50 for MVP. Better: full recursion over set outcomes.
    if home_sets_won >= sets_to_win:
        p_home_match = 1.0
        p_away_match = 0.0
    elif away_sets_won >= sets_to_win:
        p_home_match = 0.0
        p_away_match = 1.0
    else:
        # Probability home wins match = P(home wins current set) * P(home wins match from (home_sets+1, away_sets))
        #   + P(away wins current set) * P(home wins match from (home_sets, away_sets+1))
        # For "best of 3" (sets_to_win=2), from (1,0) home needs 1 more set; from (0,1) home needs 2.
        def p_match_rec(h_sets: int, a_sets: int) -> float:
            if h_sets >= sets_to_win:
                return 1.0
            if a_sets >= sets_to_win:
                return 0.0
            return (
                p_home_current_set * p_match_rec(h_sets + 1, a_sets)
                + p_away_current_set * p_match_rec(h_sets, a_sets + 1)
            )
        p_home_match = p_match_rec(home_sets_won, away_sets_won)
        p_away_match = 1.0 - p_home_match

    return MatchProbability(
        p_home_win=Decimal(str(round(p_home_match, 6))),
        p_away_win=Decimal(str(round(p_away_match, 6))),
        p_home_current_set=Decimal(str(round(p_home_current_set, 6))),
        p_away_current_set=Decimal(str(round(p_away_current_set, 6))),
        p_home_next_set=Decimal(str(round(p_pt_home, 6))),
        p_away_next_set=Decimal(str(round(p_pt_away, 6))),
    )


def from_scores_list(
    scores: list[dict],
    current_set_home: int = 0,
    current_set_away: int = 0,
    match_format: MatchFormat | None = None,
) -> MatchProbability:
    """
    scores: list of {"set_number", "home_score", "away_score"}.
    match_format: sets_to_win, points_per_set, win_by. Default BO3 до 11.
    """
    fmt = match_format or FORMAT_BO3_11
    completed: list[tuple[int, int]] = []
    cur_h, cur_a = current_set_home, current_set_away
    sorted_scores = sorted(scores, key=lambda x: x.get("set_number", 0))
    if sorted_scores and (cur_h == 0 and cur_a == 0):
        for s in sorted_scores[:-1]:
            completed.append((int(s.get("home_score", 0)), int(s.get("away_score", 0))))
        last = sorted_scores[-1]
        cur_h, cur_a = int(last.get("home_score", 0)), int(last.get("away_score", 0))
    else:
        for s in sorted_scores:
            completed.append((int(s.get("home_score", 0)), int(s.get("away_score", 0))))
    if not completed and cur_h == 0 and cur_a == 0:
        return MatchProbability(
            Decimal("0.5"), Decimal("0.5"),
            Decimal("0.5"), Decimal("0.5"),
            Decimal("0.5"), Decimal("0.5"),
        )
    return match_win_probability(
        completed,
        [],
        cur_h,
        cur_a,
        sets_to_win=fmt.sets_to_win,
        first_to=fmt.points_per_set,
        win_by=fmt.win_by,
    )
