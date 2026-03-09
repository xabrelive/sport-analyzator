"""
Управление платным Telegram-каналом: приглашение по инвайт-ссылке и удаление при истечении подписки.
Бот должен быть администратором канала/супергруппы с правами приглашать и банить.
"""
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.telegram.org/bot"


def _api_url(method: str) -> str:
    return f"{BASE_URL}{settings.telegram_bot_token}/{method}"


def _post_sync(method: str, **params: Any) -> dict | None:
    if not settings.telegram_bot_token:
        return None
    url = _api_url(method)
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(url, json={k: v for k, v in params.items() if v is not None})
            if not r.is_success:
                logger.warning("Telegram %s failed: %s %s", method, r.status_code, r.text[:200])
                return None
            data = r.json()
            if not data.get("ok"):
                return None
            return data.get("result")
    except Exception as e:
        logger.exception("Telegram %s error: %s", method, e)
        return None


async def _post_async(method: str, **params: Any) -> dict | None:
    if not settings.telegram_bot_token:
        return None
    url = _api_url(method)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, json={k: v for k, v in params.items() if v is not None})
            if not r.is_success:
                logger.warning("Telegram %s failed: %s %s", method, r.status_code, r.text[:200])
                return None
            data = r.json()
            if not data.get("ok"):
                return None
            return data.get("result")
    except Exception as e:
        logger.exception("Telegram %s error: %s", method, e)
        return None


def create_chat_invite_link_sync(chat_id: str | int, member_limit: int = 1) -> str | None:
    """Создать одноразовую инвайт-ссылку (member_limit=1). Возвращает invite_link или None."""
    result = _post_sync("createChatInviteLink", chat_id=chat_id, member_limit=member_limit)
    if not result or not isinstance(result, dict):
        return None
    return result.get("invite_link")


async def create_chat_invite_link_async(chat_id: str | int, member_limit: int = 1) -> str | None:
    result = await _post_async("createChatInviteLink", chat_id=chat_id, member_limit=member_limit)
    if not result or not isinstance(result, dict):
        return None
    return result.get("invite_link")


def ban_chat_member_sync(chat_id: str | int, user_id: int) -> bool:
    """Удалить и забанить пользователя в канале/супергруппе."""
    result = _post_sync("banChatMember", chat_id=chat_id, user_id=user_id)
    return result is True


async def ban_chat_member_async(chat_id: str | int, user_id: int) -> bool:
    result = await _post_async("banChatMember", chat_id=chat_id, user_id=user_id)
    return result is True


def unban_chat_member_sync(chat_id: str | int, user_id: int) -> bool:
    """Снять бан (чтобы пользователь мог зайти по новой ссылке)."""
    result = _post_sync("unbanChatMember", chat_id=chat_id, user_id=user_id)
    return result is True


async def unban_chat_member_async(chat_id: str | int, user_id: int) -> bool:
    result = await _post_async("unbanChatMember", chat_id=chat_id, user_id=user_id)
    return result is True


def _pricing_url() -> str:
    base = (settings.frontend_public_url or settings.frontend_url or "").rstrip("/")
    return f"{base}/pricing"


def _send_message_sync(chat_id: int | str, text: str) -> bool:
    from app.services.telegram_sender import send_telegram_message
    return send_telegram_message(chat_id, text, parse_mode=None)


def invite_user_to_paid_channel_sync(telegram_id: int) -> bool:
    """
    Пригласить пользователя в платный канал: снять бан (если был), создать инвайт-ссылку,
    отправить в личку сообщение со ссылкой.
    """
    chat_id = (settings.telegram_signals_paid_chat_id or "").strip()
    if not chat_id:
        return False
    unban_chat_member_sync(chat_id, telegram_id)
    invite_link = create_chat_invite_link_sync(chat_id, member_limit=1)
    if not invite_link:
        logger.warning("Could not create invite link for paid channel")
        return False
    text = (
        "Вы оформили подписку на платный канал PingWin.\n\n"
        "Перейдите по ссылке, чтобы присоединиться к каналу (ссылка одноразовая):\n"
        f"{invite_link}"
    )
    return _send_message_sync(telegram_id, text)


async def invite_user_to_paid_channel_async(telegram_id: int) -> bool:
    chat_id = (settings.telegram_signals_paid_chat_id or "").strip()
    if not chat_id:
        return False
    await unban_chat_member_async(chat_id, telegram_id)
    invite_link = await create_chat_invite_link_async(chat_id, member_limit=1)
    if not invite_link:
        logger.warning("Could not create invite link for paid channel")
        return False
    text = (
        "Вы оформили подписку на платный канал PingWin.\n\n"
        "Перейдите по ссылке, чтобы присоединиться к каналу (ссылка одноразовая):\n"
        f"{invite_link}"
    )
    from app.services.telegram_sender import send_telegram_message_async
    return await send_telegram_message_async(telegram_id, text, parse_mode=None)


def remove_from_paid_channel_and_notify_sync(telegram_id: int) -> bool:
    """
    Удалить пользователя из платного канала (ban) и отправить в личку сообщение
    об истечении подписки со ссылкой на страницу тарифов.
    """
    chat_id = (settings.telegram_signals_paid_chat_id or "").strip()
    if not chat_id:
        return False
    ban_chat_member_sync(chat_id, telegram_id)
    pricing = _pricing_url()
    text = (
        "Ваша подписка на платный канал PingWin истекла.\n\n"
        "Чтобы продлить подписку и снова получать доступ к каналу, перейдите на страницу тарифов:\n"
        f"{pricing}"
    )
    return _send_message_sync(telegram_id, text)


async def remove_from_paid_channel_and_notify_async(telegram_id: int) -> bool:
    chat_id = (settings.telegram_signals_paid_chat_id or "").strip()
    if not chat_id:
        return False
    await ban_chat_member_async(chat_id, telegram_id)
    pricing = _pricing_url()
    text = (
        "Ваша подписка на платный канал PingWin истекла.\n\n"
        "Чтобы продлить подписку и снова получать доступ к каналу, перейдите на страницу тарифов:\n"
        f"{pricing}"
    )
    from app.services.telegram_sender import send_telegram_message_async
    return await send_telegram_message_async(telegram_id, text, parse_mode=None)
