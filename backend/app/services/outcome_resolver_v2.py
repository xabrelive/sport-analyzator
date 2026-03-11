"""Outcome resolver for table tennis forecast V2."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.table_tennis_forecast_v2 import TableTennisForecastV2
from app.models.table_tennis_line_event import (
    LINE_EVENT_STATUS_CANCELLED,
    LINE_EVENT_STATUS_FINISHED,
    LINE_EVENT_STATUS_LIVE,
    LINE_EVENT_STATUS_POSTPONED,
    LINE_EVENT_STATUS_SCHEDULED,
    TableTennisLineEvent,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_sets_score(value: str | None) -> tuple[int | None, int | None]:
    if not value or "-" not in value:
        return None, None
    left, right = value.split("-", 1)
    try:
        return int(left), int(right)
    except (TypeError, ValueError):
        return None, None


def _winner_match(event: TableTennisLineEvent) -> str | None:
    hs, as_ = _parse_sets_score(event.live_sets_score)
    if hs is None or as_ is None or hs == as_:
        return None
    return "home" if hs > as_ else "away"


def _is_match_score_final(event: TableTennisLineEvent) -> bool:
    """Conservative final-check for match markets.

    Prevents early resolve for in-play partial scores like 0-2.
    """
    hs, as_ = _parse_sets_score(event.live_sets_score)
    if hs is None or as_ is None or hs == as_:
        return False
    sets_to_win = max(1, int(getattr(settings, "table_tennis_match_sets_to_win", 3)))
    return max(hs, as_) >= sets_to_win


def _is_completed_set_score(home: int, away: int) -> bool:
    winner = max(home, away)
    loser = min(home, away)
    return winner >= 11 and (winner - loser) >= 2


def _has_in_progress_set_fragment(event: TableTennisLineEvent) -> bool:
    if not isinstance(event.live_score, dict):
        return False
    for _, set_data in event.live_score.items():
        if not isinstance(set_data, dict):
            continue
        home_raw = set_data.get("home")
        away_raw = set_data.get("away")
        if home_raw is None and away_raw is None:
            continue
        try:
            home = int(str(home_raw or "0"))
            away = int(str(away_raw or "0"))
        except ValueError:
            continue
        # Ignore empty placeholder sets.
        if home == 0 and away == 0:
            continue
        if not _is_completed_set_score(home, away):
            return True
    return False


def _winner_set(event: TableTennisLineEvent, set_no: str) -> str | None:
    if not isinstance(event.live_score, dict):
        return None
    set_data = event.live_score.get(set_no)
    if not isinstance(set_data, dict):
        return None
    try:
        h = int(str(set_data.get("home") or "0"))
        a = int(str(set_data.get("away") or "0"))
    except ValueError:
        return None
    if not _is_completed_set_score(h, a):
        return None
    if h == a:
        return None
    return "home" if h > a else "away"


def _cancelled_grace_elapsed(event: TableTennisLineEvent, now: datetime) -> bool:
    """Treat cancellation as final only after 2h from planned start."""
    if event.starts_at is None:
        return True
    return now >= (event.starts_at + timedelta(hours=2))


async def resolve_forecast_outcomes_once(session: AsyncSession, limit: int = 1000) -> int:
    """Resolve V2 forecasts using latest event status/scores."""
    forecasts = (
        await session.execute(
            select(TableTennisForecastV2)
            .where(TableTennisForecastV2.status.in_(["pending", "cancelled", "no_result", "hit", "miss"]))
            .order_by(TableTennisForecastV2.created_at.asc())
            .limit(limit)
        )
    ).scalars().all()

    if not forecasts:
        return 0

    updated = 0
    now = _utc_now()
    for fc in forecasts:
        event = (
            await session.execute(
                select(TableTennisLineEvent).where(TableTennisLineEvent.id == fc.event_id).limit(1)
            )
        ).scalar_one_or_none()
        if not event:
            continue

        winner_by_sets = _winner_match(event)

        # Если матч снова активен, снимаем "cancelled/no_result" и возвращаем прогноз в pending.
        if event.status in {LINE_EVENT_STATUS_SCHEDULED, LINE_EVENT_STATUS_LIVE, LINE_EVENT_STATUS_POSTPONED}:
            if fc.status in {"cancelled", "no_result"}:
                fc.status = "pending"
                fc.final_status = None
                fc.final_sets_score = None
                fc.resolved_at = None
                updated += 1
            # Self-heal: для рынка match не держим итог (hit/miss), пока матч не финализирован.
            elif fc.market == "match" and fc.status in {"hit", "miss"}:
                fc.status = "pending"
                fc.final_status = None
                fc.final_sets_score = None
                fc.resolved_at = None
                updated += 1
            elif fc.market in {"set1", "set2"} and fc.status in {"hit", "miss"}:
                set_no = "1" if fc.market == "set1" else "2"
                if _winner_set(event, set_no) is None:
                    fc.status = "pending"
                    fc.final_status = None
                    fc.final_sets_score = None
                    fc.resolved_at = None
                    updated += 1
            continue

        # Cancelled оставляем только если нет явного победителя по сетам.
        if event.status == LINE_EVENT_STATUS_CANCELLED and winner_by_sets is None:
            if not _cancelled_grace_elapsed(event, now):
                # Too early to lock cancellation; keep pending.
                if fc.status in {"cancelled", "no_result"}:
                    fc.status = "pending"
                    fc.final_status = None
                    fc.final_sets_score = None
                    fc.resolved_at = None
                    updated += 1
                continue
            fc.status = "cancelled"
            fc.final_status = "cancelled"
            fc.final_sets_score = event.live_sets_score
            fc.resolved_at = now
            updated += 1
            continue

        # Для матчевого рынка разрешаем только финальные сценарии:
        # 1) event.status=finished
        # 2) event.status=cancelled, но есть финальный счёт по сетам (редкий кейс лагов статуса)
        can_resolve_match_market = (
            (
                event.status == LINE_EVENT_STATUS_FINISHED
                and winner_by_sets is not None
                and _is_match_score_final(event)
                and not _has_in_progress_set_fragment(event)
            )
            or (
                event.status == LINE_EVENT_STATUS_CANCELLED
                and winner_by_sets is not None
                and _is_match_score_final(event)
                and not _has_in_progress_set_fragment(event)
            )
        )

        winner: str | None
        if fc.market == "match":
            # Self-heal: rollback accidentally resolved match outcomes for non-final events.
            if fc.status in {"hit", "miss"} and not can_resolve_match_market:
                fc.status = "pending"
                fc.final_status = None
                fc.final_sets_score = None
                fc.resolved_at = None
                updated += 1
                continue
            if not can_resolve_match_market:
                continue
            winner = winner_by_sets
        elif fc.market == "set1":
            winner = _winner_set(event, "1")
        elif fc.market == "set2":
            winner = _winner_set(event, "2")
        else:
            winner = None

        if winner is None:
            fc.status = "no_result"
            fc.final_status = "no_result"
        else:
            fc.status = "hit" if winner == fc.pick_side else "miss"
            fc.final_status = fc.status
        fc.final_sets_score = event.live_sets_score
        fc.resolved_at = now
        updated += 1

    if updated:
        await session.commit()
    return updated
