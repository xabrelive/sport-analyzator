"""Probability API — модель вероятностей по матчу и аналитика матча."""
from uuid import UUID
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_async_session
from app.models import Match
from app.config import settings
from app.services.probability_engine import MatchFormat, from_scores_list, set_win_probability_markov
from app.services.player_stats_service import compute_player_stats, get_stats_for_recommendation
from app.services.analytics_service import (
    build_strengths_weaknesses,
    build_match_recommendations,
    build_justification,
    pre_match_probs,
)

router = APIRouter()


class ProbabilityResponse(BaseModel):
    p_home_win: Decimal
    p_away_win: Decimal
    p_home_current_set: Decimal
    p_away_current_set: Decimal
    p_home_next_set: Decimal | None
    p_away_next_set: Decimal | None


class MatchRecommendationOut(BaseModel):
    text: str
    confidence_pct: float


class MatchAnalyticsResponse(BaseModel):
    recommendations: list[MatchRecommendationOut]
    home_strengths: list[str]
    home_weaknesses: list[str]
    away_strengths: list[str]
    away_weaknesses: list[str]
    justification: str


class LiveRecommendationItem(BaseModel):
    text: str
    confidence_pct: float
    odds: float
    set_number: int


class LiveRecommendationsResponse(BaseModel):
    items: list[LiveRecommendationItem]


@router.get("/matches/{match_id}/probability", response_model=ProbabilityResponse)
async def get_match_probability(
    match_id: UUID,
    session: AsyncSession = Depends(get_async_session),
):
    q = (
        select(Match)
        .where(Match.id == match_id)
        .options(selectinload(Match.scores))
    )
    result = await session.execute(q)
    match = result.scalar_one_or_none()
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")
    scores = [
        {"set_number": s.set_number, "home_score": s.home_score, "away_score": s.away_score}
        for s in (match.scores or [])
    ]
    fmt = MatchFormat(
        sets_to_win=getattr(match, "sets_to_win", 2),
        points_per_set=getattr(match, "points_per_set", 11),
        win_by=getattr(match, "win_by", 2),
    )
    prob = from_scores_list(scores, match_format=fmt)
    return ProbabilityResponse(
        p_home_win=prob.p_home_win,
        p_away_win=prob.p_away_win,
        p_home_current_set=prob.p_home_current_set,
        p_away_current_set=prob.p_away_current_set,
        p_home_next_set=prob.p_home_next_set,
        p_away_next_set=prob.p_away_next_set,
    )


@router.get("/matches/{match_id}/analytics", response_model=MatchAnalyticsResponse)
async def get_match_analytics(
    match_id: UUID,
    session: AsyncSession = Depends(get_async_session),
):
    """Аналитика матча: рекомендации (≥70%), сильные/слабые стороны игроков, обоснование."""
    q = (
        select(Match)
        .where(Match.id == match_id)
        .options(selectinload(Match.scores))
    )
    result = await session.execute(q)
    match = result.scalar_one_or_none()
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")

    if match.home_player_id and match.away_player_id:
        stats_home, stats_away = await get_stats_for_recommendation(
            session,
            match.home_player_id,
            match.away_player_id,
            league_id=getattr(match, "league_id", None),
            lookback_days=settings.recommendation_lookback_days,
            prefer_recent_days=getattr(settings, "recommendation_prefer_recent_days", None),
            min_matches_in_league=getattr(settings, "recommendation_min_matches_in_league", 3),
        )
    else:
        stats_home = None
        stats_away = None

    scores = [
        {"set_number": s.set_number, "home_score": s.home_score, "away_score": s.away_score}
        for s in (match.scores or [])
    ]
    has_scores = len(scores) > 0
    # Определяем завершённые сеты и текущий счёт в текущем сете
    completed_sets = []
    cur_h, cur_a = 0, 0
    if scores:
        sorted_scores = sorted(scores, key=lambda x: x.get("set_number", 0))
        for s in sorted_scores[:-1]:
            completed_sets.append((int(s.get("home_score", 0)), int(s.get("away_score", 0))))
        last = sorted_scores[-1]
        cur_h, cur_a = int(last.get("home_score", 0)), int(last.get("away_score", 0))

    if has_scores and (completed_sets or cur_h > 0 or cur_a > 0):
        fmt = MatchFormat(
            sets_to_win=getattr(match, "sets_to_win", 2),
            points_per_set=getattr(match, "points_per_set", 11),
            win_by=getattr(match, "win_by", 2),
        )
        prob = from_scores_list(scores, match_format=fmt)
        p_home_win = float(prob.p_home_win)
        p_away_win = float(prob.p_away_win)
        p_home_set1 = float(prob.p_home_current_set)
        p_away_set1 = float(prob.p_away_current_set)
        # Для второго сета до его начала используем ту же вероятность сета (из очковой модели)
        p_pt_home = float(prob.p_home_next_set or 0.5)
        p_away_pt = float(prob.p_away_next_set or 0.5)
        from app.services.probability_engine import set_win_probability_markov
        p_home_set2 = set_win_probability_markov(0, 0, p_pt_home, fmt.points_per_set, fmt.win_by)
        p_away_set2 = 1.0 - p_home_set2
    else:
        p_home_win, p_away_win, p_home_set1, p_away_set1, p_home_set2, p_away_set2 = pre_match_probs(
            stats_home, stats_away
        )

    recs = build_match_recommendations(
        p_home_win, p_away_win, p_home_set1, p_away_set1, p_home_set2, p_away_set2
    )
    home_strengths, home_weaknesses = build_strengths_weaknesses(stats_home)
    away_strengths, away_weaknesses = build_strengths_weaknesses(stats_away)
    justification = build_justification(
        recs, stats_home, stats_away, p_home_win, p_away_win, p_home_set1, p_away_set1
    )

    return MatchAnalyticsResponse(
        recommendations=[MatchRecommendationOut(text=r.text, confidence_pct=r.confidence_pct) for r in recs],
        home_strengths=home_strengths,
        home_weaknesses=home_weaknesses,
        away_strengths=away_strengths,
        away_weaknesses=away_weaknesses,
        justification=justification,
    )


MIN_ODDS_LIVE_REC = 1.3
CONFIDENCE_LIVE_REC = 0.70


@router.get("/matches/{match_id}/live-recommendations", response_model=LiveRecommendationsResponse)
async def get_live_recommendations(
    match_id: UUID,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Рекомендации в моменте только для лайв-матча: только на будущие сеты (не на текущий),
    только если коэффициент ≥ 1.3 и вероятность ≥ 70%. Чтобы зритель успел поставить на следующий сет.
    """
    q = (
        select(Match)
        .where(Match.id == match_id)
        .options(selectinload(Match.scores), selectinload(Match.odds_snapshots))
    )
    result = await session.execute(q)
    match = result.scalar_one_or_none()
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")
    if match.status != "live":
        return LiveRecommendationsResponse(items=[])

    scores = [
        {"set_number": s.set_number, "home_score": s.home_score, "away_score": s.away_score}
        for s in (match.scores or [])
    ]
    if not scores:
        return LiveRecommendationsResponse(items=[])

    fmt = MatchFormat(
        sets_to_win=getattr(match, "sets_to_win", 2),
        points_per_set=getattr(match, "points_per_set", 11),
        win_by=getattr(match, "win_by", 2),
    )
    sorted_scores = sorted(scores, key=lambda x: x.get("set_number", 0))
    current_set_number = int(sorted_scores[-1].get("set_number", 1))
    next_set_number = current_set_number + 1

    home_sets_won = sum(1 for s in sorted_scores[:-1] if int(s.get("home_score", 0)) > int(s.get("away_score", 0)))
    away_sets_won = sum(1 for s in sorted_scores[:-1] if int(s.get("away_score", 0)) > int(s.get("home_score", 0)))
    score_str = f"{home_sets_won}:{away_sets_won}"

    prob = from_scores_list(scores, match_format=fmt)
    p_pt_home = float(prob.p_home_next_set or 0.5)
    p_home_wins_next_set = set_win_probability_markov(0, 0, p_pt_home, fmt.points_per_set, fmt.win_by)
    p_away_wins_next_set = 1.0 - p_home_wins_next_set

    snapshots = match.odds_snapshots or []
    set_winner_snapshots = [
        o for o in snapshots
        if (o.market == "set_winner" or (o.market or "").startswith("92_"))
        and o.selection and f"set_{next_set_number}" in (o.selection or "").lower()
    ]
    at_score = [o for o in set_winner_snapshots if (o.score_at_snapshot or "").strip() == score_str]
    use_list = at_score if at_score else set_winner_snapshots
    if not use_list:
        return LiveRecommendationsResponse(items=[])

    home_odds_snap = None
    away_odds_snap = None
    for o in sorted(use_list, key=lambda x: (x.snapshot_time or x.timestamp or ""), reverse=True):
        sel = (o.selection or "").lower()
        if f"set_{next_set_number}_home" in sel or (f"set_{next_set_number}" in sel and "home" in sel):
            if home_odds_snap is None:
                home_odds_snap = o
        if f"set_{next_set_number}_away" in sel or (f"set_{next_set_number}" in sel and "away" in sel):
            if away_odds_snap is None:
                away_odds_snap = o

    items = []
    odds_home = float(home_odds_snap.odds) if home_odds_snap else 0.0
    odds_away = float(away_odds_snap.odds) if away_odds_snap else 0.0
    if p_home_wins_next_set >= CONFIDENCE_LIVE_REC and odds_home >= MIN_ODDS_LIVE_REC:
        items.append(LiveRecommendationItem(
            text=f"П1 выиграет {next_set_number}-й сет ({p_home_wins_next_set * 100:.0f}%)",
            confidence_pct=round(p_home_wins_next_set * 100, 1),
            odds=round(odds_home, 2),
            set_number=next_set_number,
        ))
    if p_away_wins_next_set >= CONFIDENCE_LIVE_REC and odds_away >= MIN_ODDS_LIVE_REC:
        items.append(LiveRecommendationItem(
            text=f"П2 выиграет {next_set_number}-й сет ({p_away_wins_next_set * 100:.0f}%)",
            confidence_pct=round(p_away_wins_next_set * 100, 1),
            odds=round(odds_away, 2),
            set_number=next_set_number,
        ))

    return LiveRecommendationsResponse(items=items)
