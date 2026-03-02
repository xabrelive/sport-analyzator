"""Statistics API: recommendations accuracy (from line/live table)."""
import logging
from datetime import timezone
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_async_session
from app.models import Match, MatchRecommendation
from app.models.match_result import MatchResult
from app.models.match_score import MatchScore
from app.models.odds_snapshot import OddsSnapshot


router = APIRouter()
logger = logging.getLogger(__name__)

ResultFilter = Literal["all", "correct", "wrong", "pending"]


def _recommended_winner_side(text: str) -> str | None:
    """
    'home' | 'away' | None.
    Распознаёт рекомендации на победителя: П1/П2 победа в матче или по сетам.
    """
    if not text:
        return None
    t = text.lower()
    if "п1" in t and ("победа" in t or "матче" in t or "по сетам" in t or "сетам" in t):
        return "home"
    if "п2" in t and ("победа" in t or "матче" in t or "по сетам" in t or "сетам" in t):
        return "away"
    return None


def _recommended_set_winner(text: str) -> tuple[int, str] | None:
    """
    (set_number, 'home'|'away') | None.
    Распознаёт рекомендации вида «П1/П2 выиграет 1-й/2-й/... сет».
    """
    if not text:
        return None
    t = text.lower()
    side = None
    if "п1" in t and ("выиграет" in t or "сет" in t):
        side = "home"
    elif "п2" in t and ("выиграет" in t or "сет" in t):
        side = "away"
    if side is None:
        return None
    set_num = None
    if "1-й сет" in t or "1 сет" in t or "первый сет" in t:
        set_num = 1
    elif "2-й сет" in t or "второй сет" in t or "2 сет" in t:
        set_num = 2
    elif "3-й сет" in t or "третий сет" in t or "3 сет" in t:
        set_num = 3
    elif "4-й сет" in t or "4 сет" in t:
        set_num = 4
    elif "5-й сет" in t or "5 сет" in t:
        set_num = 5
    if set_num is not None:
        return (set_num, side)
    return None


def _recommendation_side(text: str) -> str | None:
    """'home' | 'away' | None по тексту рекомендации (П1/П2)."""
    if not text:
        return None
    t = text.lower()
    if "п1" in t:
        return "home"
    if "п2" in t:
        return "away"
    return None


def _scores_swapped_vs_result(match: Match) -> bool:
    """
    Если по MatchScore победил один игрок (больше сетов), а в MatchResult.winner_id — другой,
    считаем, что счёт по сетам записан в перепутанном порядке (home/away).
    """
    if not match.result or match.result.winner_id is None or not match.scores:
        return False
    home_sets = sum(1 for s in match.scores if s.home_score > s.away_score)
    away_sets = sum(1 for s in match.scores if s.away_score > s.home_score)
    if home_sets == away_sets:
        return False
    winner_is_home = match.result.winner_id == match.home_player_id
    scores_say_home_won = home_sets > away_sets
    return winner_is_home != scores_say_home_won


async def _backfill_recommendation_odds(session: AsyncSession) -> None:
    """Подставляет первый полученный коэффициент по событию для рекомендаций с пустым odds_at_recommendation."""
    q = select(MatchRecommendation).where(MatchRecommendation.odds_at_recommendation.is_(None))
    r = await session.execute(q)
    recs = r.scalars().all()
    for rec in recs:
        side = _recommendation_side(rec.recommendation_text)
        if not side:
            continue
        snap_q = (
            select(OddsSnapshot)
            .where(
                OddsSnapshot.match_id == rec.match_id,
                OddsSnapshot.market.in_(["winner", "92_1", "win"]),
            )
            .order_by(
                OddsSnapshot.snapshot_time.asc().nullslast(),
                OddsSnapshot.timestamp.asc().nullslast(),
            )
            .limit(50)
        )
        snap_r = await session.execute(snap_q)
        snaps = snap_r.scalars().all()
        odds_val = None
        for s in snaps:
            sel = (s.selection or "").lower()
            if side == "home" and sel in ("home", "1"):
                odds_val = s.odds
                break
            if side == "away" and sel in ("away", "2"):
                odds_val = s.odds
                break
        if odds_val is not None:
            await session.execute(
                update(MatchRecommendation)
                .where(MatchRecommendation.id == rec.id)
                .values(odds_at_recommendation=odds_val)
            )
    if recs:
        await session.commit()


class RecommendationStatsItem(BaseModel):
    match_id: UUID
    league_name: str = Field("", description="Название лиги")
    start_time: str
    home_name: str
    away_name: str
    recommendation_text: str
    final_score: str | None = None
    winner_name: str | None = None
    correct: bool | None = Field(None, description="True=угадали, False=не угадали, None=матч не завершён или тип рекомендации не оценивается (тоталы, фора и т.д.)")
    odds_at_recommendation: float | None = Field(None, description="Коэффициент на момент появления рекомендации")
    minutes_before_start: int | None = Field(None, description="Минут до начала матча, когда появилась рекомендация")
    created_at: str | None = Field(None, description="Дата и время добавления записи рекомендации (ISO)")


class RecommendationStatsResponse(BaseModel):
    total: int = Field(description="Всего рекомендаций выдано (сохранено)")
    correct: int = Field(description="Угадали (матч завершён, рекомендация на победителя П1/П2 в матче или по сетам, исход совпал)")
    wrong: int = Field(description="Не угадали (матч завершён, рекомендация на победителя П1/П2, исход не совпал)")
    pending: int = Field(description="Ожидают (матч не завершён или тип рекомендации не оценивается — тоталы, фора и т.д.)")
    cancelled_or_no_data_count: int = Field(default=0, description="Отменён + Не удалось получить данные (без результата)")
    cancelled_or_no_data_pct: float = Field(default=0.0, description="Доля отменённых/без данных в % от общего числа")
    items: list[RecommendationStatsItem] = Field(default_factory=list, description="Список рекомендаций с учётом фильтров и пагинации")
    page: int = Field(description="Текущая страница")
    per_page: int = Field(description="Размер страницы")
    total_filtered: int = Field(description="Число записей после применения фильтров")
    total_pages: int = Field(description="Всего страниц")


@router.get("/recommendations", response_model=RecommendationStatsResponse)
async def get_recommendations_stats(
    session: AsyncSession = Depends(get_async_session),
    result_filter: ResultFilter = Query("all", description="all | correct | wrong | pending"),
    odds_min: float | None = Query(None, description="Минимальный коэффициент при рекомендации"),
    odds_max: float | None = Query(None, description="Максимальный коэффициент при рекомендации"),
    page: int = Query(1, ge=1, description="Страница"),
    per_page: int = Query(20, ge=1, le=100, description="Записей на странице"),
):
    """
    Статистика рекомендаций из колонки «Рекомендация» (линия/лайв): все сохранённые рекомендации.
    Строка появляется сразу после появления рекомендации (линия/лайв); результат — после завершения матча.
    Угадали/не угадали считается только для рекомендаций на победителя (П1/П2 в матче или по сетам).
    Тоталы (ТБ/ТМ), фора и т.п. пока в «ожидают».
    """
    await _backfill_recommendation_odds(session)

    # Без лимита: считаем все сохранённые рекомендации (total = сколько есть)
    q = (
        select(MatchRecommendation)
        .order_by(MatchRecommendation.created_at.desc())
    )
    r = await session.execute(q)
    recs = r.scalars().all()
    total = len(recs)

    correct = 0
    wrong = 0
    pending = 0
    cancelled_count = 0
    no_data_count = 0
    items: list[RecommendationStatsItem] = []
    # Диагностика по статусам (для логов)
    by_status: dict[str, int] = {}
    finished_with_result = 0
    finished_no_result = 0

    for rec in recs:
        match_q = (
            select(Match)
            .where(Match.id == rec.match_id)
            .options(
                selectinload(Match.league),
                selectinload(Match.home_player),
                selectinload(Match.away_player),
                selectinload(Match.scores),
                selectinload(Match.result).selectinload(MatchResult.winner),
            )
        )
        match_r = await session.execute(match_q)
        match = match_r.scalar_one_or_none()
        if not match:
            continue

        home_name = match.home_player.name if match.home_player else "?"
        away_name = match.away_player.name if match.away_player else "?"
        league_name = match.league.name if match.league else ""
        start_time = match.start_time.isoformat() if match.start_time else ""
        final_score = None
        winner_name = None
        correct_flag: bool | None = None

        recommended = _recommended_winner_side(rec.recommendation_text)
        set_rec = _recommended_set_winner(rec.recommendation_text)
        status_key = (match.status or "none").strip().lower()
        by_status[status_key] = by_status.get(status_key, 0) + 1
        if status_key == "cancelled":
            final_score = "Отменён"
            cancelled_count += 1
            pending += 1
        elif status_key == "postponed":
            final_score = "Перенесён"
            pending += 1
        elif status_key == "live":
            final_score = "В игре"
            pending += 1
        elif status_key == "finished" and match.result:
            finished_with_result += 1
            final_score = match.result.final_score
            winner_name = match.result.winner_name
            # Сначала проверяем рекомендацию на победу в конкретном сете
            if set_rec is not None and match.scores:
                set_num, set_side = set_rec
                set_score = next((s for s in match.scores if s.set_number == set_num), None)
                if set_score is not None:
                    set_winner_home = set_score.home_score > set_score.away_score
                    # Если счёт по сетам противоречит победителю матча — считаем, что home/away перепутаны в счёте
                    if _scores_swapped_vs_result(match):
                        set_winner_home = not set_winner_home
                    if set_side == "home":
                        correct_flag = set_winner_home
                    else:
                        correct_flag = not set_winner_home
                    if correct_flag:
                        correct += 1
                    else:
                        wrong += 1
                else:
                    pending += 1
            elif recommended is not None and match.result.winner_id is not None:
                winner_is_home = match.result.winner_id == match.home_player_id
                # Если счёт по сетам противоречит winner_id — home/away перепутаны, реальный победитель противоположный
                if _scores_swapped_vs_result(match):
                    winner_is_home = not winner_is_home
                if recommended == "home":
                    correct_flag = winner_is_home
                else:
                    correct_flag = not winner_is_home
                if correct_flag:
                    correct += 1
                else:
                    wrong += 1
            else:
                pending += 1
        else:
            # scheduled — ждёт начала; finished без результата — не удалось получить данные
            if status_key == "finished":
                finished_no_result += 1
            if status_key == "scheduled":
                final_score = "Ждёт начала"
            else:
                final_score = "Не удалось получить данные"
                no_data_count += 1
            pending += 1

        odds_at = float(rec.odds_at_recommendation) if rec.odds_at_recommendation is not None else None
        minutes_before: int | None = None
        if match.start_time and rec.created_at:
            start_naive = match.start_time.replace(tzinfo=timezone.utc) if match.start_time.tzinfo is None else match.start_time
            created_naive = rec.created_at.replace(tzinfo=timezone.utc) if rec.created_at.tzinfo is None else rec.created_at
            delta_seconds = (start_naive - created_naive).total_seconds()
            minutes_before = int(round(delta_seconds / 60))

        items.append(
            RecommendationStatsItem(
                match_id=match.id,
                league_name=league_name,
                start_time=start_time,
                home_name=home_name,
                away_name=away_name,
                recommendation_text=rec.recommendation_text,
                final_score=final_score,
                winner_name=winner_name,
                correct=correct_flag,
                odds_at_recommendation=odds_at,
                minutes_before_start=minutes_before,
                created_at=rec.created_at.isoformat() if rec.created_at else None,
            )
        )

    # Сортировка по времени начала матча: сначала самые новые, ниже самые старые
    items.sort(key=lambda x: x.start_time or "", reverse=True)

    # Фильтрация
    filtered: list[RecommendationStatsItem] = []
    for item in items:
        if result_filter != "all":
            if result_filter == "correct" and item.correct is not True:
                continue
            if result_filter == "wrong" and item.correct is not False:
                continue
            if result_filter == "pending" and item.correct is not None:
                continue
        if odds_min is not None and (item.odds_at_recommendation is None or item.odds_at_recommendation < odds_min):
            continue
        if odds_max is not None and (item.odds_at_recommendation is None or item.odds_at_recommendation > odds_max):
            continue
        filtered.append(item)

    total_filtered = len(filtered)
    total_pages = (total_filtered + per_page - 1) // per_page if (per_page and total_filtered) else 0
    start = (page - 1) * per_page
    page_items = filtered[start : start + per_page]

    cancelled_or_no_data_count = cancelled_count + no_data_count
    cancelled_or_no_data_pct = round((cancelled_or_no_data_count / total * 100.0), 1) if total > 0 else 0.0

    logger.info(
        "recommendations_stats total=%d correct=%d wrong=%d pending=%d filtered=%d page=%d by_status=%s finished_with_result=%d finished_no_result=%d",
        total,
        correct,
        wrong,
        pending,
        total_filtered,
        page,
        by_status,
        finished_with_result,
        finished_no_result,
    )
    return RecommendationStatsResponse(
        total=total,
        correct=correct,
        wrong=wrong,
        pending=pending,
        cancelled_or_no_data_count=cancelled_or_no_data_count,
        cancelled_or_no_data_pct=cancelled_or_no_data_pct,
        items=page_items,
        page=page,
        per_page=per_page,
        total_filtered=total_filtered,
        total_pages=total_pages,
    )
