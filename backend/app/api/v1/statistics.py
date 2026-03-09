"""Statistics API: recommendations accuracy (from line/live table)."""
import logging
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.session import get_async_session
from app.models import Match, MatchRecommendation
from app.models.match_result import MatchResult
from app.models.match_score import MatchScore
from app.services.normalizer import Normalizer


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


class RecommendationStatsItem(BaseModel):
    match_id: UUID
    league_name: str = Field("", description="Название лиги")
    start_time: str
    started_at: str | None = Field(None, description="Фактическое время начала матча (ISO), если известно")
    home_name: str
    away_name: str
    recommendation_text: str
    final_score: str | None = None
    winner_name: str | None = None
    correct: bool | None = Field(None, description="True=угадали, False=не угадали, None=матч не завершён или тип прогноза не оценивается (тоталы, фора и т.д.)")
    odds_at_recommendation: float | None = Field(None, description="Коэффициент на момент появления прогноза")
    minutes_before_start: int | None = Field(None, description="Минут до начала матча, когда появился прогноз")
    created_at: str | None = Field(None, description="Дата и время добавления записи прогноза (ISO)")


class RecommendationStatsResponse(BaseModel):
    total: int = Field(description="Всего прогнозов выдано (сохранено)")
    correct: int = Field(description="Угадали (матч завершён, прогноз на победителя П1/П2 в матче или по сетам, исход совпал)")
    wrong: int = Field(description="Не угадали (матч завершён, прогноз на победителя П1/П2, исход не совпал)")
    pending: int = Field(description="Ожидают (матч не завершён или тип прогноза не оценивается — тоталы, фора и т.д.)")
    bank_profit_rub: float = Field(0.0, description="Банк при условной ставке 100 ₽ на каждый прогноз за выбранный период")
    avg_odds: float | None = Field(None, description="Средний коэффициент по всем прогнозам, где указан кф")
    cancelled_or_no_data_count: int = Field(default=0, description="Отменён + Не удалось получить данные (без результата)")
    cancelled_or_no_data_pct: float = Field(default=0.0, description="Доля отменённых/без данных в % от общего числа")
    items: list[RecommendationStatsItem] = Field(default_factory=list, description="Список прогнозов с учётом фильтров и пагинации")
    page: int = Field(description="Текущая страница")
    per_page: int = Field(description="Размер страницы")
    total_filtered: int = Field(description="Число записей после применения фильтров")
    total_pages: int = Field(description="Всего страниц")


@router.get("/recommendations", response_model=RecommendationStatsResponse)
async def get_recommendations_stats(
    session: AsyncSession = Depends(get_async_session),
    result_filter: ResultFilter = Query("all", description="all | correct | wrong | pending"),
    odds_min: float | None = Query(None, description="Минимальный коэффициент при прогнозе"),
    odds_max: float | None = Query(None, description="Максимальный коэффициент при прогнозе"),
    days: int | None = Query(None, ge=1, le=90, description="Период от текущего момента, в днях"),
    date_from: date | None = Query(None, description="Дата начала периода (YYYY-MM-DD)"),
    date_to: date | None = Query(None, description="Дата конца периода (YYYY-MM-DD)"),
    sport_key: str | None = Query(None, description="Фильтр по виду спорта (например table_tennis)"),
    page: int = Query(1, ge=1, description="Страница"),
    per_page: int = Query(20, ge=1, le=100, description="Записей на странице"),
):
    """
    Статистика прогнозов из колонки «Прогноз» (линия/лайв): все сохранённые прогнозы.
    Строка появляется сразу после появления прогноза (линия/лайв); результат — после завершения матча.
    Угадали/не угадали считается только для прогнозов на победителя (П1/П2 в матче или по сетам).
    Тоталы (ТБ/ТМ), фора и т.п. пока в «ожидают».
    """
    # Без лимита: считаем все сохранённые прогнозы (total = сколько есть)
    now = datetime.now(timezone.utc)
    since: datetime | None = None
    until: datetime | None = None
    if date_from is not None or date_to is not None:
        if date_from is None:
            date_from = date_to
        if date_to is None:
            date_to = date_from
        assert date_from is not None and date_to is not None
        if date_from > date_to:
            date_from, date_to = date_to, date_from
        since = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        until = datetime.combine(date_to, time.max, tzinfo=timezone.utc)
    elif days is not None:
        since = now - timedelta(days=days)
        until = now

    q = select(MatchRecommendation).order_by(MatchRecommendation.created_at.desc())
    if since is not None:
        q = q.where(MatchRecommendation.created_at >= since)
    if until is not None:
        q = q.where(MatchRecommendation.created_at <= until)
    if sport_key is not None and sport_key.strip():
        q = q.join(Match, MatchRecommendation.match_id == Match.id).where(Match.sport_key == sport_key.strip())

    r = await session.execute(q)
    recs = r.scalars().all()
    total = len(recs)
    rec_match_ids = [rec.match_id for rec in recs]

    matches_by_id: dict[UUID, Match] = {}
    if rec_match_ids:
        matches_q = (
            select(Match)
            .where(Match.id.in_(rec_match_ids))
            .options(
                selectinload(Match.league),
                selectinload(Match.home_player),
                selectinload(Match.away_player),
                selectinload(Match.scores),
                selectinload(Match.result).selectinload(MatchResult.winner),
            )
        )
        matches_r = await session.execute(matches_q)
        matches = matches_r.scalars().all()
        matches_by_id = {m.id: m for m in matches}

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

    # Для расчёта «банка» и среднего кф по всем прогнозам
    BANK_STAKE_RUB = 100.0
    total_odds_sum = 0.0
    total_odds_count = 0
    bank_profit = 0.0

    for rec in recs:
        match = matches_by_id.get(rec.match_id)
        if not match:
            continue

        home_name = match.home_player.name if match.home_player else "?"
        away_name = match.away_player.name if match.away_player else "?"
        league_name = match.league.name if match.league else ""
        start_time = match.start_time.isoformat() if match.start_time else ""
        started_at = match.started_at.isoformat() if getattr(match, "started_at", None) else None
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
            # До выхода матча из лайва (обычно в finished) не ставим Да/Нет.
            final_score = "В игре"
            pending += 1
        elif status_key == "finished":
            # Оцениваем рекомендации только после завершения матча.
            if set_rec is not None and match.scores:
                # Рекомендация на конкретный сет — используем MatchScore.
                set_num, set_side = set_rec
                set_score = next((s for s in match.scores if s.set_number == set_num), None)
                if set_score is not None and set_score.home_score != set_score.away_score:
                    set_winner_home = set_score.home_score > set_score.away_score
                    if _scores_swapped_vs_result(match):
                        set_winner_home = not set_winner_home
                    correct_flag = set_winner_home if set_side == "home" else (not set_winner_home)
                    if correct_flag:
                        correct += 1
                    else:
                        wrong += 1
                else:
                    pending += 1
            elif recommended is not None:
                # Рекомендация на итоговую победу П1/П2.
                if match.result and match.result.winner_id is not None:
                    finished_with_result += 1
                    winner_is_home = match.result.winner_id == match.home_player_id
                    if _scores_swapped_vs_result(match):
                        winner_is_home = not winner_is_home
                    correct_flag = winner_is_home if recommended == "home" else (not winner_is_home)
                    if correct_flag:
                        correct += 1
                    else:
                        wrong += 1
                elif match.scores:
                    # Результата в MatchResult ещё нет, но в карточке матча уже есть полный счёт по сетам —
                    # определяем победителя по MatchScore, чтобы не держать такие матчи «подвисшими».
                    home_sets = sum(1 for s in match.scores if s.home_score > s.away_score)
                    away_sets = sum(1 for s in match.scores if s.away_score > s.home_score)
                    if home_sets != away_sets:
                        winner_is_home = home_sets > away_sets
                        correct_flag = winner_is_home if recommended == "home" else (not winner_is_home)
                        if correct_flag:
                            correct += 1
                        else:
                            wrong += 1
                        finished_with_result += 1
                    else:
                        # Счёт по сетам не даёт однозначного победителя.
                        pending += 1
                else:
                    # Нет ни результата, ни счёта — ждём догрузки.
                    pending += 1

            # Финальный счёт для отображения.
            if match.result and match.result.final_score:
                final_score = match.result.final_score
                winner_name = match.result.winner_name
            elif match.scores:
                # Собираем счёт по сетам из MatchScore, если MatchResult ещё не записан.
                sets_sorted = sorted(match.scores, key=lambda s: s.set_number)
                score_parts = [f"{s.home_score}:{s.away_score}" for s in sets_sorted]
                final_score = " ".join(score_parts)
                # Если уже посчитали correct_flag по победителю, можем вывести имя победителя.
                if correct_flag is not None:
                    home_sets = sum(1 for s in sets_sorted if s.home_score > s.away_score)
                    away_sets = sum(1 for s in sets_sorted if s.away_score > s.home_score)
                    if home_sets > away_sets and match.home_player:
                        winner_name = match.home_player.name
                    elif away_sets > home_sets and match.away_player:
                        winner_name = match.away_player.name
            else:
                finished_no_result += 1
                final_score = "Не удалось получить данные"
                no_data_count += 1
        elif status_key == "scheduled":
            final_score = "Ждёт начала"
            pending += 1
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

        # Агрегируем метрики по кф и банку: учитываем только те прогнозы, где есть коэффициент.
        if odds_at is not None:
            total_odds_sum += odds_at
            total_odds_count += 1
            if correct_flag is True:
                bank_profit += BANK_STAKE_RUB * (odds_at - 1.0)
            elif correct_flag is False:
                bank_profit -= BANK_STAKE_RUB

        items.append(
            RecommendationStatsItem(
                match_id=match.id,
                league_name=league_name,
                start_time=start_time,
                started_at=started_at,
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
    avg_odds = (total_odds_sum / total_odds_count) if total_odds_count else None

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
        bank_profit_rub=round(bank_profit, 0),
        avg_odds=round(avg_odds, 2) if avg_odds is not None else None,
        cancelled_or_no_data_count=cancelled_or_no_data_count,
        cancelled_or_no_data_pct=cancelled_or_no_data_pct,
        items=page_items,
        page=page,
        per_page=per_page,
        total_filtered=total_filtered,
        total_pages=total_pages,
    )


class VipChannelStatsResponse(BaseModel):
    total: int = Field(description="Всего отправлено в VIP-канал")
    won: int = Field(description="Угадали")
    lost: int = Field(description="Не угадали")
    pending: int = Field(description="Ещё в игре")
    missed: int = Field(default=0, description="Отмена/перенос/нет данных")
    bank_profit_rub: float = Field(0.0, description="Банк при условной ставке 100 ₽ на каждый прогноз за период")
    avg_odds: float | None = Field(None, description="Средний коэффициент по прогнозам VIP-канала, если есть")


@router.get("/vip-channel", response_model=VipChannelStatsResponse)
async def get_vip_channel_stats(
    days: int = Query(7, ge=1, le=90),
):
    """Статистика VIP-канала (платный ТГ): сколько отправлено, сколько зашло за последние N дней."""
    from app.db.session import async_session_maker
    from app.services.signal_delivery_service import get_paid_channel_stats_since

    since = datetime.now(timezone.utc) - timedelta(days=days)
    stats = await get_paid_channel_stats_since(async_session_maker, since)
    return VipChannelStatsResponse(
        total=stats["total"],
        won=stats["won"],
        lost=stats["lost"],
        pending=stats["pending"],
        missed=stats["missed"],
        bank_profit_rub=stats.get("bank_profit_rub", 0.0),
        avg_odds=stats.get("avg_odds"),
    )


class FreeChannelStatsResponse(BaseModel):
    total: int = Field(description="Всего отправлено в бесплатный канал")
    won: int = Field(description="Угадали")
    lost: int = Field(description="Не угадали")
    pending: int = Field(description="Ещё в игре")
    missed: int = Field(default=0, description="Отмена/перенос/нет данных")
    bank_profit_rub: float = Field(0.0, description="Банк при условной ставке 100 ₽ на каждый прогноз за период")
    avg_odds: float | None = Field(None, description="Средний коэффициент по прогнозам бесплатного канала, если есть")


@router.get("/free-channel", response_model=FreeChannelStatsResponse)
async def get_free_channel_stats(
    days: int = Query(7, ge=1, le=90),
):
    """Статистика бесплатного канала (публичный ТГ): сколько отправлено, сколько зашло за последние N дней, плюс расчёт банка."""
    from app.db.session import async_session_maker
    from app.services.signal_delivery_service import get_free_channel_stats_since

    since = datetime.now(timezone.utc) - timedelta(days=days)
    stats = await get_free_channel_stats_since(async_session_maker, since)
    return FreeChannelStatsResponse(
        total=stats["total"],
        won=stats["won"],
        lost=stats["lost"],
        pending=stats["pending"],
        missed=stats["missed"],
        bank_profit_rub=stats.get("bank_profit_rub", 0.0),
        avg_odds=stats.get("avg_odds"),
    )
