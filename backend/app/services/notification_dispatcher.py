"""Dispatch grouped forecast notifications to Telegram/email."""
from __future__ import annotations

import asyncio
from html import escape
import logging
from datetime import datetime, timedelta, timezone

import httpx
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import async_session_maker
from app.models.table_tennis_forecast_v2 import TableTennisForecastV2
from app.services.subscription_access import has_analytics_subscription
from app.models.table_tennis_line_event import LINE_EVENT_STATUS_SCHEDULED, TableTennisLineEvent
from app.models.user import User
from app.models.user_forecast_notification import UserForecastNotification
from app.services.email import send_html_email

logger = logging.getLogger(__name__)
NOTIFICATIONS_ADVISORY_LOCK_KEY = 910001


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _in_quiet_hours(user: User, now_utc: datetime) -> bool:
    if user.quiet_hours_start is None or user.quiet_hours_end is None:
        return False
    now_t = now_utc.time()
    start = user.quiet_hours_start
    end = user.quiet_hours_end
    if start == end:
        return False
    if start < end:
        return start <= now_t < end
    return now_t >= start or now_t < end


def _human_countdown(starts_at: datetime, now: datetime) -> str:
    sec = int((starts_at - now).total_seconds())
    if sec <= 0:
        return "матч уже начался"
    mins = sec // 60
    if mins < 60:
        return f"через {mins} мин"
    h = mins // 60
    m = mins % 60
    return f"через {h} ч {m} мин"


def _clean_forecast_text(text: str | None) -> str:
    if not text:
        return "Недостаточно данных для расчёта"
    import re

    return re.sub(r"\s*\(\d+(?:[.,]\d+)?%\)", "", text).replace("%", "").strip()


def _event_link(event_id: str) -> str:
    base = (settings.frontend_public_url or "").strip().rstrip("/")
    if not base or "localhost" in base or "127.0.0.1" in base:
        base = "https://pingwin.pro"
    return f"{base}/dashboard/table-tennis/matches/{event_id}"


def _cancelled_grace_elapsed(event: TableTennisLineEvent | None, now: datetime) -> bool:
    if event is None or event.starts_at is None:
        return True
    return now >= (event.starts_at + timedelta(hours=2))


def _is_late_appeared(
    event: TableTennisLineEvent,
    forecast: TableTennisForecastV2,
    *,
    min_lead_minutes: int,
    now: datetime,
) -> bool:
    """Match/forecast appeared too close to start (< min_lead): send out of turn."""
    if event.starts_at is None or forecast.created_at is None:
        return False
    if event.starts_at <= now:
        return False
    threshold = event.starts_at - timedelta(minutes=max(0, min_lead_minutes))
    return forecast.created_at >= threshold


def _telegram_match_block(event: TableTennisLineEvent, forecast: TableTennisForecastV2, now: datetime) -> str:
    starts = event.starts_at.astimezone(timezone.utc) if event.starts_at else now
    when = starts.strftime("%d.%m.%Y %H:%M UTC")
    countdown = _human_countdown(starts, now)
    odds = float(forecast.odds_used) if forecast.odds_used is not None else None
    lines = [
        f"🏆 {escape(event.league_name or '—')}",
        f"{when}",
        f"⏱ {countdown}",
        f"{escape(event.home_name or '—')} — {escape(event.away_name or '—')}",
    ]
    if odds is not None:
        lines.append(f"Кф: {odds:.2f}")
    lines.append(f"Наш прогноз: {escape(_clean_forecast_text(forecast.forecast_text))}")
    lines.append(f"Аналитика матча: <a href=\"{escape(_event_link(str(event.id)))}\">открыть</a>")
    return "\n".join(lines)


def _build_telegram_batch(events: list[tuple[TableTennisLineEvent, TableTennisForecastV2]], now: datetime) -> str:
    blocks = []
    for event, forecast in events:
        blocks.append(_telegram_match_block(event, forecast, now))
    footer = "\n\n┄┄┄┄┄┄┄┄┄┄┄┄\n🐧 <a href=\"https://pingwin.pro\">pingwin.pro</a> — аналитический сервис"
    return "\n\n".join(blocks) + footer


def _build_email_batch(
    events: list[tuple[TableTennisLineEvent, TableTennisForecastV2]],
    now: datetime,
) -> tuple[str, str, str]:
    subject = f"PingWin: новые прогнозы ({len(events)})"
    lines: list[str] = []
    cards_html: list[str] = []
    for event, forecast in events:
        starts = event.starts_at.astimezone(timezone.utc) if event.starts_at else now
        link = _event_link(str(event.id))
        lines.append(f"{event.league_name or '—'}")
        lines.append(starts.strftime("%d.%m.%Y %H:%M UTC"))
        lines.append(_human_countdown(starts, now))
        lines.append(f"{event.home_name or '—'} — {event.away_name or '—'}")
        if forecast.odds_used is not None:
            lines.append(f"Кф: {float(forecast.odds_used):.2f}")
        lines.append(f"Наш прогноз: {_clean_forecast_text(forecast.forecast_text)}")
        lines.append(f"Аналитика матча: {link}")
        lines.append("")
        cards_html.append(
            (
                "<div style=\"border:1px solid #cbd5e1;border-radius:10px;padding:14px 16px;margin-bottom:12px;background:#ffffff;\">"
                f"<div style=\"font-size:14px;color:#0f172a;font-weight:700;margin-bottom:6px;\">🏆 {escape(event.league_name or '—')}</div>"
                f"<div style=\"font-size:13px;color:#334155;margin-bottom:2px;\">{starts.strftime('%d.%m.%Y %H:%M UTC')}</div>"
                f"<div style=\"font-size:13px;color:#334155;margin-bottom:8px;\">⏱ {escape(_human_countdown(starts, now))}</div>"
                f"<div style=\"font-size:14px;color:#0f172a;font-weight:600;margin-bottom:8px;\">{escape(event.home_name or '—')} — {escape(event.away_name or '—')}</div>"
                + (
                    f"<div style=\"font-size:13px;color:#334155;margin-bottom:6px;\">Кф: {float(forecast.odds_used):.2f}</div>"
                    if forecast.odds_used is not None
                    else ""
                )
                + f"<div style=\"font-size:14px;color:#0f172a;margin-bottom:8px;\"><b>Наш прогноз:</b> {escape(_clean_forecast_text(forecast.forecast_text))}</div>"
                + f"<div style=\"font-size:13px;\"><a href=\"{escape(link)}\" style=\"color:#2563eb;text-decoration:none;\">Аналитика матча</a></div>"
                + "</div>"
            )
        )
    lines.append("🐧 https://pingwin.pro — аналитический сервис")
    html = (
        "<!doctype html><html><body style=\"margin:0;padding:20px;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;\">"
        "<div style=\"max-width:680px;margin:0 auto;\">"
        "<div style=\"font-size:20px;font-weight:800;color:#0f172a;margin-bottom:14px;\">Новые прогнозы PingWin</div>"
        + "".join(cards_html)
        + "<div style=\"padding-top:8px;font-size:13px;color:#334155;\">🐧 <a href=\"https://pingwin.pro\" style=\"color:#2563eb;text-decoration:none;\">pingwin.pro</a> — аналитический сервис</div>"
        + "</div></body></html>"
    )
    return subject, "\n".join(lines), html


async def _send_telegram_message(chat_id: int, text: str) -> int | None:
    token = (settings.telegram_bot_token or "").strip()
    if not token:
        return None
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code != 200:
            logger.warning("Telegram sendMessage failed: %s %s", resp.status_code, resp.text[:300])
            return None
        data = resp.json()
        if not data.get("ok"):
            logger.warning("Telegram sendMessage not ok: %s", data)
            return None
        return int((data.get("result") or {}).get("message_id") or 0) or None


async def _reply_telegram_result(chat_id: int, message_id: int, status: str) -> bool:
    token = (settings.telegram_bot_token or "").strip()
    if not token:
        return False
    mark = "✅" if status == "hit" else "❌" if status == "miss" else "⚪"
    text = f"{mark} Итог прогноза: {status}"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "reply_to_message_id": message_id}
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code != 200:
            return False
        data = resp.json()
        return bool(data.get("ok"))


async def _reply_telegram_batch_result(chat_id: int, message_id: int, lines: list[str]) -> bool:
    token = (settings.telegram_bot_token or "").strip()
    if not token:
        return False
    text = "Итоги прогнозов:\n" + "\n".join(lines)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "reply_to_message_id": message_id}
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code != 200:
            return False
        data = resp.json()
        return bool(data.get("ok"))


async def _ensure_bot_channel_forecast(
    session: AsyncSession,
    forecast: TableTennisForecastV2,
) -> None:
    exists = (
        await session.execute(
            select(TableTennisForecastV2.id).where(
                and_(
                    TableTennisForecastV2.event_id == forecast.event_id,
                    TableTennisForecastV2.channel == "bot_signals",
                    TableTennisForecastV2.market == forecast.market,
                )
            )
        )
    ).scalar_one_or_none()
    if exists:
        return
    session.add(
        TableTennisForecastV2(
            event_id=forecast.event_id,
            model_run_id=forecast.model_run_id,
            channel="bot_signals",
            market=forecast.market,
            pick_side=forecast.pick_side,
            forecast_text=forecast.forecast_text,
            probability_pct=forecast.probability_pct,
            confidence_score=forecast.confidence_score,
            edge_pct=forecast.edge_pct,
            odds_used=forecast.odds_used,
            status=forecast.status,
            final_status=forecast.final_status,
            final_sets_score=forecast.final_sets_score,
            explanation_summary=forecast.explanation_summary,
            created_at=forecast.created_at,
            resolved_at=forecast.resolved_at,
        )
    )


async def _fetch_unsent_forecasts_for_user(
    session: AsyncSession,
    user: User,
    channel: str,
) -> list[tuple[TableTennisLineEvent, TableTennisForecastV2]]:
    now = _utc_now()
    rows_raw = (
        await session.execute(
            select(TableTennisLineEvent, TableTennisForecastV2)
            .join(
                TableTennisForecastV2,
                and_(
                    TableTennisForecastV2.event_id == TableTennisLineEvent.id,
                    TableTennisForecastV2.channel == "paid",
                    TableTennisForecastV2.status == "pending",
                ),
            )
            .where(
                TableTennisLineEvent.status == LINE_EVENT_STATUS_SCHEDULED,
                TableTennisLineEvent.starts_at > now,
            )
            .order_by(TableTennisLineEvent.starts_at.asc(), TableTennisForecastV2.created_at.desc())
            .limit(200)
        )
    ).all()
    if not rows_raw:
        return []

    # One forecast per event (latest).
    seen_event_ids: set[str] = set()
    rows: list[tuple[TableTennisLineEvent, TableTennisForecastV2]] = []
    for event, forecast in rows_raw:
        event_id = str(event.id)
        if event_id in seen_event_ids:
            continue
        seen_event_ids.add(event_id)
        rows.append((event, forecast))

    event_ids = [str(event.id) for event, _ in rows]
    sent_event_ids = {
        str(x[0])
        for x in (
            await session.execute(
                select(UserForecastNotification.event_id).where(
                    UserForecastNotification.user_id == user.id,
                    UserForecastNotification.channel == channel,
                    UserForecastNotification.event_id.in_(event_ids),
                )
            )
        ).all()
    }
    return [(e, f) for e, f in rows if str(e.id) not in sent_event_ids]


async def dispatch_forecast_notifications_once() -> dict[str, int]:
    now = _utc_now()
    batch_minutes = max(1, int(getattr(settings, "notifications_batch_interval_minutes", 30)))
    urgent_minutes = max(1, int(getattr(settings, "telegram_urgent_lead_minutes", 30)))
    min_lead_minutes = max(0, int(getattr(settings, "telegram_free_min_lead_minutes", 60)))
    delivered_events = 0
    delivered_messages = 0
    result_replies = 0

    async with async_session_maker() as session:
        # Single-run guard: avoid parallel dispatchers sending duplicated messages.
        got_lock = bool(
            (
                await session.execute(
                    sa.text("SELECT pg_try_advisory_lock(:k)"),
                    {"k": NOTIFICATIONS_ADVISORY_LOCK_KEY},
                )
            ).scalar_one()
        )
        if not got_lock:
            return {
                "delivered_messages": 0,
                "delivered_events": 0,
                "result_replies": 0,
            }
        try:
            users = (
                await session.execute(
                    select(User).where(User.is_active.is_(True), User.is_blocked.is_(False))
                )
            ).scalars().all()

            for user in users:
                if _in_quiet_hours(user, now):
                    continue
                if not await has_analytics_subscription(user.id, session):
                    continue

                channels: list[str] = []
                if user.notify_telegram and user.telegram_id is not None:
                    channels.append("telegram")
                effective_email = (user.notification_email or "").strip() or (None if user.is_telegram_only() else user.email)
                if user.notify_email and effective_email:
                    channels.append("email")
                if not channels:
                    continue

                for channel in channels:
                    unsent = await _fetch_unsent_forecasts_for_user(session, user, channel=channel)
                    if not unsent:
                        continue
                    urgent_cutoff = now + timedelta(minutes=urgent_minutes)
                    urgent_unsent = [
                        (e, f) for e, f in unsent
                        if (
                            (e.starts_at is not None and e.starts_at <= urgent_cutoff)
                            or _is_late_appeared(
                                e,
                                f,
                                min_lead_minutes=min_lead_minutes,
                                now=now,
                            )
                        )
                    ]
                    regular_unsent = [
                        (e, f) for e, f in unsent
                        if e.starts_at is None or e.starts_at > urgent_cutoff
                    ]
                    last_sent = (
                        await session.execute(
                            select(func.max(UserForecastNotification.sent_at)).where(
                                UserForecastNotification.user_id == user.id,
                                UserForecastNotification.channel == channel,
                            )
                        )
                    ).scalar_one_or_none()
                    can_send_regular = not (
                        last_sent is not None and (now - last_sent).total_seconds() < batch_minutes * 60
                    )

                    if channel == "telegram":
                        to_send_batches: list[list[tuple[TableTennisLineEvent, TableTennisForecastV2]]] = []
                        if urgent_unsent:
                            to_send_batches.append(urgent_unsent)
                        if can_send_regular and regular_unsent:
                            to_send_batches.append(regular_unsent)
                        for batch in to_send_batches:
                            message_text = _build_telegram_batch(batch, now)
                            message_id = await _send_telegram_message(int(user.telegram_id), message_text)
                            if message_id is None:
                                continue
                            delivered_messages += 1
                            rows_to_insert = []
                            for event, forecast in batch:
                                rows_to_insert.append(
                                    {
                                        "user_id": user.id,
                                        "event_id": str(event.id),
                                        "channel": "telegram",
                                        "forecast_v2_id": forecast.id,
                                        "telegram_message_id": message_id,
                                    }
                                )
                                delivered_events += 1
                            if rows_to_insert:
                                stmt = pg_insert(UserForecastNotification).values(rows_to_insert)
                                stmt = stmt.on_conflict_do_nothing(
                                    constraint="uq_user_forecast_notification_user_event_channel"
                                )
                                await session.execute(stmt)
                                # Persist delivery log immediately to survive restarts/crashes.
                                await session.commit()
                            for _event, forecast in batch:
                                try:
                                    await _ensure_bot_channel_forecast(session, forecast)
                                except Exception:  # noqa: BLE001
                                    logger.warning("Notifications: failed to ensure bot_signals forecast", exc_info=True)
                    elif channel == "email" and effective_email:
                        to_send_batches: list[list[tuple[TableTennisLineEvent, TableTennisForecastV2]]] = []
                        if urgent_unsent:
                            to_send_batches.append(urgent_unsent)
                        if can_send_regular and regular_unsent:
                            to_send_batches.append(regular_unsent)
                        for batch in to_send_batches:
                            subject, body_text, body_html = _build_email_batch(batch, now)
                            if not send_html_email(effective_email, subject, body_text, body_html):
                                continue
                            delivered_messages += 1
                            rows_to_insert = []
                            for event, forecast in batch:
                                rows_to_insert.append(
                                    {
                                        "user_id": user.id,
                                        "event_id": str(event.id),
                                        "channel": "email",
                                        "forecast_v2_id": forecast.id,
                                    }
                                )
                                delivered_events += 1
                            if rows_to_insert:
                                stmt = pg_insert(UserForecastNotification).values(rows_to_insert)
                                stmt = stmt.on_conflict_do_nothing(
                                    constraint="uq_user_forecast_notification_user_event_channel"
                                )
                                await session.execute(stmt)
                                await session.commit()
                            for _event, forecast in batch:
                                try:
                                    await _ensure_bot_channel_forecast(session, forecast)
                                except Exception:  # noqa: BLE001
                                    logger.warning("Notifications: failed to ensure bot_signals forecast", exc_info=True)

            await session.commit()

            # Reply with result for telegram notifications not yet replied.
            pending_replies = (
                await session.execute(
                    select(UserForecastNotification, User, TableTennisForecastV2, TableTennisLineEvent)
                    .join(User, User.id == UserForecastNotification.user_id)
                    .join(
                        TableTennisForecastV2,
                        TableTennisForecastV2.id == UserForecastNotification.forecast_v2_id,
                        isouter=True,
                    )
                    .join(
                        TableTennisLineEvent,
                        TableTennisLineEvent.id == UserForecastNotification.event_id,
                        isouter=True,
                    )
                    .where(
                        UserForecastNotification.channel == "telegram",
                        UserForecastNotification.telegram_message_id.is_not(None),
                        UserForecastNotification.result_notified_at.is_(None),
                    )
                    .limit(500)
                )
            ).all()

            grouped: dict[tuple[str, int], list[tuple[UserForecastNotification, User, TableTennisForecastV2 | None, TableTennisLineEvent | None]]] = {}
            for row, user, forecast, event in pending_replies:
                key = (str(user.id), int(row.telegram_message_id or 0))
                grouped.setdefault(key, []).append((row, user, forecast, event))

            for (_user_id, message_id), entries in grouped.items():
                user = entries[0][1]
                if user.telegram_id is None:
                    continue
                # Wait until all matches from the original batch are resolved.
                now_resolve = _utc_now()
                all_resolved = all(
                    forecast is not None
                    and (
                        forecast.status in {"hit", "miss", "no_result"}
                        or (
                            forecast.status == "cancelled"
                            and _cancelled_grace_elapsed(event, now_resolve)
                        )
                    )
                    for _row, _user, forecast, event in entries
                )
                if not all_resolved:
                    continue

                lines: list[str] = []
                for row, _u, forecast, event in entries:
                    if forecast is None:
                        continue
                    mark = "✅" if forecast.status == "hit" else "❌" if forecast.status == "miss" else "⚪"
                    match_text = "Матч"
                    if event is not None:
                        match_text = f"{event.home_name or '—'} — {event.away_name or '—'}"
                    lines.append(f"{mark} {match_text}: {forecast.status}")
                if not lines:
                    continue

                ok = await _reply_telegram_batch_result(int(user.telegram_id), message_id, lines)
                if ok:
                    now_resolved = _utc_now()
                    for row, _u, forecast, _event in entries:
                        row.result_notified_at = now_resolved
                        row.result_status = forecast.status if forecast is not None else "no_result"
                    result_replies += 1
            await session.commit()
        finally:
            await session.execute(
                sa.text("SELECT pg_advisory_unlock(:k)"),
                {"k": NOTIFICATIONS_ADVISORY_LOCK_KEY},
            )
            await session.commit()

    if delivered_messages or result_replies:
        logger.info(
            "Notifications: delivered_messages=%s delivered_events=%s result_replies=%s",
            delivered_messages,
            delivered_events,
            result_replies,
        )
    return {
        "delivered_messages": delivered_messages,
        "delivered_events": delivered_events,
        "result_replies": result_replies,
    }


async def forecast_notifications_loop() -> None:
    interval = max(20, int(getattr(settings, "notifications_loop_interval_sec", 60)))
    logger.info("Notifications: starting loop (interval=%ss)", interval)
    while True:
        try:
            await dispatch_forecast_notifications_once()
        except Exception as e:  # noqa: BLE001
            logger.exception("Notifications: loop error: %s", e)
        await asyncio.sleep(interval)
