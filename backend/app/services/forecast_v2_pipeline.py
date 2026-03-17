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
from app.services.ml_scorer import score_match_for_forecast, score_match_for_forecast_nn
from app.services.outcome_resolver_v2 import resolve_forecast_outcomes_once
from app.services.pick_selector import select_best_confidence_pick, select_pick
from app.services.table_tennis_analytics import compute_forecast_for_event

logger = logging.getLogger(__name__)

_kpi_runtime_state: dict[str, float] = {
    "dynamic_min_confidence_pct": 58.0,
    "dynamic_min_edge_pct": 0.0,
    "dynamic_min_odds": 1.5,
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
            model_name="tt_ml_clickhouse_v2" if str(getattr(settings, "ml_engine", "v1")).lower() == "v2" else "tt_ml_xgboost",
            model_version="v2.0.0" if str(getattr(settings, "ml_engine", "v1")).lower() == "v2" else "v1.0.0",
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
    """Создаёт ML-прогнозы для матчей, до начала которых 1 час и менее."""
    _init_kpi_runtime_defaults()
    model_run_id = await _ensure_active_model_run()
    now = _utc_now()
    delay_minutes = max(0, settings.betsapi_table_tennis_forecast_delay_minutes)
    earliest_created_at = now - timedelta(minutes=delay_minutes)
    # Окно ML: прогнозы только для матчей до начала которых 1 час и менее.
    window_min = max(
        1,
        int(getattr(settings, "betsapi_table_tennis_forecast_window_min_minutes_before", 1)),
    )
    window_max = max(
        1,
        int(getattr(settings, "betsapi_table_tennis_forecast_ml_max_minutes_before", 60)),
    )
    min_min = window_min
    max_min = min(window_max, 300)  # не более 5 ч
    window_start = now + timedelta(minutes=min_min)
    window_end = now + timedelta(minutes=max_min)

    async with async_session_maker() as session:
        events = (
            await session.execute(
                select(TableTennisLineEvent).where(
                    and_(
                        TableTennisLineEvent.status == LINE_EVENT_STATUS_SCHEDULED,
                        TableTennisLineEvent.starts_at > now,
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
        exclude_names = (getattr(settings, "betsapi_table_tennis_v2_exclude_league_names", "") or "").strip()
        exclude_parts = [x.strip() for x in exclude_names.split(",") if x.strip()] if exclude_names else []

        created = 0
        for event in events:
            if exclude_parts:
                league_name = (getattr(event, "league_name", None) or "").strip()
                if any(part in league_name for part in exclude_parts):
                    continue
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
            # One-shot policy: once ML forecast is created for event+channel, never recalculate it.
            # This prevents drift between prematch signal and later live/finish states.
            if existing:
                continue

            scored_result = score_match_for_forecast(event)
            if scored_result is None:
                continue
            scored, use_ml = scored_result
            effective_min_odds = max(
                float(_kpi_runtime_state["dynamic_min_odds"]),
                float(getattr(settings, "betsapi_table_tennis_v2_preferred_min_odds", 1.75)),
            )

            conf_floor = float(getattr(settings, "betsapi_table_tennis_v2_confidence_filter_min_pct", 0) or 0)
            effective_min_conf = max(float(_kpi_runtime_state["dynamic_min_confidence_pct"]), conf_floor)
            selected = select_pick(
                scored=scored,
                odds_home=float(event.odds_1 or 0.0),
                odds_away=float(event.odds_2 or 0.0),
                min_odds=effective_min_odds,
                min_confidence_pct=effective_min_conf,
                min_edge_pct=float(_kpi_runtime_state["dynamic_min_edge_pct"]),
            )
            # Fallback profile: when model is conservative around p~0.5, strict confidence gates can
            # block all picks despite positive edge. Keep stream alive with softer bounds.
            if not selected and bool(getattr(settings, "betsapi_table_tennis_v2_allow_soft_fallback", False)):
                soft_conf = min(50.0, float(_kpi_runtime_state["dynamic_min_confidence_pct"]))
                selected = select_pick(
                    scored=scored,
                    odds_home=float(event.odds_1 or 0.0),
                    odds_away=float(event.odds_2 or 0.0),
                    min_odds=effective_min_odds,
                    min_confidence_pct=max(conf_floor, soft_conf),
                    min_edge_pct=max(
                        0.8,
                        float(_kpi_runtime_state["dynamic_min_edge_pct"]) * 0.4,
                    ),
                )
            allow_hard_fallback = bool(
                getattr(settings, "betsapi_table_tennis_v2_allow_hard_confidence_fallback", False)
            ) and not bool(
                getattr(settings, "betsapi_table_tennis_v2_prioritize_quality_over_volume", True)
            )
            if not selected and allow_hard_fallback:
                # Hard fallback: лучший по уверенности; min_odds ниже (1.5), чтобы чаще был хотя бы один прогноз.
                fallback_min_odds = min(
                    effective_min_odds,
                    float(getattr(settings, "betsapi_table_tennis_min_odds_for_forecast", 1.5)),
                )
                selected = select_best_confidence_pick(
                    scored=scored,
                    odds_home=float(event.odds_1 or 0.0),
                    odds_away=float(event.odds_2 or 0.0),
                    min_odds=fallback_min_odds,
                )
                if selected:
                    logger.debug("ML v2 event %s: выбран пик по hard fallback (confidence=%.1f%%)", event.id, selected.probability_pct)
            if not selected:
                logger.debug(
                    "ML v2 event %s: пик не выбран (min_conf=%.1f%%, min_edge=%.2f%%, p_match=%.3f p_set1=%.3f)",
                    event.id, effective_min_conf, _kpi_runtime_state["dynamic_min_edge_pct"],
                    scored.p_home_match, scored.p_home_set1,
                )
                continue

            # Правило для ML: если коэффициент на выбранную сторону слишком низкий (< threshold),
            # переворачиваем сторону и текст (П1↔П2), чтобы избегать перекоса в сторону суперфаворита.
            invert_low_odds_threshold = float(
                getattr(settings, "betsapi_table_tennis_v2_invert_low_odds_threshold", 0.0) or 0.0
            )
            if invert_low_odds_threshold > 1e-9 and selected.odds_used and selected.odds_used < invert_low_odds_threshold:
                old_odds_used = float(selected.odds_used or 0.0)
                original_side = selected.side
                selected.side = "away" if selected.side == "home" else "home"
                # После инверта пересчитываем всё под новую сторону (иначе conf/edge становятся неконсистентными).
                selected.odds_used = float(event.odds_1 or 0.0) if selected.side == "home" else float(event.odds_2 or 0.0)
                if selected.market == "match":
                    p_new = float(scored.p_home_match if selected.side == "home" else scored.p_away_match)
                    label = "П1 победа в матче" if selected.side == "home" else "П2 победа в матче"
                elif selected.market == "set1":
                    p_new = float(scored.p_home_set1 if selected.side == "home" else scored.p_away_set1)
                    label = "П1 выиграет 1-й сет" if selected.side == "home" else "П2 выиграет 1-й сет"
                else:
                    p_new = float(scored.p_home_set2 if selected.side == "home" else scored.p_away_set2)
                    label = "П1 выиграет 2-й сет" if selected.side == "home" else "П2 выиграет 2-й сет"
                implied = (1.0 / selected.odds_used) if selected.odds_used > 1e-9 else 0.0
                selected.probability_pct = round(p_new * 100.0, 2)
                selected.edge_pct = round((p_new - implied) * 100.0, 2)
                selected.confidence_score = round(
                    selected.probability_pct * (0.4 + 0.6 * float(scored.quality_score)),
                    2,
                )
                selected.forecast_text = f"{label} ({round(selected.probability_pct, 1)}%)"
                logger.debug(
                    "ML v2 event %s: invert by low odds (%.2f < %.2f) side %s->%s, new_p=%.2f edge=%.2f",
                    event.id,
                    old_odds_used,
                    invert_low_odds_threshold,
                    original_side,
                    selected.side,
                    selected.probability_pct,
                    selected.edge_pct,
                )

            # Только уверенные: не публикуем прогноз, если модель не уверена в результате (матч или 1-й сет).
            min_publish = float(getattr(settings, "betsapi_table_tennis_v2_min_confidence_to_publish", 0) or 0)
            if min_publish > 0 and selected.probability_pct < min_publish:
                logger.debug(
                    "ML v2 event %s: пропуск (confidence %.1f%% < min_to_publish %.1f%%)",
                    event.id, selected.probability_pct, min_publish,
                )
                continue

            row = TableTennisForecastV2(
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
            if min_publish > 0 and selected.probability_pct < 55 and selected.probability_pct >= 50:
                logger.debug("ML v2 event %s: публикуем при confidence %.1f%% (min_publish=%.1f)", event.id, selected.probability_pct, min_publish)
            session.add(row)
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
        if not created and events:
            logger.info(
                "ML v2 forecast: 0 создано при %s событиях в окне (проверь min_confidence_to_publish, allow_hard_fallback, пороги select_pick)",
                len(events),
            )
        elif not created:
            logger.debug("ML v2 forecast: 0 событий в окне [%s–%s] мин до старта", min_min, max_min)
        return created


async def run_no_ml_forecast_once(limit: int = 400, channel: str = "no_ml") -> int:
    """Создаёт прематч‑прогнозы «без ML» на основе статистики игроков.

    Логика максимально повторяет старый backend_prematch: считаем по истории матчей
    и сетов, формируем текст вида «П1 победа в матче ...» или «П2 выиграет 1-й сет ...».
    """
    now = _utc_now()
    model_run_id = await _ensure_active_model_run()
    # No-ML: окно до 2 часов до старта (прогнозы за 2 ч и менее).
    min_min = max(0, int(getattr(settings, "betsapi_table_tennis_no_ml_forecast_min_minutes_ahead", 1)))
    max_hours = max(1, int(settings.betsapi_table_tennis_no_ml_forecast_max_hours_ahead))
    window_start = now + timedelta(minutes=min_min)
    window_end = now + timedelta(hours=max_hours)

    min_odds = float(getattr(settings, "betsapi_table_tennis_min_odds_for_forecast", 1.5))

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

        # Лиги, для которых no_ML прогноз не выдаём (исключаем из расчёта).
        exclude_names = (getattr(settings, "betsapi_table_tennis_no_ml_exclude_league_names", "") or "").strip()
        exclude_parts = [x.strip() for x in exclude_names.split(",") if x.strip()] if exclude_names else []

        created = 0
        skip_no_text = 0
        skip_exclude_league = 0
        skip_existing = 0
        skip_low_odds = 0
        skip_bad_format = 0
        for event in events:
            if exclude_parts:
                league_name = (getattr(event, "league_name", None) or "").strip()
                if any(part in league_name for part in exclude_parts):
                    skip_exclude_league += 1
                    continue
            # Прогноз уже есть для этого рынка и канала — не пересчитываем.
            # Рынок определяем позже, поэтому сначала считаем текст.
            text, conf = await compute_forecast_for_event(session, event)
            if not text:
                skip_no_text += 1
                continue

            t = text.lower()
            if "п1" in t:
                side = "home"
            elif "п2" in t:
                side = "away"
            else:
                skip_bad_format += 1
                continue

            if "1-й сет" in t:
                market = "set1"
            elif "2-й сет" in t:
                market = "set2"
            else:
                market = "match"

            # Для отдельных лиг инвертируем выбор: рассчитали П1 — выдаём П2 и наоборот.
            invert_names = (getattr(settings, "betsapi_table_tennis_no_ml_invert_pick_league_names", "") or "").strip()
            if invert_names:
                league_name = (getattr(event, "league_name", None) or "").strip()
                for name_part in (x.strip() for x in invert_names.split(",") if x.strip()):
                    if name_part and name_part in league_name:
                        side = "away" if side == "home" else "home"
                        # Меняем П1/П2 в тексте (сохраняем регистр и форму).
                        if "п1" in t:
                            text = text.replace("П1", "П2").replace("п1", "п2")
                        else:
                            text = text.replace("П2", "П1").replace("п2", "п1")
                        t = text.lower()
                        break

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
                skip_existing += 1
                continue

            odds_val: float | None
            if side == "home":
                odds_val = float(event.odds_1 or 0.0)
            else:
                odds_val = float(event.odds_2 or 0.0)
            if odds_val and odds_val < min_odds:
                skip_low_odds += 1
                continue

            row = existing or TableTennisForecastV2(
                event_id=event.id,
                channel=channel,
                model_run_id=model_run_id,
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
        if not created and events:
            logger.info(
                "No-ML forecast: 0 создано при %s событиях в окне | нет_текста=%s (нет стат/низкая уверенность) excluded=%s existing=%s low_odds=%s bad_format=%s",
                len(events),
                skip_no_text,
                skip_exclude_league,
                skip_existing,
                skip_low_odds,
                skip_bad_format,
            )
        elif not created:
            logger.debug("No-ML forecast: 0 событий в окне %s мин – %s ч до старта", min_min, max_hours)
        return created


async def run_forecast_nn_once(limit: int = 400, channel: str = "nn") -> int:
    """Creates NN forecasts for upcoming scheduled matches."""
    _init_kpi_runtime_defaults()
    model_run_id = await _ensure_active_model_run()
    now = _utc_now()
    delay_minutes = max(0, settings.betsapi_table_tennis_forecast_delay_minutes)
    earliest_created_at = now - timedelta(minutes=delay_minutes)
    window_min = max(1, int(getattr(settings, "betsapi_table_tennis_forecast_window_min_minutes_before", 1)))
    window_max = max(1, int(getattr(settings, "betsapi_table_tennis_forecast_ml_max_minutes_before", 60)))
    window_start = now + timedelta(minutes=window_min)
    window_end = now + timedelta(minutes=min(window_max, 300))

    async with async_session_maker() as session:
        events = (
            await session.execute(
                select(TableTennisLineEvent).where(
                    and_(
                        TableTennisLineEvent.status == LINE_EVENT_STATUS_SCHEDULED,
                        TableTennisLineEvent.starts_at > now,
                        TableTennisLineEvent.starts_at >= window_start,
                        TableTennisLineEvent.starts_at <= window_end,
                        TableTennisLineEvent.created_at <= earliest_created_at,
                        TableTennisLineEvent.odds_1.is_not(None),
                        TableTennisLineEvent.odds_2.is_not(None),
                    )
                )
                # NN: приоритет свежим событиям, затем ближайшим к старту.
                .order_by(TableTennisLineEvent.created_at.desc(), TableTennisLineEvent.starts_at.asc())
                .limit(limit)
            )
        ).scalars().all()

        created = 0
        min_publish = float(getattr(settings, "betsapi_table_tennis_nn_min_confidence_to_publish", 62.0) or 62.0)
        min_match_conf = float(getattr(settings, "betsapi_table_tennis_nn_min_match_confidence_pct", 66.0) or 66.0)
        min_set1_conf = float(getattr(settings, "betsapi_table_tennis_nn_min_set1_confidence_pct", 67.0) or 67.0)
        allow_nn_hard_fallback = bool(
            getattr(settings, "betsapi_table_tennis_nn_allow_hard_confidence_fallback", False)
        )
        conf_floor = float(
            getattr(
                settings,
                "betsapi_table_tennis_nn_confidence_filter_min_pct",
                getattr(settings, "betsapi_table_tennis_v2_confidence_filter_min_pct", 0),
            )
            or 0
        )
        effective_min_conf = max(float(_kpi_runtime_state["dynamic_min_confidence_pct"]), conf_floor)
        # Для NN держим строгий порог публикации: не ниже min_publish и не ниже базового NN confidence-гейта.
        nn_pick_min_conf = max(min_publish, min(min_match_conf, min_set1_conf), effective_min_conf)
        effective_min_odds = max(
            float(_kpi_runtime_state["dynamic_min_odds"]),
            float(
                getattr(
                    settings,
                    "betsapi_table_tennis_nn_preferred_min_odds",
                    getattr(settings, "betsapi_table_tennis_v2_preferred_min_odds", 1.75),
                )
            ),
        )

        skip_low_nn_conf = 0
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
            if existing:
                continue

            scored_result = score_match_for_forecast_nn(event)
            if scored_result is None:
                continue
            scored, _ = scored_result
            nn_match_conf = max(scored.p_home_match, scored.p_away_match) * 100.0
            nn_set1_conf = max(scored.p_home_set1, scored.p_away_set1) * 100.0
            # NN публикуем только если уверена в матче или в 1-м сете.
            if nn_match_conf < min_match_conf and nn_set1_conf < min_set1_conf:
                skip_low_nn_conf += 1
                continue
            # NN: выбираем один рынок с максимальной уверенностью между match и set1.
            selected = select_best_confidence_pick(
                scored=scored,
                odds_home=float(event.odds_1 or 0.0),
                odds_away=float(event.odds_2 or 0.0),
                min_odds=effective_min_odds,
            )
            if not selected and allow_nn_hard_fallback:
                selected = select_best_confidence_pick(
                    scored=scored,
                    odds_home=float(event.odds_1 or 0.0),
                    odds_away=float(event.odds_2 or 0.0),
                    min_odds=min(effective_min_odds, float(getattr(settings, "betsapi_table_tennis_min_odds_for_forecast", 1.5))),
                )
            if not selected or selected.probability_pct < nn_pick_min_conf:
                skip_low_nn_conf += 1
                continue
            # NN: рынок должен проходить именно свой confidence-гейт, а не «любой из match/set1».
            if selected.market == "match" and nn_match_conf < min_match_conf:
                skip_low_nn_conf += 1
                continue
            if selected.market == "set1" and nn_set1_conf < min_set1_conf:
                skip_low_nn_conf += 1
                continue
            if selected.market not in {"match", "set1"}:
                skip_low_nn_conf += 1
                continue

            if selected.market == "match":
                chosen_market = "match"
                chosen_conf = nn_match_conf
                alt_market = "set1"
                alt_conf = nn_set1_conf
            else:
                chosen_market = "set1"
                chosen_conf = nn_set1_conf
                alt_market = "match"
                alt_conf = nn_match_conf

            row = TableTennisForecastV2(
                event_id=event.id,
                channel=channel,
                model_run_id=model_run_id,
                market=selected.market,
                pick_side=selected.side,
                forecast_text=selected.forecast_text,
                probability_pct=selected.probability_pct,
                edge_pct=selected.edge_pct,
                confidence_score=selected.confidence_score,
                odds_used=selected.odds_used,
                status="pending",
                final_status=None,
                final_sets_score=None,
                explanation_summary=(
                    f"Tier {selected.quality_tier} [NN]: edge {selected.edge_pct:.2f}%, "
                    f"conf {selected.confidence_score:.2f}% | match={nn_match_conf:.1f}% set1={nn_set1_conf:.1f}% "
                    f"| picked {chosen_market} ({chosen_conf:.1f}%) over {alt_market} ({alt_conf:.1f}%)"
                ),
            )
            session.add(row)
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
        elif events:
            logger.info(
                "NN forecast: 0 created for %s events (strict confidence gate). "
                "min_match=%.1f min_set1=%.1f min_publish=%.1f pick_min=%.1f skipped=%s",
                len(events),
                min_match_conf,
                min_set1_conf,
                min_publish,
                nn_pick_min_conf,
                skip_low_nn_conf,
            )
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
                (ev_h >= 0.08 and 1.5 <= oh <= 3.0) or (ev_a >= 0.08 and 1.5 <= oa <= 3.0)
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

    # Volume-first correction can reduce quality. Keep optional for conservative mode.
    if not bool(getattr(settings, "betsapi_table_tennis_v2_prioritize_quality_over_volume", True)):
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
        await asyncio.sleep(max(1, settings.betsapi_table_tennis_v2_forecast_interval_sec))


async def no_ml_forecast_loop() -> None:
    """Форкастинг канала no_ml по тем же окнам, но без ML."""
    interval_no_ml = max(30, getattr(settings, "betsapi_table_tennis_no_ml_forecast_interval_sec", 180))
    while True:
        try:
            cnt = await run_no_ml_forecast_once(
                limit=settings.betsapi_table_tennis_v2_forecast_batch_size,
                channel="no_ml",
            )
            logger.info("No-ML forecast loop created/updated=%s", cnt)
        except Exception:
            logger.exception("No-ML forecast loop failed")
        await asyncio.sleep(interval_no_ml)


async def nn_forecast_loop() -> None:
    """NN forecast loop (third analytics channel)."""
    interval_nn = max(30, int(getattr(settings, "betsapi_table_tennis_nn_forecast_interval_sec", 60)))
    while True:
        try:
            cnt = await run_forecast_nn_once(
                limit=settings.betsapi_table_tennis_v2_forecast_batch_size,
                channel="nn",
            )
            logger.info("NN forecast loop created/updated=%s", cnt)
        except Exception:
            logger.exception("NN forecast loop failed")
        await asyncio.sleep(interval_nn)


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
