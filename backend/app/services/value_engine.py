"""Value detection: EV = (model_probability * odds) - 1."""
from decimal import Decimal

from app.config import settings


def expected_value(probability: Decimal, odds: float) -> Decimal:
    """EV = (P * odds) - 1. Positive = value."""
    return (probability * Decimal(str(odds))) - Decimal("1")


def is_value(
    model_probability: Decimal,
    odds: float,
    ev_threshold: float | None = None,
    min_odds: float | None = None,
    max_odds: float | None = None,
) -> tuple[bool, Decimal]:
    """
    Returns (is_value, ev).
    Value if EV >= ev_threshold and min_odds <= odds <= max_odds.
    """
    ev = expected_value(model_probability, odds)
    threshold = ev_threshold if ev_threshold is not None else settings.value_ev_threshold
    min_o = min_odds if min_odds is not None else settings.min_odds
    max_o = max_odds if max_odds is not None else settings.max_odds
    ok = ev >= threshold and min_o <= odds <= max_o
    return ok, ev
