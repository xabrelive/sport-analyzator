"""Signal engine: filter value bets and send to Telegram."""
from decimal import Decimal
from typing import Any

import httpx

from app.config import settings
from app.services.value_engine import expected_value, is_value


def build_signal_message(
    match_label: str,
    current_score: str,
    selection: str,
    odds: float,
    model_probability: Decimal,
    ev: Decimal,
) -> str:
    return (
        f"🎾 Value signal\n"
        f"Match: {match_label}\n"
        f"Score: {current_score}\n"
        f"Pick: {selection}\n"
        f"Odds: {odds}\n"
        f"Model P: {model_probability:.2%}\n"
        f"EV: {ev:.2%}"
    )


async def send_telegram_signal(message: str) -> bool:
    if not settings.telegram_bot_token or not settings.telegram_signals_chat_id:
        return False
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": settings.telegram_signals_chat_id,
        "text": message,
        "parse_mode": "HTML",
    }
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(url, json=payload, timeout=30.0)
            return r.is_success
        except Exception:
            return False


def should_send_signal(
    model_probability: Decimal,
    odds: float,
    ev_threshold: float | None = None,
) -> tuple[bool, Decimal]:
    """Returns (should_send, ev)."""
    return is_value(model_probability, odds, ev_threshold=ev_threshold)
