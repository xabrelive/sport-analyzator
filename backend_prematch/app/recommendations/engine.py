"""Precompute and persist match recommendations (предпрогноз) in a single place.

Used by:
- Celery tasks in collect_betsapi (line/live pipeline)
- one-off scripts (precompute_recommendations.py)
"""
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.models import Match, MatchRecommendation, OddsSnapshot
from app.services.analytics_service import first_recommendation_text_and_confidence
from app.services.player_stats_service import get_stats_for_recommendation

MIN_RECOMMENDATION_ODDS = 1.4


def _recommendation_side(text: str) -> str | None:
    if not text:
        return None
    t = text.lower()
    if "п1" in t:
        return "home"
    if "п2" in t:
        return "away"
    return None


async def _get_recommendation_stats(session: AsyncSession, match: Match) -> tuple[Any, Any]:
    """Обёртка над get_stats_for_recommendation с настройками из config."""
    league_id = getattr(match, "league_id", None)
    return await get_stats_for_recommendation(
        session,
        match.home_player_id,
        match.away_player_id,
        league_id,
        lookback_days=settings.recommendation_lookback_days,
        prefer_recent_days=getattr(settings, "recommendation_prefer_recent_days", None),
        min_matches_in_league=getattr(settings, "recommendation_min_matches_in_league", 3),
    )


async def precompute_match_recommendations_async(
    session_maker: async_sessionmaker[AsyncSession],
    match_ids: Iterable[str],
) -> int:
    """
    Сохраняет рекомендации в БД (одна запись на матч, не обновляется).

    Вызывается автоматически после каждого цикла линии и лайва, а также задачей
    precompute_active_recommendations. Для матчей с коэффициентами:
    сохраняем только если кф >= MIN_RECOMMENDATION_ODDS; без кф сохраняем с
    odds_at_recommendation=None.
    """
    match_ids = list(match_ids)
    if not match_ids:
        return 0

    created = 0
    async with session_maker() as session:
        # Уже рассчитанные матчи не пересчитываем: только добавляем новые записи, никогда не обновляем.
        existing_q = select(MatchRecommendation.match_id).where(MatchRecommendation.match_id.in_(match_ids))
        existing_rows = (await session.execute(existing_q)).all()
        existing_ids = {row[0] for row in existing_rows}

        matches_q = select(Match).where(Match.id.in_(match_ids))
        matches = (await session.execute(matches_q)).scalars().all()
        for match in matches:
            if match.id in existing_ids:
                continue
            if match.status not in ("scheduled", "live"):
                continue
            if not match.home_player_id or not match.away_player_id:
                continue

            stats_home, stats_away = await _get_recommendation_stats(session, match)
            if not stats_home or not stats_away:
                continue

            rec, confidence_pct = first_recommendation_text_and_confidence(stats_home, stats_away)
            if not rec:
                continue

            odds_val: float | None = None
            side = _recommendation_side(rec)
            if side is not None:
                odds_q = (
                    select(OddsSnapshot)
                    .where(
                        OddsSnapshot.match_id == match.id,
                        OddsSnapshot.market.in_(["winner", "92_1", "win"]),
                    )
                    .order_by(
                        OddsSnapshot.snapshot_time.asc().nullslast(),
                        OddsSnapshot.timestamp.asc().nullslast(),
                    )
                    .limit(50)
                )
                snaps = (await session.execute(odds_q)).scalars().all()
                for s in snaps:
                    sel = (s.selection or "").lower()
                    if side == "home" and sel in ("home", "1"):
                        odds_val = float(s.odds)
                        break
                    if side == "away" and sel in ("away", "2"):
                        odds_val = float(s.odds)
                        break

            # Если есть известный коэффициент и он ниже минимального порога — такую рекомендацию пропускаем.
            if odds_val is not None and odds_val < MIN_RECOMMENDATION_ODDS:
                continue

            session.add(
                MatchRecommendation(
                    match_id=match.id,
                    recommendation_text=rec,
                    odds_at_recommendation=odds_val,
                    confidence_pct=confidence_pct,
                )
            )
            created += 1

        if created:
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return created

