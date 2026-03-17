"""Dispatch forecasts to FREE, VIP and no-ML Telegram channels."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from html import escape
import json
import logging
import random

import httpx
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import async_session_maker
from app.models.app_setting import AppSetting
from app.models.table_tennis_forecast_v2 import TableTennisForecastV2
from app.models.table_tennis_line_event import LINE_EVENT_STATUS_SCHEDULED, TableTennisLineEvent
from app.models.telegram_channel_marker import TelegramChannelMarker
from app.models.telegram_channel_notification import TelegramChannelNotification

logger = logging.getLogger(__name__)
CHANNEL_DISPATCHER_ADVISORY_LOCK_KEY = 910002

CHANNEL_FREE = "free"
CHANNEL_VIP = "vip"
CHANNEL_NO_ML = "no_ml_channel"
DISPATCH_CFG_KEY = "telegram_dispatch_config"

DEFAULT_DISPATCH_CFG: dict = {
    "free": {
        "enabled": True,
        "slots": [],
        "min_lead_minutes": 60,
        "daily_summary_hour_utc": None,
    },
    "vip": {
        "enabled": True,
        "slots": [],
        "min_lead_minutes": 60,
        "daily_summary_hour_utc": None,
    },
    "no_ml_channel": {
        "enabled": True,
        # Потоковая отправка всех no_ml прогнозов с группировкой.
        "stream_enabled": False,
        "stream_interval_minutes": 30,
        "stream_source": "no_ml",
        "stream_group_limit": 20,
        "stream_fetch_limit": 500,
        "min_lead_minutes": 60,
        "daily_summary_hour_utc": None,
    },
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _msk_now(now_utc: datetime | None = None) -> datetime:
    base = now_utc or _utc_now()
    return base.astimezone(timezone(timedelta(hours=3)))


def _event_link(event_id: str) -> str:
    return f"https://pingwin.pro/dashboard/table-tennis/matches/{event_id}"


def _clean_forecast_text(text: str | None) -> str:
    if not text:
        return "Недостаточно данных для расчёта"
    import re

    return re.sub(r"\s*\(\d+(?:[.,]\d+)?%\)", "", text).replace("%", "").strip()


def _countdown(starts_at: datetime, now: datetime) -> str:
    seconds = int((starts_at - now).total_seconds())
    if seconds <= 0:
        return "матч уже начался"
    minutes = seconds // 60
    if minutes < 60:
        return f"через {minutes} мин"
    return f"через {minutes // 60} ч {minutes % 60} мин"


def _chat_id(channel: str) -> int | None:
    if channel == CHANNEL_FREE:
        raw = settings.telegram_signals_free_chat_id
    elif channel == CHANNEL_VIP:
        raw = settings.telegram_signals_vip_chat_id
    elif channel == CHANNEL_NO_ML:
        raw = settings.telegram_signals_no_ml_chat_id
    else:
        raw = ""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _cancelled_grace_elapsed(event: TableTennisLineEvent | None, now: datetime) -> bool:
    if event is None or event.starts_at is None:
        return True
    return now >= (event.starts_at + timedelta(hours=2))


def _slot_passed(now_msk: datetime, slot: str) -> bool:
    try:
        hh, mm = slot.split(":")
        h, m = int(hh), int(mm)
    except Exception:
        return False
    return (now_msk.hour > h) or (now_msk.hour == h and now_msk.minute >= m)


def _slot_time(slot_item: dict) -> str:
    return str(slot_item.get("time_msk") or "").strip()


def _slot_source(slot_item: dict) -> str:
    src = str(slot_item.get("source") or "paid").strip().lower()
    if src in {"paid", "no_ml", "nn"}:
        return src
    return "paid"


def _is_late_appeared(
    event: TableTennisLineEvent,
    forecast: TableTennisForecastV2,
    *,
    min_lead_minutes: int,
    now: datetime,
) -> bool:
    """Forecast appeared too close to match start (< min_lead)."""
    if event.starts_at is None or forecast.created_at is None:
        return False
    if event.starts_at <= now:
        return False
    threshold = event.starts_at - timedelta(minutes=max(0, min_lead_minutes))
    return forecast.created_at >= threshold


async def _pick_candidates(
    session: AsyncSession,
    target_channel: str,
    source: str,
    min_lead_minutes: int,
    limit: int,
) -> list[tuple[TableTennisLineEvent, TableTennisForecastV2]]:
    if source == "paid":
        return await _get_candidates(
            session=session,
            channel=target_channel,
            min_lead_minutes=min_lead_minutes,
            limit=limit,
        )
    if source == "nn":
        return await _get_nn_candidates_for_channel(
            session=session,
            channel=target_channel,
            min_lead_minutes=min_lead_minutes,
            limit=limit,
        )
    return await _get_no_ml_candidates_for_channel(
        session=session,
        channel=target_channel,
        min_lead_minutes=min_lead_minutes,
        limit=limit,
    )


async def _pick_late_appeared_candidates(
    session: AsyncSession,
    target_channel: str,
    source: str,
    min_lead_minutes: int,
    limit: int,
) -> list[tuple[TableTennisLineEvent, TableTennisForecastV2]]:
    now = _utc_now()
    max_starts = now + timedelta(minutes=max(0, min_lead_minutes))
    src_channel = "paid" if source == "paid" else ("nn" if source == "nn" else "no_ml")
    rows = (
        await session.execute(
            select(TableTennisLineEvent, TableTennisForecastV2)
            .join(
                TableTennisForecastV2,
                and_(
                    TableTennisForecastV2.event_id == TableTennisLineEvent.id,
                    TableTennisForecastV2.channel == src_channel,
                    TableTennisForecastV2.status == "pending",
                ),
            )
            .where(
                TableTennisLineEvent.status == LINE_EVENT_STATUS_SCHEDULED,
                TableTennisLineEvent.starts_at > now,
                TableTennisLineEvent.starts_at <= max_starts,
            )
            .order_by(TableTennisLineEvent.starts_at.asc(), TableTennisForecastV2.created_at.desc())
            .limit(limit)
        )
    ).all()
    if not rows:
        return []

    uniq: list[tuple[TableTennisLineEvent, TableTennisForecastV2]] = []
    seen: set[str] = set()
    for e, f in rows:
        eid = str(e.id)
        if eid in seen:
            continue
        seen.add(eid)
        if _is_late_appeared(e, f, min_lead_minutes=min_lead_minutes, now=now):
            uniq.append((e, f))
    if not uniq:
        return []

    already = {
        str(x[0])
        for x in (
            await session.execute(
                select(TelegramChannelNotification.event_id).where(
                    TelegramChannelNotification.channel == target_channel,
                    TelegramChannelNotification.event_id.in_([str(e.id) for e, _ in uniq]),
                )
            )
        ).all()
    }
    return [(e, f) for e, f in uniq if str(e.id) not in already]


async def _load_dispatch_cfg(session: AsyncSession) -> dict:
    row = (
        await session.execute(select(AppSetting).where(AppSetting.key == DISPATCH_CFG_KEY))
    ).scalars().one_or_none()
    if not row or not (getattr(row, "value", None) or "").strip():
        logger.warning(
            "Telegram dispatch: конфиг из админки не найден в БД (app_setting.%s) — используются дефолты (пустые слоты). Сохраните расписание в админке.",
            DISPATCH_CFG_KEY,
        )
        return DEFAULT_DISPATCH_CFG
    try:
        parsed = json.loads(row.value)
        if not isinstance(parsed, dict):
            logger.warning("Telegram dispatch: значение в БД не объект JSON — используются дефолты")
            return DEFAULT_DISPATCH_CFG
        cfg = json.loads(json.dumps(DEFAULT_DISPATCH_CFG))
        for key in ("free", "vip", "no_ml_channel"):
            if isinstance(parsed.get(key), dict):
                cfg[key].update(parsed[key])
        # Backward compatibility for old format.
        free = cfg.get("free", {})
        if isinstance(free, dict) and not isinstance(free.get("slots"), list):
            slots = []
            for t in list(free.get("slots_msk", []) or []):
                slots.append({"time_msk": str(t), "source": "paid", "count": int(free.get("ml_per_slot", 1) or 1)})
            if slots:
                free["slots"] = slots
        vip = cfg.get("vip", {})
        if isinstance(vip, dict) and not isinstance(vip.get("slots"), list):
            slots = []
            for t in list(vip.get("slots_msk", []) or []):
                slots.append({"time_msk": str(t), "source": "paid", "count": int(vip.get("per_slot", 1) or 1)})
            if slots:
                vip["slots"] = slots
        no_ml = cfg.get("no_ml_channel", {})
        if isinstance(no_ml, dict):
            if "stream_interval_minutes" not in no_ml and "interval_minutes" in no_ml:
                no_ml["stream_interval_minutes"] = no_ml.get("interval_minutes")
            if "stream_group_limit" not in no_ml and "group_limit" in no_ml:
                no_ml["stream_group_limit"] = no_ml.get("group_limit")
        n_free = len(free.get("slots") or []) if isinstance(free, dict) else 0
        n_vip = len(vip.get("slots") or []) if isinstance(vip, dict) else 0
        logger.debug(
            "Telegram dispatch: загружен конфиг из БД: free.slots=%s vip.slots=%s",
            n_free,
            n_vip,
        )
        return cfg
    except Exception as e:
        logger.warning(
            "Telegram dispatch: ошибка разбора конфига из БД (%s) — используются дефолты. Проверьте JSON в админке.",
            e,
            exc_info=True,
        )
        return DEFAULT_DISPATCH_CFG


async def _send_telegram(chat_id: int, text: str, reply_to_message_id: int | None = None, *, channel: str) -> int | None:
    # Каналы отправляются только своими ботами (без fallback на основной user-бот).
    if channel == CHANNEL_FREE:
        token = (settings.telegram_signals_free_bot_token or "").strip()
    elif channel == CHANNEL_VIP:
        token = (settings.telegram_signals_vip_bot_token or "").strip()
    elif channel == CHANNEL_NO_ML:
        token = (settings.telegram_signals_no_ml_bot_token or "").strip()
    else:
        token = ""
    if not token:
        logger.warning("Telegram канал %s: не задан bot token, сообщение не отправлено", channel)
        return None
    payload: dict[str, object] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload)
    if r.status_code != 200:
        logger.warning(
            "Telegram канал %s: отправка не удалась HTTP %s — %s",
            channel, r.status_code, r.text[:300],
        )
        return None
    data = r.json()
    if not data.get("ok"):
        logger.warning("Telegram канал %s: ответ not ok — %s", channel, data)
        return None
    return int((data.get("result") or {}).get("message_id") or 0) or None


def _build_event_text(event: TableTennisLineEvent, fc: TableTennisForecastV2, now: datetime) -> str:
    starts = event.starts_at.astimezone(timezone.utc) if event.starts_at else now
    odds_text = f"\nКф: {float(fc.odds_used):.2f}" if fc.odds_used is not None else ""
    return (
        f"🏆 {escape(event.league_name or '—')}\n"
        f"{starts.strftime('%d.%m.%Y %H:%M UTC')}\n"
        f"⏱ {_countdown(starts, now)}\n"
        f"{escape(event.home_name or '—')} — {escape(event.away_name or '—')}"
        f"{odds_text}\n"
        f"Наш прогноз: {escape(_clean_forecast_text(fc.forecast_text))}\n"
        f"Аналитика матча: <a href=\"{escape(_event_link(str(event.id)))}\">открыть</a>"
    )


async def _ensure_channel_forecast(session: AsyncSession, src: TableTennisForecastV2, channel: str) -> TableTennisForecastV2:
    existing = (
        await session.execute(
            select(TableTennisForecastV2).where(
                and_(
                    TableTennisForecastV2.event_id == src.event_id,
                    TableTennisForecastV2.channel == channel,
                    TableTennisForecastV2.market == src.market,
                )
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    row = TableTennisForecastV2(
        event_id=src.event_id,
        model_run_id=src.model_run_id,
        channel=channel,
        market=src.market,
        pick_side=src.pick_side,
        forecast_text=src.forecast_text,
        probability_pct=src.probability_pct,
        confidence_score=src.confidence_score,
        edge_pct=src.edge_pct,
        odds_used=src.odds_used,
        status=src.status,
        final_status=src.final_status,
        final_sets_score=src.final_sets_score,
        explanation_summary=src.explanation_summary,
        created_at=_utc_now(),
        resolved_at=src.resolved_at,
    )
    session.add(row)
    await session.flush()
    return row


async def _get_candidates(
    session: AsyncSession,
    channel: str,
    min_lead_minutes: int,
    limit: int,
) -> list[tuple[TableTennisLineEvent, TableTennisForecastV2]]:
    return await _get_source_candidates_for_channel(
        session=session,
        channel=channel,
        source_channel="paid",
        min_lead_minutes=min_lead_minutes,
        limit=limit,
    )


async def _get_source_candidates_for_channel(
    session: AsyncSession,
    channel: str,
    source_channel: str,
    min_lead_minutes: int,
    limit: int,
) -> list[tuple[TableTennisLineEvent, TableTennisForecastV2]]:
    now = _utc_now()
    min_starts = now + timedelta(minutes=max(0, min_lead_minutes))
    rows = (
        await session.execute(
            select(TableTennisLineEvent, TableTennisForecastV2)
            .join(
                TableTennisForecastV2,
                and_(
                    TableTennisForecastV2.event_id == TableTennisLineEvent.id,
                    TableTennisForecastV2.channel == source_channel,
                    TableTennisForecastV2.status == "pending",
                ),
            )
            .where(
                TableTennisLineEvent.status == LINE_EVENT_STATUS_SCHEDULED,
                TableTennisLineEvent.starts_at > min_starts,
            )
            .order_by(TableTennisLineEvent.starts_at.asc(), TableTennisForecastV2.created_at.desc())
            .limit(limit)
        )
    ).all()
    if not rows:
        return []

    # uniq by event (latest forecast first due to order)
    uniq: list[tuple[TableTennisLineEvent, TableTennisForecastV2]] = []
    seen: set[str] = set()
    for e, f in rows:
        eid = str(e.id)
        if eid in seen:
            continue
        seen.add(eid)
        uniq.append((e, f))

    already = {
        str(x[0])
        for x in (
            await session.execute(
                select(TelegramChannelNotification.event_id).where(
                    TelegramChannelNotification.channel == channel,
                    TelegramChannelNotification.event_id.in_([str(e.id) for e, _ in uniq]),
                )
            )
        ).all()
    }
    return [(e, f) for e, f in uniq if str(e.id) not in already]


async def _send_events_to_channel(
    session: AsyncSession,
    channel: str,
    events: list[tuple[TableTennisLineEvent, TableTennisForecastV2]],
) -> int:
    if not events:
        return 0
    chat_id = _chat_id(channel)
    if chat_id is None:
        logger.debug("Telegram канал %s: chat_id не задан, отправка пропущена (%s событий)", channel, len(events))
        return 0
    now = _utc_now()
    text = "\n\n".join(_build_event_text(e, f, now) for e, f in events) + "\n\n🐧 <a href=\"https://pingwin.pro\">pingwin.pro</a> — аналитический сервис"
    msg_id = await _send_telegram(chat_id, text, channel=channel)
    if msg_id is None:
        return 0
    rows_to_insert = []
    for e, src_fc in events:
        forecast_id = src_fc.id
        try:
            channel_fc = await _ensure_channel_forecast(session, src_fc, channel=channel)
            forecast_id = channel_fc.id
        except Exception:  # noqa: BLE001
            logger.warning("Channel dispatcher: failed to ensure channel forecast", exc_info=True)
        rows_to_insert.append(
            {
                "channel": channel,
                "event_id": str(e.id),
                "forecast_v2_id": forecast_id,
                "telegram_message_id": msg_id,
            }
        )
    if rows_to_insert:
        stmt = pg_insert(TelegramChannelNotification).values(rows_to_insert)
        stmt = stmt.on_conflict_do_nothing(
            constraint="uq_telegram_channel_notifications_channel_event"
        )
        result = await session.execute(stmt)
        inserted = int(result.rowcount or 0)
        return inserted
    return 0


async def _get_no_ml_candidates_for_channel(
    session: AsyncSession,
    channel: str,
    min_lead_minutes: int,
    limit: int,
) -> list[tuple[TableTennisLineEvent, TableTennisForecastV2]]:
    """Кандидаты из no_ml канала для отправки в указанный Telegram-канал."""
    return await _get_source_candidates_for_channel(
        session=session,
        channel=channel,
        source_channel="no_ml",
        min_lead_minutes=min_lead_minutes,
        limit=limit,
    )


async def _get_nn_candidates_for_channel(
    session: AsyncSession,
    channel: str,
    min_lead_minutes: int,
    limit: int,
) -> list[tuple[TableTennisLineEvent, TableTennisForecastV2]]:
    """Кандидаты из nn канала для отправки в указанный Telegram-канал."""
    return await _get_source_candidates_for_channel(
        session=session,
        channel=channel,
        source_channel="nn",
        min_lead_minutes=min_lead_minutes,
        limit=limit,
    )


async def _ensure_marker(
    session: AsyncSession,
    marker_key: str,
    channel: str,
    marker_type: str,
    telegram_message_id: int | None = None,
) -> bool:
    existing = (
        await session.execute(select(TelegramChannelMarker).where(TelegramChannelMarker.marker_key == marker_key))
    ).scalar_one_or_none()
    if existing:
        return False
    session.add(
        TelegramChannelMarker(
            marker_key=marker_key,
            channel=channel,
            marker_type=marker_type,
            telegram_message_id=telegram_message_id,
        )
    )
    return True


async def _marker_exists(session: AsyncSession, marker_key: str) -> bool:
    existing = (
        await session.execute(select(TelegramChannelMarker.id).where(TelegramChannelMarker.marker_key == marker_key))
    ).scalar_one_or_none()
    return existing is not None


async def _send_daily_summary(session: AsyncSession, channel: str, hour_utc: int) -> bool:
    now = _utc_now()
    if now.hour < hour_utc:
        return False
    marker_key = f"{channel}_summary_{now.strftime('%Y%m%d')}"
    if not await _ensure_marker(session, marker_key, channel, "summary"):
        return False
    chat_id = _chat_id(channel)
    if chat_id is None:
        return False
    day_from = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    week_from = day_from - timedelta(days=6)

    day_rows = (
        await session.execute(
            select(TelegramChannelNotification, TableTennisForecastV2)
            .join(TableTennisForecastV2, TableTennisForecastV2.id == TelegramChannelNotification.forecast_v2_id, isouter=True)
            .where(
                TelegramChannelNotification.channel == channel,
                TelegramChannelNotification.sent_at >= day_from,
            )
        )
    ).all()
    week_rows = (
        await session.execute(
            select(TelegramChannelNotification, TableTennisForecastV2)
            .join(TableTennisForecastV2, TableTennisForecastV2.id == TelegramChannelNotification.forecast_v2_id, isouter=True)
            .where(
                TelegramChannelNotification.channel == channel,
                TelegramChannelNotification.sent_at >= week_from,
            )
        )
    ).all()

    def _c(rows: list[tuple[TelegramChannelNotification, TableTennisForecastV2 | None]]) -> tuple[int, int, int]:
        total = len(rows)
        hit = sum(1 for _n, f in rows if f and f.status == "hit")
        miss = sum(1 for _n, f in rows if f and f.status == "miss")
        return total, hit, miss

    d_total, d_hit, d_miss = _c(day_rows)
    w_total, w_hit, w_miss = _c(week_rows)
    text = (
        f"📊 Статистика канала за день\n"
        f"Сегодня: дано {d_total}, угадано {d_hit}, не угадано {d_miss}\n"
        f"За неделю: дано {w_total}, угадано {w_hit}, не угадано {w_miss}\n\n"
        f"🐧 <a href=\"https://pingwin.pro\">pingwin.pro</a>"
    )
    msg_id = await _send_telegram(chat_id, text, channel=channel)
    if msg_id:
        # marker already inserted, only enrich
        m = (
            await session.execute(select(TelegramChannelMarker).where(TelegramChannelMarker.marker_key == marker_key))
        ).scalar_one_or_none()
        if m:
            m.telegram_message_id = msg_id
        return True
    return False


async def _send_result_replies(session: AsyncSession, channel: str) -> int:
    chat_id = _chat_id(channel)
    if chat_id is None:
        return 0
    rows = (
        await session.execute(
            select(TelegramChannelNotification, TableTennisForecastV2, TableTennisLineEvent)
            .join(TableTennisForecastV2, TableTennisForecastV2.id == TelegramChannelNotification.forecast_v2_id, isouter=True)
            .join(TableTennisLineEvent, TableTennisLineEvent.id == TelegramChannelNotification.event_id, isouter=True)
            .where(
                TelegramChannelNotification.channel == channel,
                TelegramChannelNotification.result_notified_at.is_(None),
            )
            .limit(500)
        )
    ).all()
    grouped: dict[int, list[tuple[TelegramChannelNotification, TableTennisForecastV2 | None, TableTennisLineEvent | None]]] = {}
    for n, f, e in rows:
        grouped.setdefault(int(n.telegram_message_id), []).append((n, f, e))

    sent = 0
    for message_id, entries in grouped.items():
        now_resolve = _utc_now()
        all_resolved = all(
            f is not None
            and (
                f.status in {"hit", "miss", "no_result"}
                or (
                    f.status == "cancelled"
                    and _cancelled_grace_elapsed(e, now_resolve)
                )
            )
            for _n, f, e in entries
        )
        if not all_resolved:
            continue
        lines: list[str] = []
        for _n, f, e in entries:
            if f is None:
                continue
            mark = "✅" if f.status == "hit" else "❌" if f.status == "miss" else "⚪"
            match_text = f"{e.home_name or '—'} — {e.away_name or '—'}" if e is not None else "Матч"
            lines.append(f"{mark} {match_text}: {f.status}")
        if not lines:
            continue
        text = "Итоги прогнозов:\n" + "\n".join(lines)
        ok = await _send_telegram(chat_id, text, reply_to_message_id=message_id, channel=channel)
        if not ok:
            continue
        now_ts = _utc_now()
        for n, f, _e in entries:
            n.result_notified_at = now_ts
            n.result_status = f.status if f is not None else "no_result"
        sent += 1
    return sent


async def dispatch_channel_notifications_once() -> dict[str, int]:
    now = _utc_now()
    now_msk = _msk_now(now)
    sent_free = 0
    sent_vip = 0
    urgent = 0
    replies = 0
    async with async_session_maker() as session:
        dispatch_cfg = await _load_dispatch_cfg(session)
        free_cfg = dispatch_cfg.get("free", {})
        vip_cfg = dispatch_cfg.get("vip", {})
        no_ml_cfg = dispatch_cfg.get("no_ml_channel", {})
        got_lock = bool(
            (
                await session.execute(
                    sa.text("SELECT pg_try_advisory_lock(:k)"),
                    {"k": CHANNEL_DISPATCHER_ADVISORY_LOCK_KEY},
                )
            ).scalar_one()
        )
        if not got_lock:
            return {
                "free_sent": 0,
                "vip_sent": 0,
                "urgent_sent": 0,
                "result_replies": 0,
            }
        try:
            if bool(free_cfg.get("enabled", True)):
                # FREE slots: источник и количество настраиваются по каждому слоту.
                msk_day = now_msk.strftime("%Y%m%d")
                for slot_item in list(free_cfg.get("slots", [])):
                    slot_name = _slot_time(slot_item)
                    if not slot_name or not _slot_passed(now_msk, slot_name):
                        continue
                    marker_key = f"free_slot_msk_{msk_day}_{slot_name}"
                    if await _marker_exists(session, marker_key):
                        continue
                    source = _slot_source(slot_item)
                    per_slot = max(1, int(slot_item.get("count") or 1))
                    candidates = await _pick_candidates(
                        session,
                        target_channel=CHANNEL_FREE,
                        source=source,
                        min_lead_minutes=max(0, int(free_cfg.get("min_lead_minutes", settings.telegram_free_min_lead_minutes))),
                        limit=200,
                    )
                    if not candidates:
                        continue
                    k = min(len(candidates), per_slot)
                    picks = random.sample(candidates, k=k)
                    sent_now = await _send_events_to_channel(session, CHANNEL_FREE, picks)
                    if sent_now > 0:
                        await _ensure_marker(session, marker_key, CHANNEL_FREE, "slot")
                    sent_free += sent_now

            # VIP (paid ML) slots: источник и количество настраиваются по каждому слоту.
            if bool(vip_cfg.get("enabled", True)):
                vip_day = now_msk.strftime("%Y%m%d")
                for slot_item in list(vip_cfg.get("slots", [])):
                    slot_name = _slot_time(slot_item)
                    if not slot_name or not _slot_passed(now_msk, slot_name):
                        continue
                    marker_key = f"vip_slot_msk_{vip_day}_{slot_name}"
                    if await _marker_exists(session, marker_key):
                        continue
                    source = _slot_source(slot_item)
                    per_slot = max(1, int(slot_item.get("count") or 1))
                    candidates = await _pick_candidates(
                        session=session,
                        target_channel=CHANNEL_VIP,
                        source=source,
                        min_lead_minutes=max(0, int(vip_cfg.get("min_lead_minutes", settings.telegram_free_min_lead_minutes))),
                        limit=500,
                    )
                    if not candidates:
                        continue
                    k = min(len(candidates), per_slot)
                    picks = random.sample(candidates, k=k)
                    sent_now = await _send_events_to_channel(session, CHANNEL_VIP, picks)
                    if sent_now > 0:
                        await _ensure_marker(session, marker_key, CHANNEL_VIP, "slot")
                    sent_vip += sent_now

            # FREE и VIP — только по расписанию из админки (слоты + daily_summary). Без захардкоженных fallback.

            # no_ml urgent: поздно появившиеся матчи отправляем вне расписания.
            if bool(no_ml_cfg.get("enabled", True)):
                source = str(no_ml_cfg.get("stream_source") or "no_ml").strip().lower()
                fetch_limit = max(1, int(no_ml_cfg.get("stream_fetch_limit", 500)))
                group_limit = max(1, int(no_ml_cfg.get("stream_group_limit", 20)))
                min_lead = max(0, int(no_ml_cfg.get("min_lead_minutes", settings.telegram_free_min_lead_minutes)))
                urgent_candidates = await _pick_late_appeared_candidates(
                    session=session,
                    target_channel=CHANNEL_NO_ML,
                    source=(source if source in {"paid", "no_ml", "nn"} else "no_ml"),
                    min_lead_minutes=min_lead,
                    limit=fetch_limit,
                )
                if urgent_candidates:
                    picks = urgent_candidates[:group_limit]
                    urgent += await _send_events_to_channel(session, CHANNEL_NO_ML, picks)

            # no_ml channel stream: отправляем все новые события пачкой не чаще N минут.
            if bool(no_ml_cfg.get("enabled", True)) and bool(no_ml_cfg.get("stream_enabled", False)):
                interval_minutes = max(5, int(no_ml_cfg.get("stream_interval_minutes", 30)))
                bucket_minute = (now.minute // interval_minutes) * interval_minutes
                bucket_start = datetime(
                    now.year, now.month, now.day, now.hour, bucket_minute, tzinfo=timezone.utc
                )
                marker_key = f"no_ml_stream_{bucket_start.strftime('%Y%m%d_%H%M')}"
                if await _ensure_marker(session, marker_key, CHANNEL_NO_ML, "stream_no_ml"):
                    source = str(no_ml_cfg.get("stream_source") or "no_ml").strip().lower()
                    fetch_limit = max(1, int(no_ml_cfg.get("stream_fetch_limit", 500)))
                    group_limit = max(1, int(no_ml_cfg.get("stream_group_limit", 20)))
                    candidates = await _pick_candidates(
                        session=session,
                        target_channel=CHANNEL_NO_ML,
                        source=(source if source in {"paid", "no_ml", "nn"} else "no_ml"),
                        min_lead_minutes=max(0, int(no_ml_cfg.get("min_lead_minutes", settings.telegram_free_min_lead_minutes))),
                        limit=fetch_limit,
                    )
                    if candidates:
                        picks = candidates[:group_limit]
                        await _send_events_to_channel(session, CHANNEL_NO_ML, picks)

            # Daily summaries.
            free_summary_hour = free_cfg.get("daily_summary_hour_utc")
            if bool(free_cfg.get("enabled", True)) and free_summary_hour is not None:
                await _send_daily_summary(session, CHANNEL_FREE, hour_utc=int(free_summary_hour))
            vip_summary_hour = vip_cfg.get("daily_summary_hour_utc")
            if bool(vip_cfg.get("enabled", True)) and vip_summary_hour is not None:
                await _send_daily_summary(session, CHANNEL_VIP, hour_utc=int(vip_summary_hour))
            no_ml_summary_hour = no_ml_cfg.get("daily_summary_hour_utc")
            if bool(no_ml_cfg.get("enabled", True)) and no_ml_summary_hour is not None:
                await _send_daily_summary(session, CHANNEL_NO_ML, hour_utc=int(no_ml_summary_hour))

            # Result replies.
            replies += await _send_result_replies(session, CHANNEL_FREE)
            replies += await _send_result_replies(session, CHANNEL_VIP)
            replies += await _send_result_replies(session, CHANNEL_NO_ML)

            await session.commit()
        finally:
            await session.execute(
                sa.text("SELECT pg_advisory_unlock(:k)"),
                {"k": CHANNEL_DISPATCHER_ADVISORY_LOCK_KEY},
            )
            await session.commit()

    return {
        "free_sent": sent_free,
        "vip_sent": sent_vip,
        "urgent_sent": urgent,
        "result_replies": replies,
    }


def _log_channel_config_warnings() -> None:
    """Один раз при старте: предупреждение, если не заданы токены или chat_id каналов."""
    for ch, name in ((CHANNEL_FREE, "free"), (CHANNEL_VIP, "vip"), (CHANNEL_NO_ML, "no_ml")):
        cid = _chat_id(ch)
        if ch == CHANNEL_FREE:
            token = (settings.telegram_signals_free_bot_token or "").strip()
        elif ch == CHANNEL_VIP:
            token = (settings.telegram_signals_vip_bot_token or "").strip()
        else:
            token = (settings.telegram_signals_no_ml_bot_token or "").strip()
        if not token:
            logger.warning("Telegram канал %s: не задан bot token — сообщения в канал не отправляются", name)
        if cid is None:
            logger.warning("Telegram канал %s: не задан chat_id — сообщения в канал не отправляются", name)
        elif token and name == "vip":
            logger.info(
                "Telegram VIP: закрытый канал поддерживается — бот должен быть администратором канала (chat_id=%s).",
                cid,
            )


async def telegram_channel_dispatcher_loop() -> None:
    interval = max(20, int(settings.telegram_channels_loop_interval_sec))
    logger.info("Telegram channels loop started: interval=%ss", interval)
    _log_channel_config_warnings()
    while True:
        try:
            await dispatch_channel_notifications_once()
        except Exception as e:  # noqa: BLE001
            logger.exception("Telegram channels loop error: %s", e)
        await asyncio.sleep(interval)
