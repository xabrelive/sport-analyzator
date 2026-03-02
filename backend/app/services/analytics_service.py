"""Match analytics: recommendations (≥70%), strengths/weaknesses per player, justification."""
from typing import NamedTuple

from app.schemas.player import PlayerStats


CONFIDENCE_THRESHOLD = 0.70
MIN_MATCHES_FOR_RECOMMENDATION = 2


class MatchRecommendation(NamedTuple):
    text: str
    confidence_pct: float  # 0–100


def _pct_str(p: float | None) -> str:
    if p is None:
        return "–"
    return f"{p * 100:.0f}%"


def build_strengths_weaknesses(stats: PlayerStats | None) -> tuple[list[str], list[str]]:
    """Split player stats into strengths (green) and weaknesses (red)."""
    strengths: list[str] = []
    weaknesses: list[str] = []
    if not stats:
        return strengths, weaknesses

    if stats.win_first_set_pct is not None:
        if stats.win_first_set_pct >= 0.6:
            strengths.append(f"Часто выигрывает 1-й сет ({_pct_str(stats.win_first_set_pct)})")
        elif stats.win_first_set_pct <= 0.4 and (stats.matches_with_first_set or 0) >= 10:
            weaknesses.append(f"Редко выигрывает 1-й сет ({_pct_str(stats.win_first_set_pct)})")

    if stats.win_second_set_pct is not None:
        if stats.win_second_set_pct >= 0.6:
            strengths.append(f"Сильный во 2-м сете ({_pct_str(stats.win_second_set_pct)})")
        elif stats.win_second_set_pct <= 0.4 and (stats.matches_with_second_set or 0) >= 10:
            weaknesses.append(f"Слаб во 2-м сете ({_pct_str(stats.win_second_set_pct)})")

    if stats.avg_sets_per_match is not None:
        if stats.avg_sets_per_match >= 5:
            strengths.append(f"Часто играет долгие матчи (в ср. {stats.avg_sets_per_match} сетов)")
        elif stats.avg_sets_per_match <= 3.5:
            strengths.append(f"Часто заканчивает матчи быстро (в ср. {stats.avg_sets_per_match} сетов)")

    if stats.win_rate is not None and (stats.total_matches or 0) >= 15:
        if stats.win_rate >= 0.65:
            strengths.append(f"Высокий % побед ({_pct_str(stats.win_rate)})")
        elif stats.win_rate <= 0.35:
            weaknesses.append(f"Низкий % побед ({_pct_str(stats.win_rate)})")

    if stats.set_patterns:
        top = stats.set_patterns[0]
        if top and top.get("pct") is not None and top["pct"] >= 0.15:
            pattern = top.get("pattern", "")
            label = pattern.replace("W", "В").replace("L", "П")
            strengths.append(f"Частый порядок сетов: {label} ({_pct_str(top['pct'])})")

    return strengths, weaknesses


def pre_match_probs(
    stats_home: PlayerStats | None,
    stats_away: PlayerStats | None,
) -> tuple[float, float, float, float, float, float]:
    """
    Pre-match probabilities from historical stats.
    Returns: p_home_win, p_away_win, p_home_set1, p_away_set1, p_home_set2, p_away_set2.
    """
    wh, lah = (stats_home.win_rate or 0.5) if stats_home else 0.5, (stats_home.total_matches or 0) if stats_home else 0
    wa, laa = (stats_away.win_rate or 0.5) if stats_away else 0.5, (stats_away.total_matches or 0) if stats_away else 0
    if lah + laa == 0:
        p_home_win = p_away_win = 0.5
    else:
        rh = wh * (stats_home.total_matches or 1) if stats_home else 0.5
        ra = wa * (stats_away.total_matches or 1) if stats_away else 0.5
        total = rh + ra
        p_home_win = rh / total if total > 0 else 0.5
        p_away_win = 1.0 - p_home_win

    s1h = (stats_home.win_first_set_pct if stats_home is not None else None) or 0.5
    s1a = (stats_away.win_first_set_pct if stats_away is not None else None) or 0.5
    n1h = (stats_home.matches_with_first_set or 1) if stats_home else 1
    n1a = (stats_away.matches_with_first_set or 1) if stats_away else 1
    if n1h + n1a == 0:
        p_home_set1 = p_away_set1 = 0.5
    else:
        total_s1 = s1h * n1h + (1 - s1a) * n1a
        denom = n1h + n1a
        p_home_set1 = total_s1 / denom if denom > 0 else 0.5
        p_away_set1 = 1.0 - p_home_set1

    s2h = (stats_home.win_second_set_pct if stats_home is not None else None) or 0.5
    s2a = (stats_away.win_second_set_pct if stats_away is not None else None) or 0.5
    n2h = (stats_home.matches_with_second_set or 1) if stats_home else 1
    n2a = (stats_away.matches_with_second_set or 1) if stats_away else 1
    if n2h + n2a == 0:
        p_home_set2 = p_away_set2 = 0.5
    else:
        total_s2 = s2h * n2h + (1 - s2a) * n2a
        denom = n2h + n2a
        p_home_set2 = total_s2 / denom if denom > 0 else 0.5
        p_away_set2 = 1.0 - p_home_set2

    return p_home_win, p_away_win, p_home_set1, p_away_set1, p_home_set2, p_away_set2


def build_match_recommendations(
    p_home_win: float,
    p_away_win: float,
    p_home_set1: float,
    p_away_set1: float,
    p_home_set2: float,
    p_away_set2: float,
    threshold: float = CONFIDENCE_THRESHOLD,
) -> list[MatchRecommendation]:
    """Build list of recommendations only when confidence >= threshold."""
    recs: list[MatchRecommendation] = []

    if p_home_win >= threshold:
        recs.append(MatchRecommendation(f"П1 победа в матче ({p_home_win * 100:.0f}%)", p_home_win * 100))
    if p_away_win >= threshold:
        recs.append(MatchRecommendation(f"П2 победа в матче ({p_away_win * 100:.0f}%)", p_away_win * 100))

    if p_home_set1 >= threshold:
        recs.append(MatchRecommendation(f"П1 выиграет 1-й сет ({p_home_set1 * 100:.0f}%)", p_home_set1 * 100))
    if p_away_set1 >= threshold:
        recs.append(MatchRecommendation(f"П2 выиграет 1-й сет ({p_away_set1 * 100:.0f}%)", p_away_set1 * 100))

    if p_home_set2 >= threshold:
        recs.append(MatchRecommendation(f"П1 выиграет 2-й сет ({p_home_set2 * 100:.0f}%)", p_home_set2 * 100))
    if p_away_set2 >= threshold:
        recs.append(MatchRecommendation(f"П2 выиграет 2-й сет ({p_away_set2 * 100:.0f}%)", p_away_set2 * 100))

    return recs


def first_recommendation_text(
    stats_home: PlayerStats | None,
    stats_away: PlayerStats | None,
    min_matches: int = MIN_MATCHES_FOR_RECOMMENDATION,
) -> str | None:
    """
    Возвращает текст приоритетной рекомендации по матчу только если у обоих игроков
    достаточно истории (минимум min_matches завершённых матчей). Иначе None.
    Выбирается исход, в котором мы наиболее уверены (максимальная вероятность) —
    либо победа в матче, либо победа в конкретном сете — чтобы доля угаданных была выше.
    """
    n_home = (stats_home.total_matches or 0) if stats_home else 0
    n_away = (stats_away.total_matches or 0) if stats_away else 0
    if n_home < min_matches or n_away < min_matches:
        return None
    p_home_win, p_away_win, p_home_set1, p_away_set1, p_home_set2, p_away_set2 = pre_match_probs(
        stats_home, stats_away
    )
    recs = build_match_recommendations(
        p_home_win, p_away_win, p_home_set1, p_away_set1, p_home_set2, p_away_set2
    )
    if not recs:
        return None
    # Наиболее уверенный исход — матч или сет — тот, у которого максимальная вероятность
    best = max(recs, key=lambda r: r.confidence_pct)
    return best.text


def build_justification(
    recommendations: list[MatchRecommendation],
    stats_home: PlayerStats | None,
    stats_away: PlayerStats | None,
    p_home_win: float,
    p_away_win: float,
    p_home_set1: float,
    p_away_set1: float,
) -> str:
    """Rule-based short justification of the analytics."""
    parts: list[str] = []
    if recommendations:
        parts.append("Рекомендации основаны на вероятностях модели (история матчей и счёт по сетам).")
    if stats_home and stats_away and (stats_home.total_matches or 0) + (stats_away.total_matches or 0) > 0:
        parts.append(
            f"Учтена статистика: П1 — {stats_home.total_matches} матчей, "
            f"П2 — {stats_away.total_matches} матчей."
        )
    if p_home_win >= 0.6 or p_away_win >= 0.6:
        parts.append(
            f"Вероятность победы в матче: П1 {p_home_win * 100:.0f}%, П2 {p_away_win * 100:.0f}%."
        )
    if p_home_set1 >= 0.55 or p_away_set1 >= 0.55:
        parts.append(
            f"Первый сет: П1 {p_home_set1 * 100:.0f}%, П2 {p_away_set1 * 100:.0f}%."
        )
    if not parts:
        return "Недостаточно данных для обоснования. Статистика по игрокам и матчу будет уточняться по мере появления матчей."
    return " ".join(parts)
