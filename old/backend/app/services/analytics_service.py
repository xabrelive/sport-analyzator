"""Match analytics: recommendations, strengths/weaknesses per player, justification."""
from typing import NamedTuple

from app.schemas.player import PlayerStats


# Пороги для сохранённых рекомендаций (линия/лайв).
# Цель — не менее ~75% угадываний при разумном количестве матчей.
# Делаем модель более избирательной по вероятности, но даём работать и при небольшой истории.
CONFIDENCE_THRESHOLD = 0.78           # для сетов (П1/П2 выиграет сет)
CONFIDENCE_THRESHOLD_MATCH = 0.82     # для победы в матче
MIN_MATCHES_FOR_RECOMMENDATION = 3    # достаточно 3 матчей у каждого для сетовых выводов
MIN_MATCHES_FOR_MATCH_RECOMMENDATION = 7  # для матча — повышенное требование
# Минимальный отрыв лучшего исхода от второго по тому же рынку — избегаем 53/47, оставляем явные перекосы.
MIN_CONFIDENCE_MARGIN = 0.07


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
    threshold_match: float = CONFIDENCE_THRESHOLD_MATCH,
) -> list[MatchRecommendation]:
    """Рекомендации только при уверенности >= threshold (85%)."""
    recs: list[MatchRecommendation] = []

    if p_home_win >= threshold_match and (p_home_win - p_away_win) >= MIN_CONFIDENCE_MARGIN:
        recs.append(MatchRecommendation(f"П1 победа в матче ({p_home_win * 100:.0f}%)", p_home_win * 100))
    if p_away_win >= threshold_match and (p_away_win - p_home_win) >= MIN_CONFIDENCE_MARGIN:
        recs.append(MatchRecommendation(f"П2 победа в матче ({p_away_win * 100:.0f}%)", p_away_win * 100))

    if p_home_set1 >= threshold and (p_home_set1 - p_away_set1) >= MIN_CONFIDENCE_MARGIN:
        recs.append(MatchRecommendation(f"П1 выиграет 1-й сет ({p_home_set1 * 100:.0f}%)", p_home_set1 * 100))
    if p_away_set1 >= threshold and (p_away_set1 - p_home_set1) >= MIN_CONFIDENCE_MARGIN:
        recs.append(MatchRecommendation(f"П2 выиграет 1-й сет ({p_away_set1 * 100:.0f}%)", p_away_set1 * 100))

    if p_home_set2 >= threshold and (p_home_set2 - p_away_set2) >= MIN_CONFIDENCE_MARGIN:
        recs.append(MatchRecommendation(f"П1 выиграет 2-й сет ({p_home_set2 * 100:.0f}%)", p_home_set2 * 100))
    if p_away_set2 >= threshold and (p_away_set2 - p_home_set2) >= MIN_CONFIDENCE_MARGIN:
        recs.append(MatchRecommendation(f"П2 выиграет 2-й сет ({p_away_set2 * 100:.0f}%)", p_away_set2 * 100))

    return recs


def _is_match_win_rec(text: str) -> bool:
    return "победа в матче" in text


def first_recommendation_text(
    stats_home: PlayerStats | None,
    stats_away: PlayerStats | None,
    min_matches: int = MIN_MATCHES_FOR_RECOMMENDATION,
    threshold: float | None = None,
    threshold_match: float | None = None,
    min_matches_for_match: int | None = None,
) -> str | None:
    """
    Возвращает текст приоритетной рекомендации по матчу только при высокой уверенности (цель ≥85% угаданных).
    Требования: минимум min_matches у обоих; для победы в матче — min_matches_for_match или MIN_MATCHES_FOR_MATCH_RECOMMENDATION.
    Пороги threshold/threshold_match — при None используются константы (85%).
    """
    n_home = (stats_home.total_matches or 0) if stats_home else 0
    n_away = (stats_away.total_matches or 0) if stats_away else 0
    if n_home < min_matches or n_away < min_matches:
        return None
    p_home_win, p_away_win, p_home_set1, p_away_set1, p_home_set2, p_away_set2 = pre_match_probs(
        stats_home, stats_away
    )
    thr = threshold if threshold is not None else CONFIDENCE_THRESHOLD
    thr_m = threshold_match if threshold_match is not None else CONFIDENCE_THRESHOLD_MATCH
    recs = build_match_recommendations(
        p_home_win, p_away_win, p_home_set1, p_away_set1, p_home_set2, p_away_set2,
        threshold=thr, threshold_match=thr_m,
    )
    if not recs:
        return None

    # Рекомендацию на победу в матче учитываем только при достаточной истории
    min_match_rec = min_matches_for_match if min_matches_for_match is not None else MIN_MATCHES_FOR_MATCH_RECOMMENDATION
    if n_home < min_match_rec or n_away < min_match_rec:
        recs = [r for r in recs if not _is_match_win_rec(r.text)]
    if not recs:
        return None

    # Выбираем исход с максимальной уверенностью — без предпочтения сет/матч
    best = max(recs, key=lambda r: r.confidence_pct)
    return best.text


def first_recommendation_text_and_confidence(
    stats_home: PlayerStats | None,
    stats_away: PlayerStats | None,
    min_matches: int = MIN_MATCHES_FOR_RECOMMENDATION,
    threshold: float | None = None,
    threshold_match: float | None = None,
    min_matches_for_match: int | None = None,
) -> tuple[str | None, float]:
    """
    То же, что first_recommendation_text, но возвращает (текст, confidence_pct).
    confidence_pct в диапазоне 0–100; 0 если рекомендации нет.
    """
    n_home = (stats_home.total_matches or 0) if stats_home else 0
    n_away = (stats_away.total_matches or 0) if stats_away else 0
    if n_home < min_matches or n_away < min_matches:
        return None, 0.0
    p_home_win, p_away_win, p_home_set1, p_away_set1, p_home_set2, p_away_set2 = pre_match_probs(
        stats_home, stats_away
    )
    thr = threshold if threshold is not None else CONFIDENCE_THRESHOLD
    thr_m = threshold_match if threshold_match is not None else CONFIDENCE_THRESHOLD_MATCH
    recs = build_match_recommendations(
        p_home_win, p_away_win, p_home_set1, p_away_set1, p_home_set2, p_away_set2,
        threshold=thr, threshold_match=thr_m,
    )
    if not recs:
        return None, 0.0
    min_match_rec = min_matches_for_match if min_matches_for_match is not None else MIN_MATCHES_FOR_MATCH_RECOMMENDATION
    if n_home < min_match_rec or n_away < min_match_rec:
        recs = [r for r in recs if not _is_match_win_rec(r.text)]
    if not recs:
        return None, 0.0
    best = max(recs, key=lambda r: r.confidence_pct)
    return best.text, best.confidence_pct


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
