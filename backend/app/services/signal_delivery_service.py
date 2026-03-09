"""Рассылка сигналов по новым прогнозам: батч за 5 минут, Telegram и/или email."""
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models import Match, MatchRecommendation, User, UserSubscription
from app.models.match_result import MatchResult
from app.models.match_score import MatchScore
from app.models.user_signal_delivery import UserSignalDelivery
from app.models.user_subscription import AccessType, SubscriptionScope
from app.services.email import send_signal_email
from app.services.telegram_sender import send_telegram_message, send_telegram_message_return_id, send_telegram_reply

logger = logging.getLogger(__name__)

SIGNALS_BATCH_WINDOW_MINUTES = 30
SIGNALS_DM_THROTTLE_MINUTES = 30
# Если до начала матча меньше этого времени — отправляем сразу, не дожидаясь получасового батча
URGENT_MINUTES_BEFORE_START = 30
# Максимальный возраст неотправленных рекомендаций для загрузки (дней), чтобы все прогнозы из статистики доходили
MAX_UNSENT_AGE_DAYS = 7

# Размер условной ставки для расчёта «банка» в статистике каналов и рекомендаций.
CHANNEL_BET_STAKE_RUB = 100


def _format_dt(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%d.%m.%Y %H:%M UTC")


def _match_card_url(match_id: Any) -> str:
    base = (settings.frontend_public_url or settings.frontend_url or "").rstrip("/")
    return f"{base}/match/{match_id}"


def _match_analytics_link(match_id: Any, use_html: bool) -> str:
    """Ссылка на аналитику матча: в HTML — кликабельный текст «Аналитика матча», в email — URL."""
    url = _match_card_url(match_id)
    if use_html:
        return f'<a href="{_html_escape(url)}">Аналитика матча</a>'
    return url


def _html_escape(s: str) -> str:
    if not s:
        return ""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _format_starts_in(start_time: datetime, now_utc: datetime) -> str:
    """Текст «через X мин» или «через X ч Y мин» от now_utc до start_time."""
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    delta = start_time - now_utc
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        return "уже начался"
    if total_seconds < 60:
        return "через минуту"
    minutes = total_seconds // 60
    if minutes < 60:
        return f"через {minutes} мин"
    hours = minutes // 60
    mins = minutes % 60
    if mins == 0:
        return f"через {hours} ч"
    return f"через {hours} ч {mins} мин"


def _is_set_recommendation(text: str) -> bool:
    """Прогноз по сетам (1-й сет, 2-й сет и т.д.) — в каналы при live не отправляем."""
    return text is not None and "сет" in text.lower()


@dataclass
class _SignalItem:
    rec_id: Any
    start_time: datetime
    home_name: str
    away_name: str
    recommendation_text: str
    odds_at_recommendation: float | None
    match_id: Any
    sport_key: str | None  # for subscription scope: one_sport / multiple / all
    is_live: bool = False  # матч уже в лайве — в сообщении помечаем LIVE; прогноз по сетам в каналы не шлём
    league_name: str = ""  # лига для отображения в сообщении


def _signal_footer(use_html: bool) -> str:
    """Подпись внизу сообщения: pingwin.pro — аналитический сервис."""
    base = (settings.frontend_public_url or settings.frontend_url or "").rstrip("/")
    domain = base.replace("https://", "").replace("http://", "").split("/")[0] if base else "pingwin.pro"
    if use_html:
        return f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n📊 <i>{domain} — аналитический сервис</i>"
    return f"\n—\n{domain} — аналитический сервис"


def _build_signal_message_text(items: list[_SignalItem], now_utc: datetime | None = None, use_html: bool = True, title_line: str | None = None) -> str:
    """Формирует текст сообщения. title_line — опциональная первая строка (например «⏰ Срочно: матч скоро»)."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    lines: list[str] = []
    if title_line:
        lines.append(title_line)
        lines.append("")
    for it in items:
        if lines:
            lines.append("")
        starts_in = _format_starts_in(it.start_time, now_utc)
        if it.league_name:
            lines.append(f"🏆 {it.league_name}")
        lines.append(_format_dt(it.start_time))
        lines.append(f"⏱ {starts_in}")
        pair_line = f"{_html_escape(it.home_name) if use_html else it.home_name} — {_html_escape(it.away_name) if use_html else it.away_name}"
        if it.is_live:
            pair_line += " • LIVE"
        if use_html:
            pair_line = f"<b>{pair_line}</b>"
        lines.append(pair_line)
        kf = f"Кф: {it.odds_at_recommendation:.2f}" if it.odds_at_recommendation is not None else "Кф: —"
        lines.append(kf)
        pred = _html_escape(it.recommendation_text) if use_html else it.recommendation_text
        if use_html:
            lines.append(f"<b>Прогноз:</b> {pred}")
        else:
            lines.append(f"Прогноз: {pred}")
        lines.append(_match_analytics_link(it.match_id, use_html))
    lines.append("")
    lines.append(_signal_footer(use_html))
    return "\n".join(lines).strip()


async def _load_unsent_items_and_rec_ids(session_maker, window_minutes: int | None = None):
    """
    Загружает неотправленные рекомендации.
    Если window_minutes задан — только созданные за последние window_minutes.
    Если None — все с signals_sent_at IS NULL за последние MAX_UNSENT_AGE_DAYS дней (чтобы доходили все прогнозы из статистики).
    Возвращает (items, rec_ids).
    """
    now_utc = datetime.now(timezone.utc)
    if window_minutes is not None:
        since = now_utc - timedelta(minutes=window_minutes)
    else:
        since = now_utc - timedelta(days=MAX_UNSENT_AGE_DAYS)
    items: list[_SignalItem] = []
    rec_ids: list[Any] = []
    async with session_maker() as session:
        q = (
            select(MatchRecommendation)
            .join(Match, MatchRecommendation.match_id == Match.id)
            .where(
                MatchRecommendation.signals_sent_at.is_(None),
                MatchRecommendation.created_at >= since,
                # Шлём сигналы по всем матчам, кроме отменённых/перенесённых,
                # даже если матч уже завершён (задержка воркера) — результат
                # пользователь всё равно получит отдельным сообщением.
                Match.status.notin_(["cancelled", "postponed"]),
            )
            .options(
                selectinload(MatchRecommendation.match).selectinload(Match.home_player),
                selectinload(MatchRecommendation.match).selectinload(Match.away_player),
                selectinload(MatchRecommendation.match).selectinload(Match.league),
            )
        )
        recs = (await session.execute(q)).scalars().all()
        for rec in recs:
            match = rec.match
            if not match or not match.home_player or not match.away_player:
                continue
            is_live = getattr(match, "status", None) == "live"
            league_name = (match.league.name if match.league else "") or ""
            items.append(
                _SignalItem(
                    rec_id=rec.id,
                    start_time=match.start_time,
                    home_name=match.home_player.name,
                    away_name=match.away_player.name,
                    recommendation_text=rec.recommendation_text,
                    odds_at_recommendation=float(rec.odds_at_recommendation) if rec.odds_at_recommendation is not None else None,
                    match_id=match.id,
                    sport_key=getattr(match, "sport_key", None),
                    is_live=is_live,
                    league_name=league_name,
                )
            )
            rec_ids.append(rec.id)
    return items, rec_ids


def _allowed_sport_keys_for_user(subs: list) -> frozenset[str] | None:
    """
    По подпискам пользователя на сигналы определяет, какие спорты ему доступны.
    - Если есть подписка scope=all → None (все спорты).
    - Иначе объединение sport_key по подпискам scope=one_sport (один спорт или несколько).
    """
    has_all = any(getattr(s, "scope", None) == SubscriptionScope.ALL.value for s in subs)
    if has_all:
        return None
    keys = set()
    for s in subs:
        if getattr(s, "scope", None) == SubscriptionScope.ONE_SPORT.value and getattr(s, "sport_key", None):
            keys.add(s.sport_key)
    return frozenset(keys) if keys else frozenset()


async def _get_users_with_signals_delivery(session_maker) -> list[tuple[User, frozenset[str] | None]]:
    """
    Пользователи, которым отправляем личные уведомления (TG/почта) о новых рекомендациях:
    - активная подписка на сигналы (valid_until >= сегодня);
    - хотя бы один канал включён (signal_via_telegram или signal_via_email).
    Подключённый Telegram не обязателен для почты; для TG нужен telegram_id.
    Возвращает список (user, allowed_sport_keys): None = все спорты, иначе только перечисленные.
    """
    today = date.today()
    async with session_maker() as session:
        q = (
            select(User)
            .join(UserSubscription, User.id == UserSubscription.user_id)
            .where(
                User.is_blocked == False,
                UserSubscription.access_type == AccessType.SIGNALS.value,
                UserSubscription.valid_until >= today,
                (User.signal_via_telegram == True) | (User.signal_via_email == True),
            )
            .distinct()
        )
        users = [u[0] for u in (await session.execute(q)).all()]
        if not users:
            return []
        user_ids = [u.id for u in users]
        subs_q = select(UserSubscription).where(
            UserSubscription.user_id.in_(user_ids),
            UserSubscription.access_type == AccessType.SIGNALS.value,
            UserSubscription.valid_until >= today,
        )
        subs = (await session.execute(subs_q)).scalars().all()
        subs_by_user: dict[Any, list[Any]] = {}
        for s in subs:
            subs_by_user.setdefault(s.user_id, []).append(s)
        return [(u, _allowed_sport_keys_for_user(subs_by_user.get(u.id, []))) for u in users]


async def _last_telegram_dm_sent_by_user(session_maker, user_ids: list) -> dict[Any, datetime]:
    """Для каждого user_id возвращает последний sent_at по UserSignalDelivery (sent_via=telegram)."""
    if not user_ids:
        return {}
    async with session_maker() as session:
        q = (
            select(UserSignalDelivery.user_id, func.max(UserSignalDelivery.sent_at).label("last_at"))
            .where(
                UserSignalDelivery.user_id.in_(user_ids),
                UserSignalDelivery.sent_via == "telegram",
            )
            .group_by(UserSignalDelivery.user_id)
        )
        rows = (await session.execute(q)).all()
        return {r.user_id: r.last_at for r in rows if r.last_at is not None}


async def _mark_recommendations_sent(session_maker, rec_ids: list) -> None:
    if not rec_ids:
        return
    async with session_maker() as session:
        await session.execute(
            update(MatchRecommendation)
            .where(MatchRecommendation.id.in_(rec_ids))
            .values(signals_sent_at=datetime.now(timezone.utc))
        )
        await session.commit()


async def deliver_signals_batch_async(session_maker) -> int:
    """
    Рассылка новых рекомендаций в личку (TG/почта).

    - Загружаем все неотправленные рекомендации (signals_sent_at IS NULL), чтобы доходили все прогнозы из статистики.
    - Срочные: до начала матча < 30 мин — отправляем сразу, не дожидаясь получасового батча.
    - Остальные: не чаще раза в 30 мин одним сообщением (троттл).
    - Если у пользователя есть и срочные, и обычные — сначала отправляем срочные сразу, затем обычные (если не троттл).
    - По подписке: scope=all → все спорты; one_sport → только выбранные.
    Возвращает количество доставок (каналов).
    """
    items, rec_ids = await _load_unsent_items_and_rec_ids(session_maker, window_minutes=None)
    if not items:
        return 0

    now_utc = datetime.now(timezone.utc)
    urgent_threshold = now_utc + timedelta(minutes=URGENT_MINUTES_BEFORE_START)
    urgent_items: list[_SignalItem] = []
    normal_items: list[_SignalItem] = []
    for it in items:
        st = it.start_time.replace(tzinfo=timezone.utc) if it.start_time.tzinfo is None else it.start_time
        if st <= urgent_threshold:
            urgent_items.append(it)
        else:
            normal_items.append(it)

    sent_count = 0
    user_deliveries: list[tuple[Any, Any, str]] = []  # (user_id, rec_id, sent_via)

    user_allowances = await _get_users_with_signals_delivery(session_maker)
    user_ids = [u.id for u, _ in user_allowances]
    last_telegram_sent = await _last_telegram_dm_sent_by_user(session_maker, user_ids)
    throttle_seconds = SIGNALS_DM_THROTTLE_MINUTES * 60

    for user, allowed_sport_keys in user_allowances:
        if allowed_sport_keys is not None:
            user_urgent = [
                it for it in urgent_items
                if (it.sport_key is None or it.sport_key in allowed_sport_keys)
                and (not it.is_live or _is_set_recommendation(it.recommendation_text))
            ]
            user_normal = [
                it for it in normal_items
                if (it.sport_key is None or it.sport_key in allowed_sport_keys)
                and (not it.is_live or _is_set_recommendation(it.recommendation_text))
            ]
        else:
            user_urgent = [
                it for it in urgent_items
                if not it.is_live or _is_set_recommendation(it.recommendation_text)
            ]
            user_normal = [
                it for it in normal_items
                if not it.is_live or _is_set_recommendation(it.recommendation_text)
            ]

        # 1) Срочные: до начала матча < 30 мин — отправляем сразу (без троттла)
        if user_urgent:
            user_text_urgent = _build_signal_message_text(
                user_urgent, now_utc, use_html=True, title_line="⏰ Срочно: матч скоро начинается"
            )
            user_text_email_urgent = _build_signal_message_text(
                user_urgent, now_utc, use_html=False, title_line="Срочно: матч скоро начинается"
            )
            subject_urgent = f"Срочно: прогнозы ({len(user_urgent)}) — матч скоро"
            if user.signal_via_telegram and user.telegram_id:
                if send_telegram_message(user.telegram_id, user_text_urgent, parse_mode="HTML", disable_web_page_preview=True):
                    sent_count += 1
                    for it in user_urgent:
                        user_deliveries.append((user.id, it.rec_id, "telegram"))
            if user.signal_via_email and user.email and not (
                user.email.startswith("tg_") and "@telegram.pingwin.local" in user.email
            ):
                if send_signal_email(user.email, subject_urgent, user_text_email_urgent):
                    sent_count += 1
                    for it in user_urgent:
                        user_deliveries.append((user.id, it.rec_id, "email"))

        # 2) Обычные: в TG не чаще раза в 30 мин; в почту — без троттла
        if user_normal:
            send_normal_telegram = True
            if user.signal_via_telegram and user.telegram_id:
                last = last_telegram_sent.get(user.id)
                if last is not None:
                    if last.tzinfo is None:
                        last = last.replace(tzinfo=timezone.utc)
                    if (now_utc - last).total_seconds() < throttle_seconds:
                        logger.debug("Signals DM throttle: user %s last sent %s min ago", user.id, (now_utc - last).total_seconds() / 60)
                        send_normal_telegram = False
            if send_normal_telegram and user.signal_via_telegram and user.telegram_id:
                user_text = _build_signal_message_text(user_normal, now_utc, use_html=True)
                user_subject = f"Новые прогнозы ({len(user_normal)})"
                if send_telegram_message(user.telegram_id, user_text, parse_mode="HTML", disable_web_page_preview=True):
                    sent_count += 1
                    for it in user_normal:
                        user_deliveries.append((user.id, it.rec_id, "telegram"))
            if user.signal_via_email and user.email and not (
                user.email.startswith("tg_") and "@telegram.pingwin.local" in user.email
            ):
                user_text_email = _build_signal_message_text(user_normal, now_utc, use_html=False)
                user_subject = f"Новые прогнозы ({len(user_normal)})"
                if send_signal_email(user.email, user_subject, user_text_email):
                    sent_count += 1
                    for it in user_normal:
                        user_deliveries.append((user.id, it.rec_id, "email"))

    delivered_pairs = {(uid, rec_id) for uid, rec_id, _ in user_deliveries}
    should_send_pairs: set[tuple[Any, Any]] = set()
    for user, allowed_sport_keys in user_allowances:
        has_channel = (user.signal_via_telegram and user.telegram_id) or (
            user.signal_via_email and user.email and not (user.email.startswith("tg_") and "@telegram.pingwin.local" in user.email)
        )
        if not has_channel:
            continue
        for it in items:
            if it.is_live and not _is_set_recommendation(it.recommendation_text):
                continue
            if allowed_sport_keys is not None and it.sport_key is not None and it.sport_key not in allowed_sport_keys:
                continue
            should_send_pairs.add((user.id, it.rec_id))
    # Помечаем как отправленные только те rec, которые доставлены всем получателям
    rec_ids_to_mark = []
    for rec_id in {r for _, r, _ in user_deliveries}:
        recipients_for_rec = {(uid, rec_id) for (uid, r) in should_send_pairs if r == rec_id}
        if recipients_for_rec and all(p in delivered_pairs for p in recipients_for_rec):
            rec_ids_to_mark.append(rec_id)
    if rec_ids_to_mark:
        await _mark_recommendations_sent(session_maker, rec_ids_to_mark)
    if user_deliveries:
        async with session_maker() as session:
            for uid, rec_id, sent_via in user_deliveries:
                session.add(
                    UserSignalDelivery(
                        user_id=uid,
                        match_recommendation_id=rec_id,
                        sent_via=sent_via,
                        sent_at=now_utc,
                    )
                )
            await session.commit()

    logger.info("Signals batch sent: %d recommendations, %d deliveries", len(items), sent_count)
    if items and user_allowances and sent_count == 0:
        logger.warning(
            "Signals batch: %d items, %d eligible users, but 0 deliveries. Check: throttle (30 min), telegram_id, signal_via_telegram, TELEGRAM_BOT_TOKEN.",
            len(items),
            len(user_allowances),
        )
    return sent_count


# Redis keys для бесплатного канала (3–4 в сутки, кф ≤2, 9–21 МСК)
FREE_CHANNEL_REDIS_COUNT_PREFIX = "free_channel_sent_count:"
FREE_CHANNEL_REDIS_LAST_SENT = "free_channel_last_sent_at"


async def deliver_free_channel_async(session_maker) -> int:
    """
    Отправляет в бесплатный канал не более 3–4 прогнозов в сутки:
    кф до 2, до начала матча не менее 60 мин, уверенность близкая к 100%,
    окно 9:00–21:00 МСК, между сообщениями минимум 1 час.
    Включено только при free_channel_enabled=True.
    """
    if not getattr(settings, "free_channel_enabled", False) or not (settings.telegram_signals_chat_id or "").strip():
        return 0

    now_utc = datetime.now(timezone.utc)
    msk = ZoneInfo("Europe/Moscow")
    now_msk = now_utc.astimezone(msk)
    start_h = getattr(settings, "free_channel_window_start_hour_msk", 9)
    end_h = getattr(settings, "free_channel_window_end_hour_msk", 21)
    if not (start_h <= now_msk.hour < end_h):
        return 0

    redis_client = None
    try:
        from redis.asyncio import from_url as redis_from_url
        redis_client = redis_from_url(settings.redis_url, decode_responses=True)
    except Exception as e:
        logger.warning("Free channel: Redis unavailable: %s", e)
        return 0

    try:
        date_key = now_utc.strftime("%Y-%m-%d")
        count_key = f"{FREE_CHANNEL_REDIS_COUNT_PREFIX}{date_key}"
        count = int(await redis_client.get(count_key) or 0)
        max_per_day = getattr(settings, "free_channel_max_per_day", 4)
        if count >= max_per_day:
            return 0

        last_ts = await redis_client.get(FREE_CHANNEL_REDIS_LAST_SENT)
        if last_ts:
            try:
                last_sent = datetime.fromisoformat(last_ts)
                if last_sent.tzinfo is None:
                    last_sent = last_sent.replace(tzinfo=timezone.utc)
                interval_min = getattr(settings, "free_channel_min_interval_minutes", 60)
                if (now_utc - last_sent).total_seconds() < interval_min * 60:
                    return 0
            except (ValueError, TypeError):
                pass

        min_conf = getattr(settings, "free_channel_min_confidence_pct", 98.0)
        max_odds_val = getattr(settings, "free_channel_max_odds", 2.0)
        min_minutes = getattr(settings, "free_channel_min_minutes_before_start", 60)
        start_cutoff = now_utc + timedelta(minutes=min_minutes)

        async with session_maker() as session:
            q = (
                select(MatchRecommendation)
                .join(Match, MatchRecommendation.match_id == Match.id)
                .where(
                    MatchRecommendation.free_channel_sent_at.is_(None),
                    MatchRecommendation.confidence_pct.isnot(None),
                    MatchRecommendation.confidence_pct >= min_conf,
                    MatchRecommendation.odds_at_recommendation.isnot(None),
                    MatchRecommendation.odds_at_recommendation <= max_odds_val,
                    Match.start_time >= start_cutoff,
                    Match.status.in_(["scheduled", "pending_odds"]),
                )
                .options(
                    selectinload(MatchRecommendation.match).selectinload(Match.home_player),
                    selectinload(MatchRecommendation.match).selectinload(Match.away_player),
                    selectinload(MatchRecommendation.match).selectinload(Match.league),
                )
                .order_by(MatchRecommendation.confidence_pct.desc())
                .limit(1)
            )
            rec = (await session.execute(q)).scalar_one_or_none()
        if not rec or not rec.match or not rec.match.home_player or not rec.match.away_player:
            return 0

        match = rec.match
        item = _SignalItem(
            rec_id=rec.id,
            start_time=match.start_time,
            home_name=match.home_player.name,
            away_name=match.away_player.name,
            recommendation_text=rec.recommendation_text,
            odds_at_recommendation=float(rec.odds_at_recommendation) if rec.odds_at_recommendation is not None else None,
            match_id=match.id,
            sport_key=getattr(match, "sport_key", None),
            league_name=(match.league.name if match.league else "") or "",
        )
        text = _build_signal_message_text([item], now_utc)
        chat_id = settings.telegram_signals_chat_id.strip()
        ok, message_id = send_telegram_message_return_id(chat_id, text, parse_mode="HTML", disable_web_page_preview=True)
        if not ok:
            return 0

        async with session_maker() as session:
            await session.execute(
                update(MatchRecommendation)
                .where(MatchRecommendation.id == rec.id)
                .values(free_channel_sent_at=now_utc, free_channel_telegram_message_id=message_id)
            )
            await session.commit()

        await redis_client.incr(count_key)
        if getattr(settings, "free_channel_max_per_day", 4) > 1:
            await redis_client.expire(count_key, 86400 * 2)  # 2 дня TTL
        await redis_client.set(FREE_CHANNEL_REDIS_LAST_SENT, now_utc.isoformat(), ex=86400 * 2)
        logger.info("Free channel: sent 1 recommendation (confidence %.1f%%, odds %s)", float(rec.confidence_pct or 0), rec.odds_at_recommendation)
        return 1
    finally:
        if redis_client is not None:
            await redis_client.aclose()


# Платный канал: 1–3 раза в час, один прогноз с макс. вероятностью захода; экспресс — позже
PAID_CHANNEL_REDIS_COUNT_PREFIX = "paid_channel_sent_count:"
PAID_CHANNEL_REDIS_LAST_SENT = "paid_channel_last_sent_at"


async def deliver_paid_channel_async(session_maker) -> int:
    """
    Отправляет в платный канал 1–3 раза в час один прогноз с наибольшей вероятностью захода.
    Только матчи из линии (предстоящие): status scheduled/pending_odds, start_time > now.
    Начатые (live) и завершённые матчи не отправляем — только те, что ещё не начались.
    """
    paid_id = (settings.telegram_signals_paid_chat_id or "").strip()
    if not paid_id:
        return 0

    now_utc = datetime.now(timezone.utc)
    hour_key = now_utc.strftime("%Y-%m-%d:%H")
    count_key = f"{PAID_CHANNEL_REDIS_COUNT_PREFIX}{hour_key}"
    max_per_hour = getattr(settings, "paid_channel_max_per_hour", 3)
    min_interval_min = getattr(settings, "paid_channel_min_interval_minutes", 20)

    redis_client = None
    try:
        from redis.asyncio import from_url as redis_from_url
        redis_client = redis_from_url(settings.redis_url, decode_responses=True)
    except Exception as e:
        logger.warning("Paid channel: Redis unavailable: %s", e)
        return 0

    try:
        count = int(await redis_client.get(count_key) or 0)
        if count >= max_per_hour:
            return 0

        last_ts = await redis_client.get(PAID_CHANNEL_REDIS_LAST_SENT)
        if last_ts:
            try:
                last_sent = datetime.fromisoformat(last_ts)
                if last_sent.tzinfo is None:
                    last_sent = last_sent.replace(tzinfo=timezone.utc)
                if (now_utc - last_sent).total_seconds() < min_interval_min * 60:
                    return 0
            except (ValueError, TypeError):
                pass

        async with session_maker() as session:
            # Только линия: матчи, которые ещё не начались (scheduled/pending_odds), start_time в будущем.
            # Явно исключаем live/finished/cancelled/postponed — в VIP канал только предстоящие матчи.
            q = (
                select(MatchRecommendation)
                .join(Match, MatchRecommendation.match_id == Match.id)
                .where(
                    MatchRecommendation.paid_channel_sent_at.is_(None),
                    Match.start_time > now_utc,
                    Match.status.in_(["scheduled", "pending_odds"]),
                )
                .options(
                    selectinload(MatchRecommendation.match).selectinload(Match.home_player),
                    selectinload(MatchRecommendation.match).selectinload(Match.away_player),
                    selectinload(MatchRecommendation.match).selectinload(Match.league),
                )
                .order_by(
                    MatchRecommendation.confidence_pct.desc().nullslast(),
                    Match.start_time.asc(),
                )
                .limit(1)
            )
            rec = (await session.execute(q)).scalar_one_or_none()

        if not rec or not rec.match or not rec.match.home_player or not rec.match.away_player:
            # Логируем, почему не отправили: нет кандидатов из линии (все уже начались или все уже отправляли)
            async with session_maker() as session:
                total_unsent = await session.execute(
                    select(func.count(MatchRecommendation.id))
                    .join(Match, MatchRecommendation.match_id == Match.id)
                    .where(
                        MatchRecommendation.paid_channel_sent_at.is_(None),
                    )
                )
                total_line_future = await session.execute(
                    select(func.count(MatchRecommendation.id))
                    .join(Match, MatchRecommendation.match_id == Match.id)
                    .where(
                        MatchRecommendation.paid_channel_sent_at.is_(None),
                        Match.start_time > now_utc,
                        Match.status.in_(["scheduled", "pending_odds"]),
                    )
                )
                n_unsent = total_unsent.scalar() or 0
                n_line_future = total_line_future.scalar() or 0
            logger.info(
                "Paid channel: no candidate. Recommendations unsent total=%s, line+future (scheduled/pending_odds)=%s",
                n_unsent,
                n_line_future,
            )
            return 0

        match = rec.match
        is_live = False  # платный канал — только прематч
        item = _SignalItem(
            rec_id=rec.id,
            start_time=match.start_time,
            home_name=match.home_player.name,
            away_name=match.away_player.name,
            recommendation_text=rec.recommendation_text,
            odds_at_recommendation=float(rec.odds_at_recommendation) if rec.odds_at_recommendation is not None else None,
            match_id=match.id,
            sport_key=getattr(match, "sport_key", None),
            is_live=is_live,
            league_name=(match.league.name if match.league else "") or "",
        )
        text = _build_signal_message_text([item], now_utc)
        ok, message_id = send_telegram_message_return_id(paid_id, text, parse_mode="HTML", disable_web_page_preview=True)
        if not ok:
            return 0

        async with session_maker() as session:
            await session.execute(
                update(MatchRecommendation)
                .where(MatchRecommendation.id == rec.id)
                .values(paid_channel_sent_at=now_utc, paid_channel_telegram_message_id=message_id)
            )
            await session.commit()

        await redis_client.incr(count_key)
        await redis_client.expire(count_key, 7200)
        await redis_client.set(PAID_CHANNEL_REDIS_LAST_SENT, now_utc.isoformat(), ex=7200)
        logger.info(
            "Paid channel: sent 1 recommendation (confidence %s%%, odds %s)",
            float(rec.confidence_pct) if rec.confidence_pct is not None else "—",
            rec.odds_at_recommendation,
        )
        return 1
    finally:
        if redis_client is not None:
            await redis_client.aclose()


# --- Reply to forecast message when result is known (same logic as statistics API) ---

def _recommended_winner_side(text: str) -> str | None:
    if not text:
        return None
    t = text.lower()
    if "п1" in t and ("победа" in t or "матче" in t or "по сетам" in t or "сетам" in t):
        return "home"
    if "п2" in t and ("победа" in t or "матче" in t or "по сетам" in t or "сетам" in t):
        return "away"
    return None


def _recommended_set_winner(text: str) -> tuple[int, str] | None:
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
    if not match.result or match.result.winner_id is None or not match.scores:
        return False
    home_sets = sum(1 for s in match.scores if s.home_score > s.away_score)
    away_sets = sum(1 for s in match.scores if s.away_score > s.home_score)
    if home_sets == away_sets:
        return False
    winner_is_home = match.result.winner_id == match.home_player_id
    scores_say_home_won = home_sets > away_sets
    return winner_is_home != scores_say_home_won


def _recommendation_correct_flag(rec: MatchRecommendation, match: Match) -> bool | None:
    """True=угадали, False=не угадали, None=pending (матч не завершён или тип не оценивается)."""
    status_key = (getattr(match, "status", None) or "none").strip().lower()
    if status_key != "finished":
        return None
    set_rec = _recommended_set_winner(rec.recommendation_text)
    if set_rec is not None and match.scores:
        set_num, set_side = set_rec
        set_score = next((s for s in match.scores if s.set_number == set_num), None)
        if set_score is not None and set_score.home_score != set_score.away_score:
            set_winner_home = set_score.home_score > set_score.away_score
            if _scores_swapped_vs_result(match):
                set_winner_home = not set_winner_home
            return set_winner_home if set_side == "home" else (not set_winner_home)
        return None
    recommended = _recommended_winner_side(rec.recommendation_text)
    if recommended is None:
        return None
    if match.result and match.result.winner_id is not None:
        winner_is_home = match.result.winner_id == match.home_player_id
        if _scores_swapped_vs_result(match):
            winner_is_home = not winner_is_home
        return winner_is_home if recommended == "home" else (not winner_is_home)
    if match.scores:
        home_sets = sum(1 for s in match.scores if s.home_score > s.away_score)
        away_sets = sum(1 for s in match.scores if s.away_score > s.home_score)
        if home_sets != away_sets:
            winner_is_home = home_sets > away_sets
            return winner_is_home if recommended == "home" else (not winner_is_home)
    return None


def get_recommendation_outcome(rec: MatchRecommendation, match: Match) -> str:
    """'won' | 'lost' | 'pending' для отображения в блоке «Мои сигналы»."""
    correct = _recommendation_correct_flag(rec, match)
    if correct is True:
        return "won"
    if correct is False:
        return "lost"
    return "pending"


async def reply_forecast_results_async(session_maker) -> int:
    """
    Находит рекомендации, отправленные в каналы (free/paid) с сохранённым message_id,
    у которых матч завершён и результат известен, но ответ ещё не отправлен.
    Отправляет в Telegram ответ на то сообщение: «✅ Угадали» или «❌ Не угадали», затем помечает replied_at.
    Возвращает количество отправленных ответов.
    """
    from sqlalchemy import and_
    reply_count = 0
    to_update: list[tuple[Any, dict[str, Any]]] = []

    async with session_maker() as session:
        q = (
            select(MatchRecommendation)
            .join(Match, MatchRecommendation.match_id == Match.id)
            .where(
                or_(
                    and_(
                        MatchRecommendation.free_channel_telegram_message_id.isnot(None),
                        MatchRecommendation.free_result_replied_at.is_(None),
                    ),
                    and_(
                        MatchRecommendation.paid_channel_telegram_message_id.isnot(None),
                        MatchRecommendation.paid_result_replied_at.is_(None),
                    ),
                ),
                Match.status == "finished",
            )
            .options(
                selectinload(MatchRecommendation.match).selectinload(Match.result).selectinload(MatchResult.winner),
                selectinload(MatchRecommendation.match).selectinload(Match.scores),
            )
        )
        recs = (await session.execute(q)).scalars().unique().all()

    now_utc = datetime.now(timezone.utc)
    free_chat = (settings.telegram_signals_chat_id or "").strip()
    paid_chat = (settings.telegram_signals_paid_chat_id or "").strip()

    for rec in recs:
        match = rec.match
        correct = _recommendation_correct_flag(rec, match)
        if correct is None:
            continue
        text = "✅ Угадали" if correct else "❌ Не угадали"
        updates: dict[str, Any] = {}

        if rec.free_channel_telegram_message_id is not None and rec.free_result_replied_at is None and free_chat:
            if send_telegram_reply(free_chat, rec.free_channel_telegram_message_id, text, parse_mode=None):
                updates["free_result_replied_at"] = now_utc
                reply_count += 1

        if rec.paid_channel_telegram_message_id is not None and rec.paid_result_replied_at is None and paid_chat:
            if send_telegram_reply(paid_chat, rec.paid_channel_telegram_message_id, text, parse_mode=None):
                updates["paid_result_replied_at"] = now_utc
                reply_count += 1

        if updates:
            to_update.append((rec.id, updates))

    if to_update:
        async with session_maker() as session:
            for rec_id, updates in to_update:
                await session.execute(update(MatchRecommendation).where(MatchRecommendation.id == rec_id).values(**updates))
            await session.commit()

    if reply_count:
        logger.info("Reply forecast results: sent %d reply(ies)", reply_count)
    return reply_count


async def send_dm_batch_results_async(session_maker) -> int:
    """
    Для батчей личных сообщений в Telegram (несколько матчей в одном сообщении):
    когда по всем матчам батча известны исходы — отправляет пользователю одно сообщение
    «По итогам прогнозов» с результатом по каждому матчу (✅ Угадали / ❌ Не угадали).
    Возвращает количество отправленных сообщений.
    """
    now_utc = datetime.now(timezone.utc)
    sent_count = 0

    async with session_maker() as session:
        # Батчи: user_id + sent_at, только telegram, результат ещё не отправляли, в батче минимум 2 матча
        batch_q = (
            select(UserSignalDelivery.user_id, UserSignalDelivery.sent_at)
            .where(
                UserSignalDelivery.sent_via == "telegram",
                UserSignalDelivery.telegram_result_sent_at.is_(None),
            )
            .group_by(UserSignalDelivery.user_id, UserSignalDelivery.sent_at)
            .having(func.count(UserSignalDelivery.id) >= 2)
        )
        batches = (await session.execute(batch_q)).all()

    for (user_id, sent_at) in batches:
        async with session_maker() as session:
            deliveries_q = (
                select(UserSignalDelivery)
                .where(
                    UserSignalDelivery.user_id == user_id,
                    UserSignalDelivery.sent_at == sent_at,
                    UserSignalDelivery.sent_via == "telegram",
                    UserSignalDelivery.telegram_result_sent_at.is_(None),
                )
            )
            deliveries = (await session.execute(deliveries_q)).scalars().all()
        if not deliveries:
            continue
        rec_ids = [d.match_recommendation_id for d in deliveries]
        delivery_ids = [d.id for d in deliveries]

        async with session_maker() as session:
            recs_q = (
                select(MatchRecommendation)
                .where(MatchRecommendation.id.in_(rec_ids))
                .options(
                    selectinload(MatchRecommendation.match).selectinload(Match.result),
                    selectinload(MatchRecommendation.match).selectinload(Match.scores),
                    selectinload(MatchRecommendation.match).selectinload(Match.home_player),
                    selectinload(MatchRecommendation.match).selectinload(Match.away_player),
                )
            )
            recs = list((await session.execute(recs_q)).scalars().unique().all())
        # Порядок как в батче
        recs_sorted = sorted(recs, key=lambda r: rec_ids.index(r.id))

        skip_batch = False
        for rec in recs_sorted:
            match = rec.match
            if not match or (getattr(match, "status", None) or "").strip().lower() != "finished":
                skip_batch = True
                break
            correct = _recommendation_correct_flag(rec, match)
            if correct is None:
                skip_batch = True
                break
        if skip_batch:
            continue

        lines = ["<b>По итогам прогнозов</b>", ""]
        for rec in recs_sorted:
            match = rec.match
            home_name = (match.home_player.name if match and match.home_player else "?") or "?"
            away_name = (match.away_player.name if match and match.away_player else "?") or "?"
            correct = _recommendation_correct_flag(rec, match)
            outcome = "✅ Угадали" if correct else "❌ Не угадали"
            lines.append(f"{_html_escape(home_name)} — {_html_escape(away_name)}: {outcome}")
        text = "\n".join(lines)

        async with session_maker() as session:
            user = await session.get(User, user_id)
        if not user or not user.telegram_id or getattr(user, "is_blocked", False):
            continue
        if send_telegram_message(user.telegram_id, text, parse_mode="HTML", disable_web_page_preview=True):
            async with session_maker() as session:
                await session.execute(
                    update(UserSignalDelivery)
                    .where(UserSignalDelivery.id.in_(delivery_ids))
                    .values(telegram_result_sent_at=now_utc)
                )
                await session.commit()
            sent_count += 1
            logger.info("DM batch results sent to user %s (%d matches)", user_id, len(recs_sorted))

    if sent_count:
        logger.info("send_dm_batch_results: sent %d batch result message(s)", sent_count)
    return sent_count


async def send_dm_single_results_async(session_maker) -> int:
    """
    Для одиночных личных сообщений в Telegram (один матч в сообщении):
    когда матч завершён и исход известен — отправляет пользователю сообщение
    «По итогам прогноза» с результатом (✅ Угадали / ❌ Не угадали).
    Возвращает количество отправленных сообщений.
    """
    now_utc = datetime.now(timezone.utc)
    sent_count = 0

    async with session_maker() as session:
        # Одиночные доставки: telegram, результат ещё не отправляли, группа (user_id, sent_at) имеет ровно 1 доставку
        subq = (
            select(UserSignalDelivery.user_id, UserSignalDelivery.sent_at)
            .where(
                UserSignalDelivery.sent_via == "telegram",
                UserSignalDelivery.telegram_result_sent_at.is_(None),
            )
            .group_by(UserSignalDelivery.user_id, UserSignalDelivery.sent_at)
            .having(func.count(UserSignalDelivery.id) == 1)
        )
        singles = (await session.execute(subq)).all()

    for (user_id, sent_at) in singles:
        async with session_maker() as session:
            d_q = (
                select(UserSignalDelivery)
                .where(
                    UserSignalDelivery.user_id == user_id,
                    UserSignalDelivery.sent_at == sent_at,
                    UserSignalDelivery.sent_via == "telegram",
                    UserSignalDelivery.telegram_result_sent_at.is_(None),
                )
            )
            deliveries = (await session.execute(d_q)).scalars().all()
        if not deliveries:
            continue
        d = deliveries[0]
        rec_id = d.match_recommendation_id
        async with session_maker() as session:
            recs_q = (
                select(MatchRecommendation)
                .where(MatchRecommendation.id == rec_id)
                .options(
                    selectinload(MatchRecommendation.match).selectinload(Match.result),
                    selectinload(MatchRecommendation.match).selectinload(Match.scores),
                    selectinload(MatchRecommendation.match).selectinload(Match.home_player),
                    selectinload(MatchRecommendation.match).selectinload(Match.away_player),
                )
            )
            rec = (await session.execute(recs_q)).scalar_one_or_none()
        if not rec or not rec.match:
            continue
        match = rec.match
        if (getattr(match, "status", None) or "").strip().lower() != "finished":
            continue
        correct = _recommendation_correct_flag(rec, match)
        if correct is None:
            continue
        home_name = (match.home_player.name if match.home_player else "?") or "?"
        away_name = (match.away_player.name if match.away_player else "?") or "?"
        outcome = "✅ Угадали" if correct else "❌ Не угадали"
        text = f"<b>По итогам прогноза</b>\n\n{_html_escape(home_name)} — {_html_escape(away_name)}: {outcome}"

        async with session_maker() as session:
            user = await session.get(User, user_id)
        if not user or not user.telegram_id or getattr(user, "is_blocked", False):
            continue
        if send_telegram_message(user.telegram_id, text, parse_mode="HTML", disable_web_page_preview=True):
            async with session_maker() as session:
                await session.execute(
                    update(UserSignalDelivery)
                    .where(UserSignalDelivery.id == d.id)
                    .values(telegram_result_sent_at=now_utc)
                )
                await session.commit()
            sent_count += 1
            logger.info("DM single result sent to user %s", user_id)

    if sent_count:
        logger.info("send_dm_single_results: sent %d single result message(s)", sent_count)
    return sent_count


# --- Daily stats: free 21:00, paid 23:59 Moscow ---

def _day_bounds_msk(day_date: date, msk: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day_date, datetime.min.time(), tzinfo=msk)
    end = datetime.combine(day_date, datetime.max.time().replace(microsecond=0), tzinfo=msk)
    return start, end


async def get_channel_daily_stats(
    session_maker,
    channel: str,
    day_date: date,
) -> dict[str, int]:
    """
    channel: "free" | "paid"
    day_date: date in Moscow (or any date; we filter by sent_at in that day MSK).
    Returns: total, won, lost, pending, missed (cancelled/no_data).
    """
    msk = ZoneInfo("Europe/Moscow")
    start_msk, end_msk = _day_bounds_msk(day_date, msk)
    start_utc = start_msk.astimezone(timezone.utc)
    end_utc = end_msk.astimezone(timezone.utc)

    if channel == "free":
        sent_at_col = MatchRecommendation.free_channel_sent_at
    else:
        sent_at_col = MatchRecommendation.paid_channel_sent_at

    async with session_maker() as session:
        q = (
            select(MatchRecommendation)
            .join(Match, MatchRecommendation.match_id == Match.id)
            .where(
                sent_at_col.isnot(None),
                sent_at_col >= start_utc,
                sent_at_col <= end_utc,
            )
            .options(
                selectinload(MatchRecommendation.match).selectinload(Match.result),
                selectinload(MatchRecommendation.match).selectinload(Match.scores),
            )
        )
        recs = (await session.execute(q)).scalars().all()

    total = len(recs)
    won = lost = pending = missed = 0
    for rec in recs:
        match = rec.match
        status_key = (getattr(match, "status", None) or "none").strip().lower()
        if status_key == "cancelled" or status_key == "postponed":
            missed += 1
            continue
        if status_key != "finished":
            pending += 1
            continue
        if not match.result and not (match.scores and any(s.home_score != s.away_score for s in match.scores)):
            missed += 1
            continue
        correct = _recommendation_correct_flag(rec, match)
        if correct is True:
            won += 1
        elif correct is False:
            lost += 1
        else:
            pending += 1

    return {"total": total, "won": won, "lost": lost, "pending": pending, "missed": missed}


async def get_paid_channel_stats_since(session_maker, since_utc: datetime) -> dict[str, int]:
    """
    Агрегированная статистика VIP-канала: все отправленные в платный канал с since_utc.
    total, won, lost, pending, missed, bank_profit_rub, avg_odds.
    Банк считается при условной ставке CHANNEL_BET_STAKE_RUB на каждый прогноз.
    """
    sent_at_col = MatchRecommendation.paid_channel_sent_at
    async with session_maker() as session:
        q = (
            select(MatchRecommendation)
            .join(Match, MatchRecommendation.match_id == Match.id)
            .where(
                sent_at_col.isnot(None),
                sent_at_col >= since_utc,
            )
            .options(
                selectinload(MatchRecommendation.match).selectinload(Match.result),
                selectinload(MatchRecommendation.match).selectinload(Match.scores),
            )
        )
        recs = (await session.execute(q)).scalars().all()

    total = len(recs)
    won = lost = pending = missed = 0
    bank_profit = 0.0
    odds_sum = 0.0
    odds_count = 0
    for rec in recs:
        match = rec.match
        status_key = (getattr(match, "status", None) or "none").strip().lower()

        odds = float(rec.odds_at_recommendation) if rec.odds_at_recommendation is not None else None
        if odds is not None:
            odds_sum += odds
            odds_count += 1

        if status_key == "cancelled" or status_key == "postponed":
            missed += 1
            continue
        if status_key != "finished":
            pending += 1
            continue
        if not match.result and not (match.scores and any(s.home_score != s.away_score for s in match.scores)):
            missed += 1
            continue
        correct = _recommendation_correct_flag(rec, match)
        if correct is True:
            won += 1
            if odds is not None:
                bank_profit += CHANNEL_BET_STAKE_RUB * (odds - 1)
        elif correct is False:
            lost += 1
            bank_profit -= CHANNEL_BET_STAKE_RUB
        else:
            pending += 1
    avg_odds = (odds_sum / odds_count) if odds_count else None
    return {
        "total": total,
        "won": won,
        "lost": lost,
        "pending": pending,
        "missed": missed,
        "bank_profit_rub": round(bank_profit, 0),
        "avg_odds": round(avg_odds, 2) if avg_odds is not None else None,
    }


async def get_free_channel_stats_since(session_maker, since_utc: datetime) -> dict[str, int]:
    """
    Агрегированная статистика бесплатного канала: все отправленные в free-канал с since_utc.
    total, won, lost, pending, missed, bank_profit_rub, avg_odds.
    Банк считается при условной ставке CHANNEL_BET_STAKE_RUB на каждый прогноз.
    """
    sent_at_col = MatchRecommendation.free_channel_sent_at
    async with session_maker() as session:
        q = (
            select(MatchRecommendation)
            .join(Match, MatchRecommendation.match_id == Match.id)
            .where(
                sent_at_col.isnot(None),
                sent_at_col >= since_utc,
            )
            .options(
                selectinload(MatchRecommendation.match).selectinload(Match.result),
                selectinload(MatchRecommendation.match).selectinload(Match.scores),
            )
        )
        recs = (await session.execute(q)).scalars().all()

    total = len(recs)
    won = lost = pending = missed = 0
    bank_profit = 0.0
    odds_sum = 0.0
    odds_count = 0
    for rec in recs:
        match = rec.match
        status_key = (getattr(match, "status", None) or "none").strip().lower()

        odds = float(rec.odds_at_recommendation) if rec.odds_at_recommendation is not None else None
        if odds is not None:
            odds_sum += odds
            odds_count += 1

        if status_key == "cancelled" or status_key == "postponed":
            missed += 1
            continue
        if status_key != "finished":
            pending += 1
            continue
        if not match.result and not (match.scores and any(s.home_score != s.away_score for s in match.scores)):
            missed += 1
            continue
        correct = _recommendation_correct_flag(rec, match)
        if correct is True:
            won += 1
            if odds is not None:
                bank_profit += CHANNEL_BET_STAKE_RUB * (odds - 1)
        elif correct is False:
            lost += 1
            bank_profit -= CHANNEL_BET_STAKE_RUB
        else:
            pending += 1
    avg_odds = (odds_sum / odds_count) if odds_count else None
    return {
        "total": total,
        "won": won,
        "lost": lost,
        "pending": pending,
        "missed": missed,
        "bank_profit_rub": round(bank_profit, 0),
        "avg_odds": round(avg_odds, 2) if avg_odds is not None else None,
    }


async def send_free_channel_daily_stats_async(session_maker) -> bool:
    """Отправляет в бесплатный канал сводку за день (21:00 МСК). Вызывать по расписанию в 21:00 МСК."""
    chat_id = (settings.telegram_signals_chat_id or "").strip()
    if not chat_id:
        return False
    msk = ZoneInfo("Europe/Moscow")
    today = datetime.now(msk).date()
    stats = await get_channel_daily_stats(session_maker, "free", today)
    lines = [
        "📊 Статистика за день (бесплатный канал)",
        "",
        f"Всего прогнозов в чат: {stats['total']}",
        f"✅ Угадали: {stats['won']}",
        f"❌ Не угадали: {stats['lost']}",
        f"⏳ Ещё в игре: {stats['pending']}",
        f"⊘ Пропущено (отмена/перенос): {stats['missed']}",
    ]
    text = "\n".join(lines)
    ok = send_telegram_message(chat_id, text, parse_mode=None)
    if ok:
        logger.info("Free channel daily stats sent: %s", stats)
    return ok


async def send_paid_channel_daily_stats_async(session_maker) -> bool:
    """Отправляет в VIP-чат сводку за день (23:59 МСК). Вызывать по расписанию в 23:59 МСК."""
    paid_id = (settings.telegram_signals_paid_chat_id or "").strip()
    if not paid_id:
        return False
    msk = ZoneInfo("Europe/Moscow")
    today = datetime.now(msk).date()
    stats = await get_channel_daily_stats(session_maker, "paid", today)
    lines = [
        "📊 Итоги за сутки (VIP)",
        "",
        f"Всего прогнозов: {stats['total']}",
        f"✅ Угадали: {stats['won']}",
        f"❌ Не угадали: {stats['lost']}",
        f"⏳ В игре: {stats['pending']}",
        f"⊘ Пропущено: {stats['missed']}",
    ]
    text = "\n".join(lines)
    ok = send_telegram_message(paid_id, text, parse_mode=None)
    if ok:
        logger.info("Paid channel daily stats sent: %s", stats)
    return ok
