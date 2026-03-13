"""Forecast V2 loops and orchestration."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, func, or_, select

from app.config import settings
from app.db.session import async_session_maker
from app.models.table_tennis_forecast_early_scan import TableTennisForecastEarlyScan
from app.models.table_tennis_forecast_explanation import TableTennisForecastExplanation
from app.models.table_tennis_forecast_v2 import TableTennisForecastV2
from app.models.table_tennis_line_event import (
    LINE_EVENT_STATUS_CANCELLED,
    LINE_EVENT_STATUS_LIVE,
    LINE_EVENT_STATUS_POSTPONED,
    LINE_EVENT_STATUS_SCHEDULED,
    TableTennisLineEvent,
)
from app.models.table_tennis_model_run import TableTennisModelRun
from app.services.ml_scorer import score_match_for_forecast
from app.services.outcome_resolver_v2 import resolve_forecast_outcomes_once
from app.services.pick_selector import select_pick
from app.services.table_tennis_analytics import compute_forecast_for_event

logger = logging.getLogger(__name__)

_kpi_runtime_state: dict[str, float] = {
    "dynamic_min_confidence_pct": 74.0,
    "dynamic_min_edge_pct": 3.0,
    "dynamic_min_odds": 1.6,
    "last_hit_rate": 0.0,
    "last_picks_per_day": 0.0,
    "last_updated_at": 0.0,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _init_kpi_runtime_defaults() -> None:
    if _kpi_runtime_state["last_updated_at"] > 0:
        return
    _kpi_runtime_state["dynamic_min_confidence_pct"] = float(
        settings.betsapi_table_tennis_v2_base_min_confidence
    )
    _kpi_runtime_state["dynamic_min_edge_pct"] = float(
        settings.betsapi_table_tennis_v2_base_min_edge
    )
    _kpi_runtime_state["dynamic_min_odds"] = float(
        settings.betsapi_table_tennis_min_odds_for_forecast
    )


async def _ensure_active_model_run() -> int:
    async with async_session_maker() as session:
        active = (
            await session.execute(
                select(TableTennisModelRun)
                .where(TableTennisModelRun.is_active.is_(True))
                .order_by(TableTennisModelRun.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if active:
            return active.id

        row = TableTennisModelRun(
            model_name="tt_ml_xgboost",
            model_version="v1.0.0",
            params_json={
                "weights": {
                    "form_delta": 1.9,
                    "h2h": 0.9,
                    "fatigue": 0.008,
                }
            },
            metrics_json={"bootstrap": True},
            is_active=True,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.id


async def run_forecast_v2_once(limit: int = 400, channel: str = "paid") -> int:
    """Создаёт прогнозы только для матчей в окне 1–3 часа до начала (Stage 2)."""
    _init_kpi_runtime_defaults()
    model_run_id = await _ensure_active_model_run()
    now = _utc_now()
    delay_minutes = max(0, settings.betsapi_table_tennis_forecast_delay_minutes)
    earliest_created_at = now - timedelta(minutes=delay_minutes)
    min_min = getattr(settings, "betsapi_table_tennis_forecast_min_minutes_before", 60)
    max_min = getattr(settings, "betsapi_table_tennis_forecast_max_minutes_before", 180)
    window_start = now + timedelta(minutes=min_min)
    window_end = now + timedelta(minutes=max_min)

    async with async_session_maker() as session:
        events = (
            await session.execute(
                select(TableTennisLineEvent).where(
                    and_(
                        TableTennisLineEvent.status == LINE_EVENT_STATUS_SCHEDULED,
                        TableTennisLineEvent.starts_at > now,
                        TableTennisLineEvent.starts_at <= now + timedelta(hours=3),
                        TableTennisLineEvent.starts_at >= window_start,
                        TableTennisLineEvent.starts_at <= window_end,
                        TableTennisLineEvent.created_at <= earliest_created_at,
                        TableTennisLineEvent.odds_1.is_not(None),
                        TableTennisLineEvent.odds_2.is_not(None),
                    )
                )
                .order_by(TableTennisLineEvent.starts_at.asc())
                .limit(limit)
            )
        ).scalars().all()

        created = 0
        for event in events:
            existing = (
                await session.execute(
                    select(TableTennisForecastV2)
                    .where(
                        and_(
                            TableTennisForecastV2.event_id == event.id,
                            TableTennisForecastV2.channel == channel,
                        )
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            # Где уже дали прогноз — не пересчитываем
            if existing and existing.status in {"pending", "hit", "miss", "cancelled", "no_result"}:
                continue

            scored_result = score_match_for_forecast(event)
            if scored_result is None:
                continue
            scored, use_ml = scored_result

            selected = select_pick(
                scored=scored,
                odds_home=float(event.odds_1 or 0.0),
                odds_away=float(event.odds_2 or 0.0),
                min_odds=float(_kpi_runtime_state["dynamic_min_odds"]),
                min_confidence_pct=float(_kpi_runtime_state["dynamic_min_confidence_pct"]),
                min_edge_pct=float(_kpi_runtime_state["dynamic_min_edge_pct"]),
            )
            if not selected:
                continue

            row = existing or TableTennisForecastV2(
                event_id=event.id,
                channel=channel,
                model_run_id=model_run_id,
            )
            row.market = selected.market
            row.pick_side = selected.side
            row.forecast_text = selected.forecast_text
            row.probability_pct = selected.probability_pct
            row.edge_pct = selected.edge_pct
            row.confidence_score = selected.confidence_score
            row.odds_used = selected.odds_used
            row.status = "pending"
            row.final_status = None
            row.final_sets_score = None
            ml_tag = " [ML]" if use_ml else ""
            row.explanation_summary = (
                f"Tier {selected.quality_tier}{ml_tag}: edge {selected.edge_pct:.2f}%, conf {selected.confidence_score:.2f}%"
            )
            if not existing:
                session.add(row)
                await session.flush()
            else:
                await session.flush()

            await session.execute(
                delete(TableTennisForecastExplanation).where(
                    TableTennisForecastExplanation.forecast_v2_id == row.id
                )
            )
            for factor in scored.factors[:5]:
                session.add(
                    TableTennisForecastExplanation(
                        forecast_v2_id=row.id,
                        factor_key=str(factor.get("factor_key") or "unknown"),
                        factor_label=str(factor.get("factor_label") or "Фактор"),
                        factor_value=str(factor.get("factor_value") or ""),
                        contribution=float(factor.get("contribution") or 0.0),
                        direction=str(factor.get("direction") or "neutral"),
                        rank=int(factor.get("rank") or 0),
                    )
                )
            created += 1

        if created:
            await session.commit()
        return created


async def run_no_ml_forecast_once(limit: int = 400, channel: str = "no_ml") -> int:
    """Создаёт прематч‑прогнозы «без ML» на основе статистики игроков.

    Логика максимально повторяет старый backend_prematch: считаем по истории матчей
    и сетов, формируем текст вида «П1 победа в матче ...» или «П2 выиграет 1-й сет ...».
    """
    now = _utc_now()
    # Для аналитики без ML берём широкий прематч-интервал: от текущего момента до 8 часов вперёд.
    window_start = now
    window_end = now + timedelta(hours=8)

    min_odds = float(getattr(settings, "betsapi_table_tennis_min_odds_for_forecast", 1.4))

    async with async_session_maker() as session:
        events = (
            await session.execute(
                select(TableTennisLineEvent)
                .where(
                    and_(
                        TableTennisLineEvent.status == LINE_EVENT_STATUS_SCHEDULED,
                        TableTennisLineEvent.starts_at >= window_start,
                        TableTennisLineEvent.starts_at <= window_end,
                        TableTennisLineEvent.odds_1.is_not(None),
                        TableTennisLineEvent.odds_2.is_not(None),
                    )
                )
                .order_by(TableTennisLineEvent.starts_at.asc())
                .limit(limit)
            )
        ).scalars().all()

        created = 0
        for event in events:
            # Прогноз уже есть для этого рынка и канала — не пересчитываем.
            # Рынок определяем позже, поэтому сначала считаем текст.
            text, conf = await compute_forecast_for_event(session, event)
            if not text:
                continue

            t = text.lower()
            if "п1" in t:
                side = "home"
            elif "п2" in t:
                side = "away"
            else:
                # Неподдерживаемый формат текста.
                continue

            if "1-й сет" in t:
                market = "set1"
            elif "2-й сет" in t:
                market = "set2"
            else:
                market = "match"

            existing = (
                await session.execute(
                    select(TableTennisForecastV2)
                    .where(
                        and_(
                            TableTennisForecastV2.event_id == event.id,
                            TableTennisForecastV2.channel == channel,
                            TableTennisForecastV2.market == market,
                        )
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing and existing.status in {"pending", "hit", "miss", "cancelled", "no_result"}:
                continue

            odds_val: float | None
            if side == "home":
                odds_val = float(event.odds_1 or 0.0)
            else:
                odds_val = float(event.odds_2 or 0.0)
            if odds_val and odds_val < min_odds:
                # Слишком маленький коэффициент — пропускаем.
                continue

            row = existing or TableTennisForecastV2(
                event_id=event.id,
                channel=channel,
            )
            row.market = market
            row.pick_side = side
            row.forecast_text = text
            row.probability_pct = conf  # 0–100
            row.edge_pct = None
            row.confidence_score = conf
            row.odds_used = odds_val or None
            row.status = "pending"
            row.final_status = None
            row.final_sets_score = None
            row.explanation_summary = f"Pre-match stats: conf {conf:.1f}% (no ML)"

            if not existing:
                session.add(row)
                await session.flush()
            else:
                await session.flush()

            created += 1

        if created:
            await session.commit()
        return created


async def run_early_scan_once(limit: int = 200) -> int:
    """Stage 1: скрининг за 6-12h. Находим потенциальные value-матчи, не публикуем."""
    from app.services.ml_scorer import score_match_for_forecast

    now = _utc_now()
    min_h = 6
    max_h = 12
    window_start = now + timedelta(hours=min_h)
    window_end = now + timedelta(hours=max_h)

    async with async_session_maker() as session:
        events = (
            await session.execute(
                select(TableTennisLineEvent).where(
                    and_(
                        TableTennisLineEvent.status == LINE_EVENT_STATUS_SCHEDULED,
                        TableTennisLineEvent.starts_at > window_start,
                        TableTennisLineEvent.starts_at <= window_end,
                        TableTennisLineEvent.odds_1.is_not(None),
                        TableTennisLineEvent.odds_2.is_not(None),
                    )
                )
                .order_by(TableTennisLineEvent.starts_at.asc())
                .limit(limit)
            )
        ).scalars().all()

        created = 0
        for event in events:
            existing = (
                await session.execute(
                    select(TableTennisForecastEarlyScan).where(
                        TableTennisForecastEarlyScan.event_id == event.id
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if existing:
                continue

            scored_result = score_match_for_forecast(event)
            if scored_result is None:
                continue
            scored, _ = scored_result
            oh, oa = float(event.odds_1 or 1.9), float(event.odds_2 or 1.9)
            ev_h = scored.p_home_match * oh - 1.0 if oh > 0 else 0
            ev_a = scored.p_away_match * oa - 1.0 if oa > 0 else 0
            has_value = (
                (ev_h >= 0.08 and 1.6 <= oh <= 2.6) or (ev_a >= 0.08 and 1.6 <= oa <= 2.6)
            )
            minutes_to_match = int((event.starts_at - now).total_seconds() / 60) if event.starts_at else None
            row = TableTennisForecastEarlyScan(
                event_id=event.id,
                minutes_to_match=minutes_to_match,
                p_match=scored.p_home_match,
                has_value=has_value,
            )
            session.add(row)
            created += 1
        if created:
            await session.commit()
        return created


async def run_result_priority_once() -> int:
    async with async_session_maker() as session:
        return await resolve_forecast_outcomes_once(session, limit=2000)


async def run_kpi_guard_once() -> dict:
    """Adjust selector cutoffs to keep balanced volume and hit-rate."""
    _init_kpi_runtime_defaults()
    now = _utc_now()
    day_ago = now - timedelta(hours=24)
    async with async_session_maker() as session:
        rows = (
            await session.execute(
                select(TableTennisForecastV2).where(
                    and_(
                        TableTennisForecastV2.created_at >= day_ago,
                        TableTennisForecastV2.channel == "paid",
                    )
                )
            )
        ).scalars().all()

    total = len(rows)
    resolved = [r for r in rows if r.status in {"hit", "miss"}]
    hits = sum(1 for r in resolved if r.status == "hit")
    hit_rate = (hits / len(resolved) * 100.0) if resolved else 0.0
    picks_per_day = float(total)

    # Balanced policy around targets (hit-rate + picks/day).
    conf = _kpi_runtime_state["dynamic_min_confidence_pct"]
    edge = _kpi_runtime_state["dynamic_min_edge_pct"]
    target_picks = float(settings.betsapi_table_tennis_v2_target_picks_per_day)
    if target_picks > 0:
        picks_ratio = picks_per_day / target_picks
    else:
        picks_ratio = 1.0
    resolved_count = float(len(resolved))

    # Volume-first correction when we are far below target.
    if picks_ratio < 0.5:
        conf -= 2.0
        edge -= 0.7
    elif picks_ratio < 0.8:
        conf -= 1.0
        edge -= 0.4
    elif picks_ratio > 1.3 and resolved_count >= 30:
        conf += 0.7
        edge += 0.2

    # Accuracy correction only when enough resolved outcomes exist.
    if resolved_count >= 25:
        if hit_rate < settings.betsapi_table_tennis_v2_target_hit_rate:
            conf += 1.2
            edge += 0.5
        elif hit_rate > settings.betsapi_table_tennis_v2_target_hit_rate + 4:
            conf -= 0.6
            edge -= 0.2

    conf = max(
        float(settings.betsapi_table_tennis_v2_min_confidence_floor),
        min(float(settings.betsapi_table_tennis_v2_min_confidence_ceiling), conf),
    )
    edge = max(
        float(settings.betsapi_table_tennis_v2_min_edge_floor),
        min(float(settings.betsapi_table_tennis_v2_min_edge_ceiling), edge),
    )

    _kpi_runtime_state.update(
        {
            "dynamic_min_confidence_pct": round(conf, 2),
            "dynamic_min_edge_pct": round(edge, 2),
            "dynamic_min_odds": round(float(settings.betsapi_table_tennis_min_odds_for_forecast), 2),
            "last_hit_rate": round(hit_rate, 2),
            "last_picks_per_day": round(picks_per_day, 2),
            "last_updated_at": now.timestamp(),
        }
    )
    return dict(_kpi_runtime_state)


async def run_validation_checks_once() -> dict:
    """Quick runtime validation checks for V2 pipeline."""
    now = _utc_now()
    day_ago = now - timedelta(hours=24)
    async with async_session_maker() as session:
        total_recent = int(
            (
                await session.execute(
                    select(func.count(TableTennisForecastV2.id)).where(
                        and_(
                            TableTennisForecastV2.created_at >= day_ago,
                            TableTennisForecastV2.channel == "paid",
                        )
                    )
                )
            ).scalar_one()
            or 0
        )
        stale_pending = int(
            (
                await session.execute(
                    select(func.count(TableTennisForecastV2.id))
                    .join(TableTennisLineEvent, TableTennisLineEvent.id == TableTennisForecastV2.event_id)
                    .where(
                        and_(
                            TableTennisForecastV2.status == "pending",
                            TableTennisLineEvent.status.in_(
                                [LINE_EVENT_STATUS_CANCELLED, "finished"]
                            ),
                        )
                    )
                )
            ).scalar_one()
            or 0
        )
        missing_explanations = int(
            (
                await session.execute(
                    select(func.count(TableTennisForecastV2.id))
                    .outerjoin(
                        TableTennisForecastExplanation,
                        TableTennisForecastExplanation.forecast_v2_id == TableTennisForecastV2.id,
                    )
                    .where(
                        and_(
                            TableTennisForecastV2.created_at >= day_ago,
                            TableTennisForecastExplanation.id.is_(None),
                        )
                    )
                )
            ).scalar_one()
            or 0
        )

    return {
        "recent_forecasts_24h": total_recent,
        "stale_pending": stale_pending,
        "missing_explanations_24h": missing_explanations,
        "kpi_runtime": get_kpi_runtime_state(),
    }


def get_kpi_runtime_state() -> dict:
    return dict(_kpi_runtime_state)


async def early_scan_loop() -> None:
    """Stage 1: скрининг за 6-12h. Раз в 10 мин."""
    while True:
        try:
            cnt = await run_early_scan_once(limit=200)
            if cnt:
                logger.info("Early scan created=%s", cnt)
        except Exception:
            logger.exception("Early scan failed")
        await asyncio.sleep(max(600, getattr(settings, "betsapi_table_tennis_early_scan_interval_sec", 600)))


async def forecast_v2_loop() -> None:
    while True:
        try:
            cnt = await run_forecast_v2_once(limit=settings.betsapi_table_tennis_v2_forecast_batch_size)
            logger.info("V2 forecast loop created/updated=%s", cnt)
        except Exception:
            logger.exception("V2 forecast loop failed")
        await asyncio.sleep(max(10, settings.betsapi_table_tennis_v2_forecast_interval_sec))


async def no_ml_forecast_loop() -> None:
    """Форкастинг канала no_ml по тем же окнам, но без ML."""
    while True:
        try:
            cnt = await run_no_ml_forecast_once(
                limit=settings.betsapi_table_tennis_v2_forecast_batch_size,
                channel="no_ml",
            )
            logger.info("No-ML forecast loop created/updated=%s", cnt)
        except Exception:
            logger.exception("No-ML forecast loop failed")
        await asyncio.sleep(max(30, settings.betsapi_table_tennis_v2_forecast_interval_sec))


async def result_priority_loop() -> None:
    while True:
        try:
            cnt = await run_result_priority_once()
            logger.info("V2 result_priority loop resolved=%s", cnt)
        except Exception:
            logger.exception("V2 result_priority loop failed")
        await asyncio.sleep(max(5, settings.betsapi_table_tennis_v2_result_priority_interval_sec))


async def kpi_guard_loop() -> None:
    while True:
        try:
            state = await run_kpi_guard_once()
            logger.info(
                "V2 KPI guard: min_conf=%.2f min_edge=%.2f hit_rate=%.2f picks/day=%.2f",
                state["dynamic_min_confidence_pct"],
                state["dynamic_min_edge_pct"],
                state["last_hit_rate"],
                state["last_picks_per_day"],
            )
        except Exception:
            logger.exception("V2 KPI guard loop failed")
        await asyncio.sleep(max(15, settings.betsapi_table_tennis_v2_kpi_guard_interval_sec))
