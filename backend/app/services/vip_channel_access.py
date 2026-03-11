"""VIP Telegram channel access: invite on activation, revoke on expiry."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta, timezone

import httpx
import sqlalchemy as sa
from sqlalchemy import and_, select

from app.config import settings
from app.db.session import async_session_maker
from app.models.user import User
from app.models.user_subscription import UserSubscription

logger = logging.getLogger(__name__)
VIP_ACCESS_ADVISORY_LOCK_KEY = 910003


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _vip_chat_id() -> int | None:
    raw = (settings.telegram_signals_vip_chat_id or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def vip_public_url() -> str | None:
    raw = (settings.telegram_signals_vip_public_url or "").strip()
    return raw or None


async def _telegram_api(method: str, payload: dict) -> dict | None:
    token = (settings.telegram_bot_token or "").strip()
    if not token:
        return None
    url = f"https://api.telegram.org/bot{token}/{method}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(url, json=payload)
    if resp.status_code != 200:
        logger.warning("Telegram %s failed: %s %s", method, resp.status_code, resp.text[:300])
        return None
    data = resp.json()
    if not data.get("ok"):
        logger.warning("Telegram %s not ok: %s", method, data)
        return None
    return data


async def _send_telegram_message(chat_id: int, text: str) -> bool:
    data = await _telegram_api(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
    )
    return bool(data)


async def get_vip_member_status(telegram_user_id: int) -> str | None:
    chat_id = _vip_chat_id()
    if chat_id is None:
        return None
    data = await _telegram_api(
        "getChatMember",
        {
            "chat_id": chat_id,
            "user_id": int(telegram_user_id),
        },
    )
    if not data:
        return None
    return str((data.get("result") or {}).get("status") or "") or None


def is_vip_member_status(status: str | None) -> bool:
    return (status or "") in {"member", "administrator", "creator", "restricted"}


async def create_vip_invite_link(user: User, valid_until: date) -> str | None:
    chat_id = _vip_chat_id()
    if chat_id is None:
        return None
    # Link is limited to one user and expires slightly after subscription end.
    expire_dt = datetime.combine(valid_until + timedelta(days=1), time(hour=0, minute=30), tzinfo=timezone.utc)
    data = await _telegram_api(
        "createChatInviteLink",
        {
            "chat_id": chat_id,
            "name": f"vip-{user.id}",
            "member_limit": 1,
            "expire_date": int(expire_dt.timestamp()),
        },
    )
    if not data:
        return None
    return str((data.get("result") or {}).get("invite_link") or "") or None


async def send_vip_invite_to_user(user: User, valid_until: date) -> bool:
    if user.telegram_id is None:
        return False
    member_status = await get_vip_member_status(int(user.telegram_id))
    channel_link = vip_public_url()
    if is_vip_member_status(member_status):
        text = (
            "✅ Подписка VIP активирована. Вы уже состоите в VIP-канале."
            + (f"\nОткрыть канал: {channel_link}" if channel_link else "")
        )
        return await _send_telegram_message(int(user.telegram_id), text)
    invite = await create_vip_invite_link(user, valid_until)
    if not invite:
        return False
    text = (
        "✅ Оплата подтверждена. Доступ к VIP-каналу активирован.\n\n"
        f"Ссылка для входа: {invite}\n"
        f"Подписка активна до: {valid_until.isoformat()} (UTC)\n\n"
        "После истечения подписки доступ к каналу будет автоматически закрыт."
    )
    return await _send_telegram_message(int(user.telegram_id), text)


async def revoke_vip_channel_access(telegram_user_id: int) -> bool:
    chat_id = _vip_chat_id()
    if chat_id is None:
        return False
    # Remove from channel/group and allow future rejoin on next active subscription.
    await _telegram_api(
        "banChatMember",
        {
            "chat_id": chat_id,
            "user_id": int(telegram_user_id),
            "revoke_messages": False,
        },
    )
    await _telegram_api(
        "unbanChatMember",
        {
            "chat_id": chat_id,
            "user_id": int(telegram_user_id),
            "only_if_banned": True,
        },
    )
    return True


async def enforce_vip_channel_access_once() -> dict[str, int]:
    removed = 0
    scanned = 0
    today = _utc_now().date()
    async with async_session_maker() as session:
        got_lock = bool(
            (
                await session.execute(
                    sa.text("SELECT pg_try_advisory_lock(:k)"),
                    {"k": VIP_ACCESS_ADVISORY_LOCK_KEY},
                )
            ).scalar_one()
        )
        if not got_lock:
            return {"scanned": 0, "removed": 0}
        try:
            active_rows = (
                await session.execute(
                    select(UserSubscription.user_id).where(
                        and_(
                            UserSubscription.service_key == "vip_channel",
                            UserSubscription.valid_until >= today,
                        )
                    )
                )
            ).all()
            active_user_ids = {str(r[0]) for r in active_rows}

            users = (
                await session.execute(
                    select(User).where(User.telegram_id.is_not(None))
                )
            ).scalars().all()
            for u in users:
                scanned += 1
                if str(u.id) in active_user_ids:
                    continue
                if u.telegram_id is None:
                    continue
                ok = await revoke_vip_channel_access(int(u.telegram_id))
                if ok:
                    removed += 1
            return {"scanned": scanned, "removed": removed}
        finally:
            await session.execute(
                sa.text("SELECT pg_advisory_unlock(:k)"),
                {"k": VIP_ACCESS_ADVISORY_LOCK_KEY},
            )
            await session.commit()


async def vip_channel_access_loop() -> None:
    interval = max(60, int(getattr(settings, "vip_access_check_interval_sec", 600)))
    while True:
        try:
            await enforce_vip_channel_access_once()
        except Exception:
            logger.exception("vip_channel_access_loop failed")
        await asyncio.sleep(interval)

