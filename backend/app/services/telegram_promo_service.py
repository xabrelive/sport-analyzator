"""Рекламные посты в Telegram по расписанию: статистика за вчера (12:00 и 19:00 МСК)."""
import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models import Match, MatchRecommendation, User
from app.models.scheduled_telegram_post import ScheduledTelegramPost
from app.services.signal_delivery_service import (
    _recommendation_correct_flag,
    _recommended_set_winner,
    _recommended_winner_side,
    _scores_swapped_vs_result,
)
from app.models.match_result import MatchResult
from app.models.match_score import MatchScore
from app.services.telegram_sender import send_telegram_message

logger = logging.getLogger(__name__)

MSK = ZoneInfo("Europe/Moscow")
BET_STAKE_RUB = 100


def _yesterday_msk() -> date:
    return (datetime.now(MSK) - timedelta(days=1)).date()


def _match_date_msk(start_time: datetime) -> date:
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    return start_time.astimezone(MSK).date()


async def get_yesterday_recommendations_stats(session_maker):
    """
    Статистика по рекомендациям за вчера (по дате матча в МСК).
    Возвращает: total, won, lost, pending, avg_odds, bank_profit_rub (при ставке 100 ₽ на каждый).
    """
    yesterday = _yesterday_msk()
    start_msk = datetime.combine(yesterday, datetime.min.time(), tzinfo=MSK)
    end_msk = datetime.combine(yesterday, datetime.max.time().replace(microsecond=0), tzinfo=MSK)
    start_utc = start_msk.astimezone(timezone.utc)
    end_utc = end_msk.astimezone(timezone.utc)

    async with session_maker() as session:
        q = (
            select(MatchRecommendation)
            .join(Match, MatchRecommendation.match_id == Match.id)
            .where(
                Match.status == "finished",
                Match.start_time >= start_utc,
                Match.start_time <= end_utc,
            )
            .options(
                selectinload(MatchRecommendation.match).selectinload(Match.result).selectinload(MatchResult.winner),
                selectinload(MatchRecommendation.match).selectinload(Match.scores),
            )
        )
        recs = list((await session.execute(q)).scalars().unique().all())

    total = len(recs)
    won = lost = pending = 0
    odds_sum = 0.0
    odds_count = 0
    bank_profit = 0.0

    for rec in recs:
        match = rec.match
        correct = _recommendation_correct_flag(rec, match)
        odds = float(rec.odds_at_recommendation) if rec.odds_at_recommendation is not None else None
        if odds is not None:
            odds_sum += odds
            odds_count += 1
        if correct is True:
            won += 1
            if odds is not None:
                bank_profit += BET_STAKE_RUB * (odds - 1)
            else:
                bank_profit += 0
        elif correct is False:
            lost += 1
            bank_profit -= BET_STAKE_RUB
        else:
            pending += 1

    avg_odds = (odds_sum / odds_count) if odds_count else None
    return {
        "total": total,
        "won": won,
        "lost": lost,
        "pending": pending,
        "avg_odds": round(avg_odds, 2) if avg_odds is not None else None,
        "bank_profit_rub": round(bank_profit, 0),
        "date_str": yesterday.strftime("%d.%m.%Y"),
    }


async def get_yesterday_recommendations_stats_by_sport(session_maker):
    """
    То же за вчера, но с разбивкой по видам спорта (sport_key).
    Возвращает: date_str, sports: [{ sport_key, total, won, lost, pending, avg_odds, bank_profit_rub }], totals.
    """
    yesterday = _yesterday_msk()
    start_msk = datetime.combine(yesterday, datetime.min.time(), tzinfo=MSK)
    end_msk = datetime.combine(yesterday, datetime.max.time().replace(microsecond=0), tzinfo=MSK)
    start_utc = start_msk.astimezone(timezone.utc)
    end_utc = end_msk.astimezone(timezone.utc)

    async with session_maker() as session:
        q = (
            select(MatchRecommendation)
            .join(Match, MatchRecommendation.match_id == Match.id)
            .where(
                Match.status == "finished",
                Match.start_time >= start_utc,
                Match.start_time <= end_utc,
            )
            .options(
                selectinload(MatchRecommendation.match).selectinload(Match.result).selectinload(MatchResult.winner),
                selectinload(MatchRecommendation.match).selectinload(Match.scores),
            )
        )
        recs = list((await session.execute(q)).scalars().unique().all())

    by_sport: dict[str, dict] = {}
    sport_names = {"table_tennis": "Настольный теннис", "tennis": "Теннис"}

    for rec in recs:
        match = rec.match
        sk = getattr(match, "sport_key", None) or "other"
        if sk not in by_sport:
            by_sport[sk] = {"total": 0, "won": 0, "lost": 0, "pending": 0, "odds_sum": 0.0, "odds_count": 0, "bank_profit": 0.0}
        correct = _recommendation_correct_flag(rec, match)
        odds = float(rec.odds_at_recommendation) if rec.odds_at_recommendation is not None else None
        by_sport[sk]["total"] += 1
        if odds is not None:
            by_sport[sk]["odds_sum"] += odds
            by_sport[sk]["odds_count"] += 1
        if correct is True:
            by_sport[sk]["won"] += 1
            by_sport[sk]["bank_profit"] += BET_STAKE_RUB * (odds - 1) if odds else 0
        elif correct is False:
            by_sport[sk]["lost"] += 1
            by_sport[sk]["bank_profit"] -= BET_STAKE_RUB
        else:
            by_sport[sk]["pending"] += 1

    sports = []
    for sk, d in sorted(by_sport.items()):
        avg = (d["odds_sum"] / d["odds_count"]) if d["odds_count"] else None
        sports.append({
            "sport_key": sk,
            "sport_name": sport_names.get(sk, sk),
            "total": d["total"],
            "won": d["won"],
            "lost": d["lost"],
            "pending": d["pending"],
            "avg_odds": round(avg, 2) if avg is not None else None,
            "bank_profit_rub": round(d["bank_profit"], 0),
        })
    total_all = sum(d["total"] for d in by_sport.values())
    won_all = sum(d["won"] for d in by_sport.values())
    lost_all = sum(d["lost"] for d in by_sport.values())
    bank_all = sum(d["bank_profit"] for d in by_sport.values())
    return {
        "date_str": yesterday.strftime("%d.%m.%Y"),
        "sports": sports,
        "total": total_all,
        "won": won_all,
        "lost": lost_all,
        "bank_profit_rub": round(bank_all, 0),
    }


def _site_url() -> str:
    base = (settings.frontend_public_url or settings.frontend_url or "").rstrip("/")
    return base or "https://pingwin.pro"


def build_daily_stats_12_text(stats: dict) -> str:
    """Текст поста в 12:00: общая статистика за вчера, одинары, экспресс (пока заглушка), банк, ссылка."""
    date_str = stats.get("date_str", "")
    total = stats.get("total", 0)
    won = stats.get("won", 0)
    lost = stats.get("lost", 0)
    pending = stats.get("pending", 0)
    avg_odds = stats.get("avg_odds")
    bank = stats.get("bank_profit_rub", 0)
    url = _site_url()
    avg_line = f"{avg_odds:.2f}" if avg_odds is not None else "—"
    lines = [
        f"📊 По нашей аналитике за вчера ({date_str})",
        "",
        "Статистика прогнозов",
        "Одинарных:",
        f"  всего {total}",
        f"  угадано {won}",
        f"  проиграно {lost}",
        f"  средний кф {avg_line}",
        "",
        "Экспрессов: пока нет данных",
        "",
        f"При ставке по {BET_STAKE_RUB} ₽ на каждый прогноз за вчера (00:00–23:59) банк {bank:+.0f} ₽.",
        "",
        f"🔗 {url}",
        "Перейдите на сайт и оформите доступ в VIP‑канал — получайте прогнозы первыми.",
    ]
    return "\n".join(lines)


def build_daily_stats_19_text(stats_by_sport: dict) -> str:
    """Текст поста в 19:00: по видам спорта за вчера, без экспрессов, ссылка."""
    date_str = stats_by_sport.get("date_str", "")
    sports = stats_by_sport.get("sports", [])
    total = stats_by_sport.get("total", 0)
    won = stats_by_sport.get("won", 0)
    lost = stats_by_sport.get("lost", 0)
    bank = stats_by_sport.get("bank_profit_rub", 0)
    url = _site_url()
    lines = [
        f"📊 Аналитика за вчера по видам спорта ({date_str})",
        "",
    ]
    for s in sports:
        avg = s.get("avg_odds")
        avg_line = f"{avg:.2f}" if avg is not None else "—"
        lines.append(f"🏓 {s.get('sport_name', s.get('sport_key', ''))}")
        lines.append(f"  всего {s['total']} · угадано {s['won']} · проиграно {s['lost']} · ср. кф {avg_line}")
        lines.append("")
    lines.append(f"Итого: {total} прогнозов, угадано {won}, проиграно {lost}. Банк при ставке {BET_STAKE_RUB} ₽/прогноз: {bank:+.0f} ₽.")
    lines.append("")
    lines.append(f"🔗 {url}")
    lines.append("Оформите доступ в VIP‑канал на сайте.")
    return "\n".join(lines)


async def send_scheduled_post(session_maker, post, body: str) -> bool:
    """Отправить пост в канал или в личку подписчикам бота."""
    target = (post.target or "").strip()
    if target == "paid_channel":
        chat_id = (settings.telegram_signals_paid_chat_id or "").strip()
        if not chat_id:
            logger.warning("No paid channel chat_id")
            return False
        return send_telegram_message(chat_id, body, parse_mode=None, disable_web_page_preview=False)
    if target == "free_channel":
        chat_id = (settings.telegram_signals_chat_id or "").strip()
        if not chat_id:
            logger.warning("No free channel chat_id")
            return False
        return send_telegram_message(chat_id, body, parse_mode=None, disable_web_page_preview=False)
    if target == "bot_dm":
        async with session_maker() as session:
            r = await session.execute(
                select(User.telegram_id).where(
                    User.telegram_id.isnot(None),
                    User.is_blocked == False,
                )
            )
            user_ids = [row[0] for row in r.all()]
        sent = 0
        for tid in user_ids:
            if send_telegram_message(tid, body, parse_mode=None, disable_web_page_preview=False):
                sent += 1
        logger.info("Scheduled post %s sent to %d users (bot_dm)", post.id, sent)
        return sent > 0
    logger.warning("Unknown target %s for scheduled post %s", target, post.id)
    return False


def _current_slot_msk() -> str:
    """Текущий 15-минутный слот в МСК (HH:MM), чтобы не пропустить пост при запуске в 12:01."""
    now = datetime.now(MSK)
    slot_min = (now.hour * 60 + now.minute) // 15 * 15
    h, m = slot_min // 60, slot_min % 60
    return f"{h:02d}:{m:02d}"


def _last_sent_was_today(post: ScheduledTelegramPost) -> bool:
    """Проверяет, что last_sent_at пришёлся на сегодня по МСК (чтобы не слать дважды в день)."""
    if not post.last_sent_at:
        return False
    sent = post.last_sent_at
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=timezone.utc)
    return sent.astimezone(MSK).date() == datetime.now(MSK).date()


async def run_scheduled_posts(session_maker) -> int:
    """
    Запускать по расписанию (например каждые 15 мин). Проверяет посты с send_at_time_msk == текущее время МСК,
    которые ещё не отправлялись сегодня; для шаблонов подставляет статистику, отправляет, обновляет last_sent_at.
    Возвращает количество отправленных постов.
    """
    slot_msk = _current_slot_msk()

    async with session_maker() as session:
        q = (
            select(ScheduledTelegramPost)
            .where(
                ScheduledTelegramPost.is_active == True,
                ScheduledTelegramPost.send_at_time_msk == slot_msk,
            )
        )
        posts = list((await session.execute(q)).scalars().all())

    sent_count = 0
    for post in posts:
        if _last_sent_was_today(post):
            continue
        body: str | None = None
        if post.template_type == "daily_stats_12":
            stats = await get_yesterday_recommendations_stats(session_maker)
            body = build_daily_stats_12_text(stats)
        elif post.template_type == "daily_stats_19_sport":
            stats = await get_yesterday_recommendations_stats_by_sport(session_maker)
            body = build_daily_stats_19_text(stats)
        elif post.body:
            body = post.body
        if not body:
            logger.warning("Scheduled post %s has no body and no template", post.id)
            continue
        ok = await send_scheduled_post(session_maker, post, body)
        if ok:
            from sqlalchemy import update
            async with session_maker() as session:
                await session.execute(
                    update(ScheduledTelegramPost)
                    .where(ScheduledTelegramPost.id == post.id)
                    .values(last_sent_at=datetime.now(timezone.utc))
                )
                await session.commit()
            sent_count += 1
            logger.info("Scheduled post %s (%s) sent to %s", post.id, post.name, post.target)
    return sent_count
