"""Pre‑match analytics for table tennis: recommendation to fill 'Прогноз' column.

Логика максимально приближена к старому analytics_service:
- считаем win_rate и статистику по 1/2 сету,
- на их основе получаем вероятности победы в матче и сетах,
- строим рекомендации и выбираем самую уверенную.

Используются только данные из table_tennis_line_events (завершённые матчи).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import Tuple

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.table_tennis_line_event import (
    TableTennisLineEvent,
    LINE_EVENT_STATUS_FINISHED,
    LINE_EVENT_STATUS_CANCELLED,
    LINE_EVENT_STATUS_SCHEDULED,
    LINE_EVENT_STATUS_LIVE,
    LINE_EVENT_STATUS_POSTPONED,
)
from app.models.table_tennis_forecast_v2 import TableTennisForecastV2
from app.config import settings

logger = logging.getLogger(__name__)

# Пороги no-ML (управляются через .env): сеты/матч, минимум матчей, отрыв.
CONFIDENCE_THRESHOLD = float(
    getattr(settings, "betsapi_table_tennis_no_ml_confidence_threshold_set", 0.65) or 0.65
)  # для сетов
CONFIDENCE_THRESHOLD_MATCH = float(
    getattr(settings, "betsapi_table_tennis_no_ml_confidence_threshold_match", 0.65) or 0.65
)  # для победы в матче
MIN_MATCHES_FOR_RECOMMENDATION = int(
    getattr(settings, "betsapi_table_tennis_no_ml_min_matches_for_recommendation", 2) or 2
)  # минимум матчей у каждого для выводов
MIN_MATCHES_FOR_MATCH_RECOMMENDATION = int(
    getattr(settings, "betsapi_table_tennis_no_ml_min_matches_for_match_recommendation", 4) or 4
)  # для прогноза на матч — больше истории
MIN_CONFIDENCE_MARGIN = float(
    getattr(settings, "betsapi_table_tennis_no_ml_min_confidence_margin", 0.03) or 0.03
)  # минимальный отрыв лучшего исхода от альтернативы

# Окна для статистики.
RECOMMENDATION_LOOKBACK_DAYS = 180
RECOMMENDATION_PREFER_RECENT_DAYS: int | None = 30
RECOMMENDATION_MIN_MATCHES_IN_LEAGUE = 1  # было 3 — меньше требований к лиге, больше прогнозов


@dataclass
class PlayerStats:
    total_matches: int
    wins: int
    losses: int
    win_rate: float | None
    matches_with_first_set: int
    wins_first_set: int
    win_first_set_pct: float | None
    matches_with_second_set: int
    wins_second_set: int
    win_second_set_pct: float | None


def _parse_sets_score(value: str | None) -> Tuple[int | None, int | None]:
    if not value or "-" not in value:
        return None, None
    left, right = value.split("-", 1)
    try:
        return int(left), int(right)
    except (TypeError, ValueError):
        return None, None


async def load_player_stats(
    session: AsyncSession,
    player_id: str,
) -> PlayerStats | None:
    """Строит PlayerStats по завершённым матчам игрока из table_tennis_line_events."""
    stmt = select(TableTennisLineEvent).where(
        and_(
            TableTennisLineEvent.status == LINE_EVENT_STATUS_FINISHED,
            (TableTennisLineEvent.home_id == player_id)
            | (TableTennisLineEvent.away_id == player_id),
        )
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    if not rows:
        return None

    total = 0
    wins = 0
    losses = 0
    matches_with_first = 0
    wins_first = 0
    matches_with_second = 0
    wins_second = 0

    for r in rows:
        total += 1
        # Победа в матче по сетовому счёту
        hs, as_ = _parse_sets_score(r.live_sets_score)
        if hs is not None and as_ is not None and (hs != as_):
            is_home = r.home_id == player_id
            home_win = hs > as_
            if (is_home and home_win) or ((not is_home) and (not home_win)):
                wins += 1
            else:
                losses += 1

        # Статистика по 1 и 2 сету из live_score
        if isinstance(r.live_score, dict):
            # 1-й сет
            s1 = r.live_score.get("1")
            if isinstance(s1, dict):
                try:
                    h1 = int(str(s1.get("home") or "0"))
                    a1 = int(str(s1.get("away") or "0"))
                except ValueError:
                    h1 = a1 = 0
                if h1 or a1:
                    matches_with_first += 1
                    is_home = r.home_id == player_id
                    home_win = h1 > a1
                    if (is_home and home_win) or ((not is_home) and (not home_win)):
                        wins_first += 1

            # 2-й сет
            s2 = r.live_score.get("2")
            if isinstance(s2, dict):
                try:
                    h2 = int(str(s2.get("home") or "0"))
                    a2 = int(str(s2.get("away") or "0"))
                except ValueError:
                    h2 = a2 = 0
                if h2 or a2:
                    matches_with_second += 1
                    is_home = r.home_id == player_id
                    home_win = h2 > a2
                    if (is_home and home_win) or ((not is_home) and (not home_win)):
                        wins_second += 1

    if total == 0:
        return None

    win_rate = wins / total if total > 0 else None
    win_first_set_pct = (
        wins_first / matches_with_first if matches_with_first > 0 else None
    )
    win_second_set_pct = (
        wins_second / matches_with_second if matches_with_second > 0 else None
    )

    return PlayerStats(
        total_matches=total,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        matches_with_first_set=matches_with_first,
        wins_first_set=wins_first,
        win_first_set_pct=win_first_set_pct,
        matches_with_second_set=matches_with_second,
        wins_second_set=wins_second,
        win_second_set_pct=win_second_set_pct,
    )


async def _compute_player_stats_for_window(
    session: AsyncSession,
    player_id: str,
    *,
    last_days: int | None = None,
    league_id: str | None = None,
) -> PlayerStats | None:
    """
    Аналог compute_player_stats из старого player_stats_service, но по table_tennis_line_events.
    Используется только для выбора окна статистики под рекомендацию (no-ML).
    """
    stmt = select(TableTennisLineEvent).where(
        and_(
            TableTennisLineEvent.status == LINE_EVENT_STATUS_FINISHED,
            (TableTennisLineEvent.home_id == player_id)
            | (TableTennisLineEvent.away_id == player_id),
        )
    )
    if last_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=last_days)
        stmt = stmt.where(TableTennisLineEvent.starts_at >= cutoff)
    if league_id is not None:
        stmt = stmt.where(TableTennisLineEvent.league_id == league_id)

    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    if not rows:
        return None

    total = 0
    wins = 0
    losses = 0
    matches_with_first = 0
    wins_first = 0
    matches_with_second = 0
    wins_second = 0

    for r in rows:
        total += 1
        # Победа в матче по сетовому счёту
        hs, as_ = _parse_sets_score(r.live_sets_score)
        if hs is not None and as_ is not None and (hs != as_):
            is_home = r.home_id == player_id
            home_win = hs > as_
            if (is_home and home_win) or ((not is_home) and (not home_win)):
                wins += 1
            else:
                losses += 1

        # Статистика по 1 и 2 сету из live_score
        if isinstance(r.live_score, dict):
            # 1-й сет
            s1 = r.live_score.get("1")
            if isinstance(s1, dict):
                try:
                    h1 = int(str(s1.get("home") or "0"))
                    a1 = int(str(s1.get("away") or "0"))
                except ValueError:
                    h1 = a1 = 0
                if h1 or a1:
                    matches_with_first += 1
                    is_home = r.home_id == player_id
                    home_win = h1 > a1
                    if (is_home and home_win) or ((not is_home) and (not home_win)):
                        wins_first += 1

            # 2-й сет
            s2 = r.live_score.get("2")
            if isinstance(s2, dict):
                try:
                    h2 = int(str(s2.get("home") or "0"))
                    a2 = int(str(s2.get("away") or "0"))
                except ValueError:
                    h2 = a2 = 0
                if h2 or a2:
                    matches_with_second += 1
                    is_home = r.home_id == player_id
                    home_win = h2 > a2
                    if (is_home and home_win) or ((not is_home) and (not home_win)):
                        wins_second += 1

    if total == 0:
        return None

    win_rate = wins / total if total > 0 else None
    win_first_set_pct = (
        wins_first / matches_with_first if matches_with_first > 0 else None
    )
    win_second_set_pct = (
        wins_second / matches_with_second if matches_with_second > 0 else None
    )

    return PlayerStats(
        total_matches=total,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        matches_with_first_set=matches_with_first,
        wins_first_set=wins_first,
        win_first_set_pct=win_first_set_pct,
        matches_with_second_set=matches_with_second,
        wins_second_set=wins_second,
        win_second_set_pct=win_second_set_pct,
    )


async def get_stats_for_recommendation_from_line_events(
    session: AsyncSession,
    home_player_id: str,
    away_player_id: str,
    league_id: str | None,
    *,
    lookback_days: int = RECOMMENDATION_LOOKBACK_DAYS,
    prefer_recent_days: int | None = RECOMMENDATION_PREFER_RECENT_DAYS,
    min_matches_in_league: int = RECOMMENDATION_MIN_MATCHES_IN_LEAGUE,
) -> tuple[PlayerStats | None, PlayerStats | None]:
    """
    Статистика для рекомендации: приоритет — лига и короткое окно (неделя/месяц),
    как в старом get_stats_for_recommendation.
    """

    def enough_in_league(sh: PlayerStats | None, sa: PlayerStats | None) -> bool:
        if league_id is None:
            return True
        return (
            sh is not None
            and sa is not None
            and (sh.total_matches or 0) >= min_matches_in_league
            and (sa.total_matches or 0) >= min_matches_in_league
        )

    # 1) prefer_recent_days + лига
    if prefer_recent_days is not None:
        sh = await _compute_player_stats_for_window(
            session,
            home_player_id,
            last_days=prefer_recent_days,
            league_id=league_id,
        )
        sa = await _compute_player_stats_for_window(
            session,
            away_player_id,
            last_days=prefer_recent_days,
            league_id=league_id,
        )
        if enough_in_league(sh, sa):
            return sh, sa

    # 2) lookback_days + лига
    sh = await _compute_player_stats_for_window(
        session,
        home_player_id,
        last_days=lookback_days,
        league_id=league_id,
    )
    sa = await _compute_player_stats_for_window(
        session,
        away_player_id,
        last_days=lookback_days,
        league_id=league_id,
    )
    if enough_in_league(sh, sa):
        return sh, sa

    # 3) Fallback: lookback_days по всем лигам
    sh = await _compute_player_stats_for_window(
        session,
        home_player_id,
        last_days=lookback_days,
        league_id=None,
    )
    sa = await _compute_player_stats_for_window(
        session,
        away_player_id,
        last_days=lookback_days,
        league_id=None,
    )
    return sh, sa


def _pre_match_probs(
    stats_home: PlayerStats | None,
    stats_away: PlayerStats | None,
) -> tuple[float, float, float, float, float, float]:
    """
    Pre-match probabilities from historical stats.
    Returns: p_home_win, p_away_win, p_home_set1, p_away_set1, p_home_set2, p_away_set2.
    """
    wh = stats_home.win_rate if stats_home and stats_home.win_rate is not None else 0.5
    wa = stats_away.win_rate if stats_away and stats_away.win_rate is not None else 0.5
    lah = stats_home.total_matches if stats_home else 0
    laa = stats_away.total_matches if stats_away else 0
    if lah + laa == 0:
        p_home_win = p_away_win = 0.5
    else:
        rh = wh * (stats_home.total_matches or 1) if stats_home else 0.5
        ra = wa * (stats_away.total_matches or 1) if stats_away else 0.5
        total = rh + ra
        p_home_win = rh / total if total > 0 else 0.5
        p_away_win = 1.0 - p_home_win

    s1h = stats_home.win_first_set_pct if stats_home and stats_home.win_first_set_pct is not None else 0.5
    s1a = stats_away.win_first_set_pct if stats_away and stats_away.win_first_set_pct is not None else 0.5
    n1h = stats_home.matches_with_first_set if stats_home else 0
    n1a = stats_away.matches_with_first_set if stats_away else 0
    if n1h + n1a == 0:
        p_home_set1 = p_away_set1 = 0.5
    else:
        total_s1 = s1h * n1h + (1 - s1a) * n1a
        denom = n1h + n1a
        p_home_set1 = total_s1 / denom if denom > 0 else 0.5
        p_away_set1 = 1.0 - p_home_set1

    s2h = stats_home.win_second_set_pct if stats_home and stats_home.win_second_set_pct is not None else 0.5
    s2a = stats_away.win_second_set_pct if stats_away and stats_away.win_second_set_pct is not None else 0.5
    n2h = stats_home.matches_with_second_set if stats_home else 0
    n2a = stats_away.matches_with_second_set if stats_away else 0
    if n2h + n2a == 0:
        p_home_set2 = p_away_set2 = 0.5
    else:
        total_s2 = s2h * n2h + (1 - s2a) * n2a
        denom = n2h + n2a
        p_home_set2 = total_s2 / denom if denom > 0 else 0.5
        p_away_set2 = 1.0 - p_home_set2

    return p_home_win, p_away_win, p_home_set1, p_away_set1, p_home_set2, p_away_set2


@dataclass
class MatchRecommendation:
    text: str
    confidence_pct: float  # 0–100


def _build_match_recommendations(
    p_home_win: float,
    p_away_win: float,
    p_home_set1: float,
    p_away_set1: float,
    p_home_set2: float,
    p_away_set2: float,
    threshold: float = CONFIDENCE_THRESHOLD,
    threshold_match: float = CONFIDENCE_THRESHOLD_MATCH,
) -> list[MatchRecommendation]:
    """Рекомендации только при уверенности >= threshold."""
    recs: list[MatchRecommendation] = []

    # Победа в матче
    if p_home_win >= threshold_match and (p_home_win - p_away_win) >= MIN_CONFIDENCE_MARGIN:
        recs.append(
            MatchRecommendation(
                f"П1 победа в матче ({p_home_win * 100:.0f}%)",
                p_home_win * 100,
            )
        )
    if p_away_win >= threshold_match and (p_away_win - p_home_win) >= MIN_CONFIDENCE_MARGIN:
        recs.append(
            MatchRecommendation(
                f"П2 победа в матче ({p_away_win * 100:.0f}%)",
                p_away_win * 100,
            )
        )

    # 1-й сет
    if p_home_set1 >= threshold and (p_home_set1 - p_away_set1) >= MIN_CONFIDENCE_MARGIN:
        recs.append(
            MatchRecommendation(
                f"П1 выиграет 1-й сет ({p_home_set1 * 100:.0f}%)",
                p_home_set1 * 100,
            )
        )
    if p_away_set1 >= threshold and (p_away_set1 - p_home_set1) >= MIN_CONFIDENCE_MARGIN:
        recs.append(
            MatchRecommendation(
                f"П2 выиграет 1-й сет ({p_away_set1 * 100:.0f}%)",
                p_away_set1 * 100,
            )
        )

    # 2-й сет
    if p_home_set2 >= threshold and (p_home_set2 - p_away_set2) >= MIN_CONFIDENCE_MARGIN:
        recs.append(
            MatchRecommendation(
                f"П1 выиграет 2-й сет ({p_home_set2 * 100:.0f}%)",
                p_home_set2 * 100,
            )
        )
    if p_away_set2 >= threshold and (p_away_set2 - p_home_set2) >= MIN_CONFIDENCE_MARGIN:
        recs.append(
            MatchRecommendation(
                f"П2 выиграет 2-й сет ({p_away_set2 * 100:.0f}%)",
                p_away_set2 * 100,
            )
        )

    return recs


def _is_match_win_rec(text: str) -> bool:
    return "победа в матче" in text


def _first_recommendation_text_and_confidence(
    stats_home: PlayerStats | None,
    stats_away: PlayerStats | None,
    min_matches: int = MIN_MATCHES_FOR_RECOMMENDATION,
    threshold: float | None = None,
    threshold_match: float | None = None,
    min_matches_for_match: int | None = None,
) -> tuple[str | None, float]:
    """
    Логика максимально совпадает со старым first_recommendation_text_and_confidence:
    - требуем минимум матчей у обоих игроков;
    - строим рекомендации по матчу и сетам;
    - при недостаточной истории отбрасываем прогнозы «победа в матче»;
    - выбираем исход с максимальной уверенностью без дополнительного приоритета матча/сетов.
    """
    n_home = (stats_home.total_matches if stats_home else 0)
    n_away = (stats_away.total_matches if stats_away else 0)
    if n_home < min_matches or n_away < min_matches:
        return None, 0.0

    p_home_win, p_away_win, p_home_set1, p_away_set1, p_home_set2, p_away_set2 = _pre_match_probs(
        stats_home, stats_away
    )
    thr = threshold if threshold is not None else CONFIDENCE_THRESHOLD
    thr_m = threshold_match if threshold_match is not None else CONFIDENCE_THRESHOLD_MATCH
    recs = _build_match_recommendations(
        p_home_win,
        p_away_win,
        p_home_set1,
        p_away_set1,
        p_home_set2,
        p_away_set2,
        threshold=thr,
        threshold_match=thr_m,
    )

    min_match_rec = (
        min_matches_for_match
        if min_matches_for_match is not None
        else MIN_MATCHES_FOR_MATCH_RECOMMENDATION
    )
    if n_home < min_match_rec or n_away < min_match_rec:
        recs = [r for r in recs if not _is_match_win_rec(r.text)]

    # Прогноз только при максимальной уверенности: если ни один исход не прошёл порог — не даём прогноз.
    if not recs:
        return None, 0.0

    best = max(recs, key=lambda r: r.confidence_pct)
    return best.text, best.confidence_pct


async def compute_forecast_for_event(
    session: AsyncSession,
    event: TableTennisLineEvent,
) -> Tuple[str | None, float]:
    """Возвращает (текст прогноза, confidence_pct) или (None, 0.0), если данных недостаточно."""
    home_id = event.home_id
    away_id = event.away_id
    if not home_id or not away_id:
        logger.debug(
            "no-ML event %s: нет home_id или away_id (прогноз невозможен)",
            getattr(event, "id", "?"),
        )
        return None, 0.0

    # Для no-ML прогноза используем «умную» статистику:
    # та же лига + последние N дней, как в старом backend_prematch.
    stats_home, stats_away = await get_stats_for_recommendation_from_line_events(
        session,
        home_id,
        away_id,
        getattr(event, "league_id", None),
    )
    if not stats_home or not stats_away:
        logger.debug(
            "no-ML event %s: нет статистики по игрокам (в table_tennis_line_events нужны завершённые матчи со счётом)",
            getattr(event, "id", "?"),
        )
        return None, 0.0

    text, conf = _first_recommendation_text_and_confidence(
        stats_home,
        stats_away,
        min_matches=MIN_MATCHES_FOR_RECOMMENDATION,
        threshold=CONFIDENCE_THRESHOLD,
        threshold_match=CONFIDENCE_THRESHOLD_MATCH,
        min_matches_for_match=MIN_MATCHES_FOR_MATCH_RECOMMENDATION,
    )
    if not text:
        logger.debug(
            "no-ML event %s: нет рекомендации (нет статистики или недостаточно матчей у игроков в table_tennis_line_events)",
            getattr(event, "id", "?"),
        )
        return None, 0.0
    return text, conf


def build_strengths_weaknesses(
    stats: PlayerStats | None,
) -> tuple[list[str], list[str]]:
    """Формирует человекочитаемые сильные и слабые стороны игрока по статистике."""
    strengths: list[str] = []
    weaknesses: list[str] = []
    if not stats:
        return strengths, weaknesses

    if stats.win_rate is not None:
        if stats.win_rate >= 0.65 and stats.total_matches >= 10:
            strengths.append(f"Высокий % побед в матчах ({stats.win_rate * 100:.0f}%)")
        elif stats.win_rate <= 0.35 and stats.total_matches >= 10:
            weaknesses.append(f"Низкий % побед в матчах ({stats.win_rate * 100:.0f}%)")

    if stats.win_first_set_pct is not None and stats.matches_with_first_set >= 8:
        if stats.win_first_set_pct >= 0.6:
            strengths.append(
                f"Часто выигрывает 1-й сет ({stats.win_first_set_pct * 100:.0f}%)"
            )
        elif stats.win_first_set_pct <= 0.4:
            weaknesses.append(
                f"Редко выигрывает 1-й сет ({stats.win_first_set_pct * 100:.0f}%)"
            )

    if stats.win_second_set_pct is not None and stats.matches_with_second_set >= 8:
        if stats.win_second_set_pct >= 0.6:
            strengths.append(
                f"Сильный во 2-м сете ({stats.win_second_set_pct * 100:.0f}%)"
            )
        elif stats.win_second_set_pct <= 0.4:
            weaknesses.append(
                f"Слабый во 2-м сете ({stats.win_second_set_pct * 100:.0f}%)"
            )

    return strengths, weaknesses


def _evaluate_forecast_outcome(
    event: TableTennisLineEvent,
    forecast_text: str,
) -> str:
    """Определяет исход прогноза (hit/miss/no_result) по финальным данным матча."""
    # Нужен финальный счёт и, для сетовых прогнозов, детализация по сетам.
    sets_score = event.live_sets_score or ""
    scores = event.live_score or {}

    # Помощники для победителя матча и сетов
    def _winner_by_sets() -> str | None:
        h, a = _parse_sets_score(sets_score)
        if h is None or a is None or h == a:
            return None
        return "home" if h > a else "away"

    def _winner_in_set(set_no: str) -> str | None:
        s = scores.get(set_no)
        if not isinstance(s, dict):
            return None
        try:
            h = int(str(s.get("home") or "0"))
            a = int(str(s.get("away") or "0"))
        except ValueError:
            return None
        # Сет считаем завершённым только по правилам настольного тенниса.
        if not (max(h, a) >= 11 and abs(h - a) >= 2):
            return None
        if h == a:
            return None
        return "home" if h > a else "away"

    text = forecast_text.lower()

    # Прогноз на победу в матче
    if "победа в матче" in text:
        winner = _winner_by_sets()
        if winner is None:
            return "no_result"
        expected = "home" if "п1" in text else "away"
        return "hit" if winner == expected else "miss"

    # Прогноз на 1-й сет
    if "1-й сет" in text:
        winner = _winner_in_set("1")
        if winner is None:
            return "no_result"
        expected = "home" if "п1" in text else "away"
        return "hit" if winner == expected else "miss"

    # Прогноз на 2-й сет
    if "2-й сет" in text:
        winner = _winner_in_set("2")
        if winner is None:
            return "no_result"
        expected = "home" if "п1" in text else "away"
        return "hit" if winner == expected else "miss"

    return "no_result"


def _is_match_forecast_text(value: str | None) -> bool:
    return "победа в матче" in (value or "").lower()


def _has_in_progress_set_fragment(scores: dict | None) -> bool:
    if not isinstance(scores, dict):
        return False
    for _, s in scores.items():
        if not isinstance(s, dict):
            continue
        try:
            h = int(str(s.get("home") or "0"))
            a = int(str(s.get("away") or "0"))
        except ValueError:
            continue
        if h == 0 and a == 0:
            continue
        if not (max(h, a) >= 11 and abs(h - a) >= 2):
            return True
    return False


def _cancelled_grace_elapsed(event: TableTennisLineEvent, now: datetime) -> bool:
    if event.starts_at is None:
        return True
    from datetime import timedelta
    return now >= (event.starts_at + timedelta(hours=2))


async def update_forecast_outcome_for_event(
    session: AsyncSession,
    event: TableTennisLineEvent,
) -> None:
    """Обновляет статус V2-прогнозов для данного события."""
    if not event.id:
        return
    result = await session.execute(
        select(TableTennisForecastV2).where(
            TableTennisForecastV2.event_id == event.id,
            TableTennisForecastV2.status.in_(["pending", "cancelled", "no_result", "hit", "miss"]),
        )
    )
    rows = list(result.scalars().all())
    if not rows:
        return

    now = datetime.now(timezone.utc)
    hs, as_ = _parse_sets_score(event.live_sets_score)
    has_decisive_sets_winner = hs is not None and as_ is not None and hs != as_
    required_wins = max(1, int(getattr(settings, "table_tennis_match_sets_to_win", 3)))
    score_final = (
        has_decisive_sets_winner
        and max(hs or 0, as_ or 0) >= required_wins
        and not _has_in_progress_set_fragment(event.live_score)
    )

    # Если матч "ожил" (scheduled/live/postponed) после ошибочного cancelled/no_result,
    # возвращаем прогноз в pending.
    if event.status in {
        LINE_EVENT_STATUS_SCHEDULED,
        LINE_EVENT_STATUS_LIVE,
        LINE_EVENT_STATUS_POSTPONED,
    }:
        for row in rows:
            if row.status in {"cancelled", "no_result"} or (
                _is_match_forecast_text(row.forecast_text) and row.status in {"hit", "miss"}
            ):
                row.status = "pending"
                row.resolved_at = None
                row.final_status = None
                row.final_sets_score = None
            elif row.status in {"hit", "miss"} and row.forecast_text:
                outcome_preview = _evaluate_forecast_outcome(event, row.forecast_text)
                if outcome_preview == "no_result":
                    row.status = "pending"
                    row.resolved_at = None
                    row.final_status = None
                    row.final_sets_score = None

    # Если матч помечен cancelled, но по сетам уже есть явный победитель,
    # считаем его завершённым для целей прогноза (BetsAPI иногда запаздывает по status).
    if event.status == LINE_EVENT_STATUS_CANCELLED and not score_final:
        if not _cancelled_grace_elapsed(event, now):
            for row in rows:
                # Keep all forecasts pending during grace window.
                if row.status in {"cancelled", "no_result", "hit", "miss"}:
                    row.status = "pending"
                    row.resolved_at = None
                    row.final_status = None
                    row.final_sets_score = None
            return
        for row in rows:
            if _is_match_forecast_text(row.forecast_text):
                row.status = "pending"
                row.resolved_at = None
                row.final_status = None
                row.final_sets_score = None
            else:
                row.status = "cancelled"
                row.resolved_at = now
                row.final_status = event.status
                row.final_sets_score = event.live_sets_score
        return

    # В реальных данных BetsAPI статус иногда запаздывает, но по live_sets_score уже есть победитель.
    # Тогда считаем матч завершённым для расчёта исхода прогноза.
    effective_status = event.status
    if event.status != LINE_EVENT_STATUS_FINISHED:
        if not has_decisive_sets_winner:
            return
        effective_status = LINE_EVENT_STATUS_FINISHED

    for row in rows:
        if _is_match_forecast_text(row.forecast_text):
            can_resolve_match = (
                event.status in {LINE_EVENT_STATUS_FINISHED, LINE_EVENT_STATUS_CANCELLED}
                and score_final
            )
            if not can_resolve_match:
                if row.status in {"hit", "miss", "cancelled", "no_result"}:
                    row.status = "pending"
                    row.resolved_at = None
                    row.final_status = None
                    row.final_sets_score = None
                continue
        if not row.forecast_text:
            row.status = "no_result"
        else:
            row.status = _evaluate_forecast_outcome(event, row.forecast_text)
        row.resolved_at = now
        row.final_status = effective_status
        row.final_sets_score = event.live_sets_score


