"""Forecast V2 loops and orchestration."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, func, or_, select

from app.config import settings
from app.db.session import async_session_maker
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
from app.services.feature_builder import (
    build_match_feature_snapshot,
    rebuild_player_daily_features_once,
    upsert_match_feature,
)
from app.services.model_scorer_v2 import score_match_features
from app.services.outcome_resolver_v2 import resolve_forecast_outcomes_once
from app.services.pick_selector import select_pick

logger = logging.getLogger(__name__)

_kpi_runtime_state: dict[str, float] = {
    "dynamic_min_confidence_pct": 74.0,
    "dynamic_min_edge_pct": 3.0,
    "dynamic_min_odds": 1.4,
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
            model_name="tt_local_blended_v2",
            model_version="v2.0.0",
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


async def rebuild_features_once() -> int:
    async with async_session_maker() as session:
        return await rebuild_player_daily_features_once(session)


async def run_forecast_v2_once(limit: int = 400, channel: str = "paid") -> int:
    _init_kpi_runtime_defaults()
    model_run_id = await _ensure_active_model_run()
    now = _utc_now()
    delay_minutes = max(0, settings.betsapi_table_tennis_forecast_delay_minutes)
    earliest_created_at = now - timedelta(minutes=delay_minutes)

    async with async_session_maker() as session:
        events = (
            await session.execute(
                select(TableTennisLineEvent).where(
                    and_(
                        TableTennisLineEvent.status == LINE_EVENT_STATUS_SCHEDULED,
                        TableTennisLineEvent.starts_at > now,
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
            if existing and existing.status in {"pending", "hit", "miss"}:
                continue

            snapshot = await build_match_feature_snapshot(session, event)
            await upsert_match_feature(session, snapshot, model_run_id=model_run_id)
            scored = score_match_features(snapshot.features)

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
            row.explanation_summary = (
                f"Tier {selected.quality_tier}: edge {selected.edge_pct:.2f}%, conf {selected.confidence_score:.2f}%"
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
                select(TableTennisForecastV2).where(TableTennisForecastV2.created_at >= day_ago)
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
                        TableTennisForecastV2.created_at >= day_ago
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


async def features_loop() -> None:
    while True:
        try:
            cnt = await rebuild_features_once()
            logger.info("V2 features_loop rebuilt rows=%s", cnt)
        except Exception:
            logger.exception("V2 features_loop failed")
        await asyncio.sleep(max(30, settings.betsapi_table_tennis_v2_features_interval_sec))


async def forecast_v2_loop() -> None:
    while True:
        try:
            cnt = await run_forecast_v2_once(limit=settings.betsapi_table_tennis_v2_forecast_batch_size)
            logger.info("V2 forecast loop created/updated=%s", cnt)
        except Exception:
            logger.exception("V2 forecast loop failed")
        await asyncio.sleep(max(10, settings.betsapi_table_tennis_v2_forecast_interval_sec))


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
