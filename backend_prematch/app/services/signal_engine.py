"""Signal engine: filter value bets, build message. Доставка — через telegram_sender и email сервисы."""
from decimal import Decimal

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


async def send_telegram_signal(message: str, chat_id: str | int | None = None) -> bool:
    """Отправить сигнал в Telegram: в chat_id или в общий telegram_signals_chat_id."""
    from app.config import settings
    from app.services.telegram_sender import send_telegram_message_async

    target = chat_id if chat_id is not None else (settings.telegram_signals_chat_id or None)
    if not target:
        return False
    return await send_telegram_message_async(target, message)


def should_send_signal(
    model_probability: Decimal,
    odds: float,
    ev_threshold: float | None = None,
) -> tuple[bool, Decimal]:
    """Returns (should_send, ev)."""
    return is_value(model_probability, odds, ev_threshold=ev_threshold)
