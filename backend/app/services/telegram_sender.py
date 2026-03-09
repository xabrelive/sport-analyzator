"""Сервис отправки сообщений в Telegram. Отдельный модуль для рассылки сигналов и уведомлений."""
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _send_message_internal(
    url: str, payload: dict[str, Any], disable_web_page_preview: bool = False
) -> tuple[bool, int | None]:
    """POST sendMessage (sync); returns (success, message_id from result)."""
    if disable_web_page_preview:
        payload = {**payload, "disable_web_page_preview": True}
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(url, json=payload)
        if not r.is_success:
            logger.warning("Telegram sendMessage failed: %s %s", r.status_code, r.text)
            return False, None
        data = r.json()
        result = data.get("result") if isinstance(data, dict) else None
        msg_id = result.get("message_id") if isinstance(result, dict) else None
        return True, int(msg_id) if msg_id is not None else None
    except Exception as e:
        logger.exception("Telegram send failed: %s", e)
        return False, None


def send_telegram_message(
    chat_id: int | str,
    text: str,
    parse_mode: str | None = "HTML",
    disable_web_page_preview: bool = False,
) -> bool:
    """
    Отправить сообщение в Telegram в указанный chat_id (пользователь или канал).
    parse_mode: "HTML", "Markdown" или None для обычного текста.
    disable_web_page_preview: отключить превью ссылок.
    Возвращает True при успехе.
    """
    if not settings.telegram_bot_token:
        logger.warning("Telegram bot token not configured, skip send")
        return False
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    ok, _ = _send_message_internal(url, payload, disable_web_page_preview=disable_web_page_preview)
    return ok


def send_telegram_message_return_id(
    chat_id: int | str,
    text: str,
    parse_mode: str | None = "HTML",
    disable_web_page_preview: bool = False,
) -> tuple[bool, int | None]:
    """
    Отправить сообщение в Telegram. Возвращает (success, message_id или None).
    """
    if not settings.telegram_bot_token:
        logger.warning("Telegram bot token not configured, skip send")
        return False, None
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    return _send_message_internal(url, payload, disable_web_page_preview=disable_web_page_preview)


def send_telegram_reply(
    chat_id: int | str, reply_to_message_id: int, text: str, parse_mode: str | None = None
) -> bool:
    """Отправить ответ на сообщение в Telegram (reply)."""
    if not settings.telegram_bot_token:
        logger.warning("Telegram bot token not configured, skip reply")
        return False
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "reply_to_message_id": reply_to_message_id,
        "text": text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(url, json=payload)
            if not r.is_success:
                logger.warning("Telegram sendMessage reply failed: %s %s", r.status_code, r.text)
                return False
            return True
    except Exception as e:
        logger.exception("Telegram reply failed: %s", e)
        return False


async def send_telegram_message_async(
    chat_id: int | str,
    text: str,
    parse_mode: str | None = "HTML",
    disable_web_page_preview: bool = False,
) -> bool:
    """Асинхронная отправка сообщения в Telegram."""
    if not settings.telegram_bot_token:
        logger.warning("Telegram bot token not configured, skip send")
        return False
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if disable_web_page_preview:
        payload["disable_web_page_preview"] = True
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, json=payload)
            if not r.is_success:
                logger.warning("Telegram sendMessage failed: %s %s", r.status_code, r.text)
                return False
            return True
    except Exception as e:
        logger.exception("Telegram send failed: %s", e)
        return False
