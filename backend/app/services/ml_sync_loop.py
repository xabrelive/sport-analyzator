"""ML sync loop: синхронизация main→ML, backfill, дообучение. ML берёт все данные только из основной БД."""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from app.config import settings
from app.db.session import async_session_maker
from app.models.app_setting import AppSetting
from app.ml.pipeline import (
    sync_finished_to_ml_once,
    sync_full_main_to_ml,
    sync_leagues_to_ml,
    sync_players_to_ml,
    sync_missing_finished_to_ml_once,
    backfill_features_incremental_once,
    backfill_duration_from_main_incremental_once,
    backfill_odds_from_main_incremental_once,
    check_suspicious_matches_once,
)
from app.ml.league_performance import update_league_performance_once
from app.ml.player_stats import (
    backfill_player_daily_stats_once,
    backfill_player_style_once,
    backfill_player_elo_history_once,
)
from app.ml.db import get_ml_session
from app.ml.model_trainer import retrain_models_if_needed
from app.services.ml_queue import enqueue

logger = logging.getLogger(__name__)

# Ключ: когда последний раз поставили переобучение в очередь (чтобы не ставить повторно пока не прошло retrain_interval)
_RETRAIN_REQUESTED_TS_KEY = "ml_retrain_requested_at_ts"

_SYNC_CURSOR_KEY = "ml_sync_finished_cursor_v1"
_FORCE_FULL_KEY = "ml_sync_force_full_once"
_FEATURES_CURSOR_KEY = "ml_features_backfill_cursor_v1"
_ODDS_CURSOR_KEY = "ml_odds_backfill_cursor_v1"
_DURATION_CURSOR_KEY = "ml_duration_backfill_cursor_v1"
_SYNC_LOOKBACK_SEC = 3 * 60 * 60
_V2_FEATURES_REFRESH_CURSOR_KEY = "ml_v2_features_refresh_cursor"
_V2_FEATURES_REFRESH_APPLIED_SIG_KEY = "ml_v2_features_applied_signature"


def _ml_matches_count() -> int:
    try:
        s = get_ml_session()
        r = s.execute(text("SELECT COUNT(*) FROM matches")).scalar_one()
        s.close()
        return int(r or 0)
    except Exception:
        return 0


async def _get_app_setting(key: str) -> str | None:
    async with async_session_maker() as session:
        row = (
            await session.execute(select(AppSetting).where(AppSetting.key == key))
        ).scalars().one_or_none()
        return (row.value or "").strip() if row and row.value else None


async def _set_app_setting(key: str, value: str) -> None:
    async with async_session_maker() as session:
        row = (
            await session.execute(select(AppSetting).where(AppSetting.key == key))
        ).scalars().one_or_none()
        if row:
            row.value = value
        else:
            session.add(AppSetting(key=key, value=value))
        await session.commit()


async def _load_sync_cursor() -> tuple[datetime | None, int]:
    raw = await _get_app_setting(_SYNC_CURSOR_KEY)
    if not raw:
        return None, 0
    try:
        obj = json.loads(raw)
        ts = int(obj.get("last_starts_at_ts") or 0)
        event_id = int(obj.get("last_event_id") or 0)
        dt = datetime.fromtimestamp(ts, tz=timezone.utc) if ts > 0 else None
        return dt, event_id
    except Exception:
        return None, 0


async def _save_sync_cursor(last_starts_at_ts: int, last_event_id: int) -> None:
    if int(last_starts_at_ts or 0) <= 0:
        return
    payload = json.dumps(
        {
            "last_starts_at_ts": int(last_starts_at_ts),
            "last_event_id": int(last_event_id or 0),
            "saved_at_ts": int(datetime.now(timezone.utc).timestamp()),
        }
    )
    await _set_app_setting(_SYNC_CURSOR_KEY, payload)


async def _consume_force_full_flag() -> bool:
    raw = (await _get_app_setting(_FORCE_FULL_KEY) or "").strip().lower()
    enabled = raw in {"1", "true", "yes", "on"}
    if enabled:
        await _set_app_setting(_FORCE_FULL_KEY, "0")
    return enabled


async def _load_int_setting(key: str, default: int = 0) -> int:
    raw = await _get_app_setting(key)
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _parse_refresh_cursor(raw: str | None) -> tuple[datetime | None, str]:
    text_raw = (raw or "").strip()
    if not text_raw:
        return None, ""
    if "|" not in text_raw:
        try:
            return datetime.fromisoformat(text_raw), ""
        except Exception:
            return None, ""
    dt_raw, mid = text_raw.split("|", 1)
    try:
        return datetime.fromisoformat(dt_raw), str(mid or "")
    except Exception:
        return None, ""


async def ml_sync_loop() -> None:
    """Автозаполнение всех ML таблиц каждые N сек (по умолчанию 600 = 10 мин).

    Для ML_ENGINE=v2 каждый цикл автоматически:
    - sync_finished_to_ch_once → ml.matches, ml.match_sets, ml.player_match_stats,
      recompute_elo_from_matches() → ml.player_elo_history,
      _refresh_player_daily_stats → ml.player_daily_stats;
    - sync_missing_finished_to_ch_once → догрузка пропущенных матчей;
    - sync_player_daily_stats_to_ch_once → backfill ml.player_daily_stats;
    - rebuild_features_to_ch(incremental) → новые строки ml.match_features;
    - rebuild_features_to_ch(missing) → исторические пропуски ml.match_features;
    - rebuild_features_to_ch(refresh) → пересчёт при изменении схемы (новые колонки).

    Интервал задаётся ML_SYNC_INTERVAL_SEC (по умолчанию 600)."""
    interval = max(300, settings.ml_sync_interval_sec)  # мин. 5 мин, по умолчанию 600 (10 мин)
    logger.info(
        "ML sync loop: автодогрузка main→ML каждые %s сек (матчи, кф, фичи, статистика)",
        interval,
    )
    min_new_for_retrain = max(50, settings.ml_retrain_min_new_matches)
    retrain_interval_sec = max(600, int(getattr(settings, "ml_retrain_interval_sec", 1800) or 1800))
    days_back_raw = getattr(settings, "ml_sync_days_back", 3650)
    days_back: int | None = 0 if days_back_raw == 0 else max(365, days_back_raw)
    batch_size = max(500, getattr(settings, "ml_sync_batch_size", 3000))

    while True:
        dur_updated = odds_updated = features_added = 0
        daily_stats = style_count = elo_hist = leagues_updated = 0
        try:
            if str(getattr(settings, "ml_engine", "v1")).lower() == "v2":
                from app.ml_v2.sync import (
                    sync_finished_to_ch_once,
                    sync_missing_finished_to_ch_once,
                    sync_player_daily_stats_to_ch_once,
                    backfill_match_sets_from_main,
                )
                from app.ml_v2.features import rebuild_features_to_ch, feature_schema_signature

                sync_res = await sync_finished_to_ch_once(limit=max(1000, batch_size))
                missing_res = await sync_missing_finished_to_ch_once(limit=max(500, min(5000, batch_size // 2)))
                # Дозаполнение ml.match_sets для матчей из ml.matches без сетов (разрыв по сетовой детализации)
                sets_backfill = await backfill_match_sets_from_main(limit=2000)
                if (sets_backfill.get("filled") or 0) > 0 or (sets_backfill.get("remaining") or 0) > 0:
                    logger.info(
                        "ML v2 match_sets backfill: filled=%s sets_inserted=%s remaining=%s",
                        sets_backfill.get("filled"),
                        sets_backfill.get("sets_inserted"),
                        sets_backfill.get("remaining"),
                    )
                pds_limit = max(1000, int(getattr(settings, "ml_v2_player_daily_backfill_limit", 50000) or 50000))
                pds_res = await asyncio.to_thread(sync_player_daily_stats_to_ch_once, pds_limit)
                feat_res = await asyncio.to_thread(rebuild_features_to_ch, mode="incremental")
                # Aggressive historical catch-up: run several missing passes per cycle.
                missing_passes = max(
                    1,
                    int(getattr(settings, "ml_v2_missing_backfill_passes_per_cycle", 4) or 4),
                )
                missing_limit = max(
                    1000,
                    int(getattr(settings, "ml_v2_missing_backfill_limit", 25000) or 25000),
                )
                missing_added_total = 0
                missing_left = 0
                for _ in range(missing_passes):
                    miss_res = await asyncio.to_thread(
                        rebuild_features_to_ch,
                        mode="missing",
                        limit=missing_limit,
                    )
                    added_now = int((miss_res or {}).get("features_added", 0) or 0)
                    missing_added_total += added_now
                    missing_left = int((miss_res or {}).get("remaining_missing", 0) or 0)
                    if added_now <= 0 or missing_left <= 0:
                        break
                # Auto-refresh for schema upgrades: rewrites historical feature rows in chunks.
                current_sig = feature_schema_signature()
                applied_sig = (await _get_app_setting(_V2_FEATURES_REFRESH_APPLIED_SIG_KEY) or "").strip()
                refresh_added = 0
                refresh_done = False
                if applied_sig != current_sig:
                    cursor_raw = await _get_app_setting(_V2_FEATURES_REFRESH_CURSOR_KEY)
                    cursor_dt, cursor_mid = _parse_refresh_cursor(cursor_raw)
                    refresh_limit = max(
                        1000,
                        int(getattr(settings, "ml_v2_refresh_backfill_limit", 20000) or 20000),
                    )
                    ref_res = await asyncio.to_thread(
                        rebuild_features_to_ch,
                        mode="refresh",
                        limit=refresh_limit,
                        cursor_start_time=cursor_dt,
                        cursor_match_id=cursor_mid,
                    )
                    refresh_added = int((ref_res or {}).get("features_added", 0) or 0)
                    refresh_done = bool((ref_res or {}).get("refresh_done", False))
                    if refresh_done:
                        await _set_app_setting(_V2_FEATURES_REFRESH_APPLIED_SIG_KEY, current_sig)
                        await _set_app_setting(_V2_FEATURES_REFRESH_CURSOR_KEY, "")
                    else:
                        next_ts = str((ref_res or {}).get("refresh_next_cursor_start_time", "") or "")
                        next_mid = str((ref_res or {}).get("refresh_next_cursor_match_id", "") or "")
                        if next_ts:
                            await _set_app_setting(_V2_FEATURES_REFRESH_CURSOR_KEY, f"{next_ts}|{next_mid}")
                else:
                    await _set_app_setting(_V2_FEATURES_REFRESH_CURSOR_KEY, "")
                now_ts = int(datetime.now(timezone.utc).timestamp())
                last_retrain_ts = await _load_int_setting("ml_v2_last_retrain_at_ts", default=0)
                synced_now = int((sync_res or {}).get("synced", 0) or 0) + int((missing_res or {}).get("synced", 0) or 0)
                features_now = (
                    int((feat_res or {}).get("features_added", 0) or 0)
                    + int(missing_added_total)
                    + int(refresh_added)
                )
                due_by_time = last_retrain_ts == 0 or (now_ts - last_retrain_ts) >= retrain_interval_sec
                due_by_volume = synced_now >= min_new_for_retrain or features_now >= min_new_for_retrain

                queued_retrain = False
                if due_by_time or due_by_volume:
                    if enqueue("retrain", {"min_rows": 1000}):
                        queued_retrain = True
                        await _set_app_setting("ml_v2_last_retrain_requested_at_ts", str(now_ts))
                    else:
                        logger.warning("ML v2 retrain enqueue failed")

                logger.info(
                    "ML v2 sync loop: synced=%s missing=%s daily_stats=%s features=%s missing_features_left=%s refresh_added=%s refresh_done=%s retrain_queued=%s due_time=%s due_volume=%s",
                    synced_now,
                    int((missing_res or {}).get("synced", 0) or 0),
                    int((pds_res or {}).get("updated", 0) or 0),
                    features_now,
                    int(missing_left),
                    int(refresh_added),
                    bool(refresh_done),
                    bool(queued_retrain),
                    bool(due_by_time),
                    bool(due_by_volume),
                )
                await _set_app_setting("ml_v2_last_sync_at_ts", str(int(datetime.now(timezone.utc).timestamp())))
                await asyncio.sleep(interval)
                continue

            total_synced = 0
            force_full_once = await _consume_force_full_flag()
            cursor_dt, cursor_event_id = await _load_sync_cursor()
            features_cursor = await _load_int_setting(_FEATURES_CURSOR_KEY, default=0)
            odds_cursor = await _load_int_setting(_ODDS_CURSOR_KEY, default=0)
            duration_cursor = await _load_int_setting(_DURATION_CURSOR_KEY, default=0)
            need_full_sync = (
                force_full_once
                or _ml_matches_count() < 100
                or cursor_dt is None
            )

            # Синхронизация лиг, игроков: все текущие + новые при появлении (реальное время)
            leagues_res = await sync_leagues_to_ml()
            if leagues_res.get("added", 0) > 0:
                logger.info("ML leagues sync: added=%s, total=%s", leagues_res.get("added"), leagues_res.get("total"))
            players_res = await sync_players_to_ml()
            if players_res.get("added", 0) > 0:
                logger.info("ML players sync: added=%s, total=%s", players_res.get("added"), players_res.get("total"))

            if need_full_sync:
                # ML берёт все данные только из основной БД. Загрузка архива в main — задача tt_workers/backend.
                logger.info("ML: полная синхронизация из main (days_back=%s, batch=%s)...", days_back, batch_size)
                res = await sync_full_main_to_ml(batch_size=batch_size, days_back=days_back)
                total_synced = res.get("synced", 0)
                await _save_sync_cursor(
                    int(res.get("last_starts_at_ts", 0) or 0),
                    int(res.get("last_event_id", 0) or 0),
                )
                if total_synced > 0:
                    logger.info("ML full sync: total synced=%s", total_synced)
            else:
                cursor_ts = int(cursor_dt.timestamp()) if cursor_dt else 0
                query_cursor_dt = cursor_dt - timedelta(seconds=_SYNC_LOOKBACK_SEC) if cursor_dt else None
                res = await sync_finished_to_ml_once(
                    limit=batch_size,
                    days_back=0,
                    after_starts_at=query_cursor_dt,
                    after_event_id=cursor_event_id,
                )
                total_synced = res.get("synced", 0)
                if int(res.get("fetched", 0) or 0) > 0:
                    new_cursor_ts = int(res.get("last_starts_at_ts", 0) or 0)
                    new_cursor_event_id = int(res.get("last_event_id", 0) or 0)
                    # При lookback-запросах не даем курсору откатываться назад.
                    if (
                        new_cursor_ts > cursor_ts
                        or (
                            new_cursor_ts == cursor_ts
                            and new_cursor_event_id > int(cursor_event_id or 0)
                        )
                    ):
                        await _save_sync_cursor(new_cursor_ts, new_cursor_event_id)
                if total_synced > 0:
                    logger.info("ML sync: synced=%s skipped=%s", total_synced, res.get("skipped"))
            # Каждый цикл догружаем матчи, которые есть в main, но отсутствуют в ML (например после догрузки результатов)
            try:
                missing_res = await sync_missing_finished_to_ml_once(limit=10_000)
                if missing_res.get("synced", 0) > 0:
                    total_synced += missing_res["synced"]
                    logger.info("ML sync missing: +%s", missing_res["synced"])
            except Exception as e:
                logger.warning("ML sync_missing_finished failed (main sync already done): %s", e)
            # Метки обновляем всегда после основной синхронизации, чтобы при падении backfill цикл не казался «остановившимся»
            await _set_app_setting("ml_last_sync_at_ts", str(int(datetime.now(timezone.utc).timestamp())))
            await _set_app_setting("ml_last_sync_synced", str(int(res.get("synced", 0) or 0)))
            await _set_app_setting("ml_last_sync_skipped", str(int(res.get("skipped", 0) or 0)))
            await _set_app_setting("ml_last_sync_full", "1" if need_full_sync else "0")
            await _set_app_setting("ml_last_autosync_at_ts", str(int(datetime.now(timezone.utc).timestamp())))

            # Каждые 10 мин: подтягиваем из main в ML всё — длительность, кф, фичи, статистика игроков/лиг
            _DURATION_LIMIT = 15_000
            _ODDS_LIMIT = 50_000
            _FEATURES_LIMIT = 30_000
            _PLAYER_DAILY_LIMIT = 15_000
            _PLAYER_STYLE_LIMIT = 5_000
            _ELO_HISTORY_LIMIT = 20_000
            _LEAGUE_PERF_LIMIT = 15_000

            async def _safe_thread(name: str, fn, *args, **kwargs):
                """Выполняет тяжёлую sync-функцию в пуле потоков, не блокируя прогнозы и линию."""
                try:
                    return await asyncio.to_thread(fn, *args, **kwargs) or 0
                except Exception as e:
                    logger.debug("ML %s: %s", name, e)
                    return 0

            dur_updated = 0
            odds_updated = 0
            try:
                d_res = await backfill_duration_from_main_incremental_once(
                    limit=_DURATION_LIMIT,
                    after_match_id=int(duration_cursor or 0),
                )
                dur_updated = int((d_res or {}).get("updated", 0) or 0)
                if int((d_res or {}).get("fetched", 0) or 0) > 0:
                    await _set_app_setting(
                        _DURATION_CURSOR_KEY,
                        str(int((d_res or {}).get("last_match_id", duration_cursor) or duration_cursor or 0)),
                    )
                if dur_updated > 0:
                    logger.info("ML duration backfill: %s matches", dur_updated)
            except Exception as e:
                logger.debug("ML duration backfill: %s", e)
            try:
                o_res = await asyncio.to_thread(
                    backfill_odds_from_main_incremental_once,
                    _ODDS_LIMIT,
                    int(odds_cursor or 0),
                )
                odds_updated = int((o_res or {}).get("added", 0) or 0)
                o_fetched = int((o_res or {}).get("fetched", 0) or 0)
                o_last_id = int((o_res or {}).get("last_match_id", odds_cursor) or odds_cursor or 0)
                if o_fetched > 0:
                    await _set_app_setting(_ODDS_CURSOR_KEY, str(o_last_id))
                if odds_updated > 0:
                    logger.info("ML odds backfill from main: %s rows", odds_updated)
                # Чтобы на дашборде «Odds backfill (последний запуск)» отражал и автоматический прогон
                await _set_app_setting("ml_last_odds_backfill_at_ts", str(int(datetime.now(timezone.utc).timestamp())))
                await _set_app_setting("ml_last_odds_backfill_added_total", str(odds_updated))
                await _set_app_setting("ml_last_odds_backfill_api_total", "0")
                await _set_app_setting("ml_last_odds_backfill_cursor", str(o_last_id))
            except Exception as e:
                logger.debug("ML odds backfill: %s", e)
            features_added = 0
            try:
                f_res = await asyncio.to_thread(
                    backfill_features_incremental_once,
                    _FEATURES_LIMIT,
                    int(features_cursor or 0),
                    None,
                    int(getattr(settings, "ml_backfill_workers", 6)),
                )
                features_added = int((f_res or {}).get("features_added", 0) or 0)
                if int((f_res or {}).get("fetched", 0) or 0) > 0:
                    await _set_app_setting(
                        _FEATURES_CURSOR_KEY,
                        str(int((f_res or {}).get("last_match_id", features_cursor) or features_cursor or 0)),
                    )
            except Exception as e:
                logger.debug("ML features: %s", e)
            if features_added > 0:
                logger.info("ML features backfill: %s matches", features_added)
            suspicious_count = await _safe_thread("suspicious", check_suspicious_matches_once, 5000)
            if suspicious_count > 0:
                logger.info("ML suspicious matches: %s flagged", suspicious_count)
            daily_stats = await _safe_thread("player_daily_stats", backfill_player_daily_stats_once, _PLAYER_DAILY_LIMIT)
            if daily_stats > 0:
                logger.info("ML player_daily_stats: %s rows", daily_stats)
            style_count = await _safe_thread("player_style", backfill_player_style_once, _PLAYER_STYLE_LIMIT)
            if style_count > 0:
                logger.info("ML player_style: %s players", style_count)
            elo_hist = await _safe_thread("player_elo_history", backfill_player_elo_history_once, _ELO_HISTORY_LIMIT)
            if elo_hist > 0:
                logger.info("ML player_elo_history: %s rows", elo_hist)
            leagues_updated = await _safe_thread("league_performance", update_league_performance_once, _LEAGUE_PERF_LIMIT)
            if leagues_updated > 0:
                logger.info("ML league performance: %s leagues updated", leagues_updated)
            now_ts = int(datetime.now(timezone.utc).timestamp())
            # Время последнего успешного переобучения и последней постановки в очередь — из БД (чтобы работало после рестарта и при очереди в ml_worker)
            last_retrain_raw = await _get_app_setting("ml_last_retrain_at_ts")
            last_requested_raw = await _get_app_setting(_RETRAIN_REQUESTED_TS_KEY)
            last_retrain_ts = int(last_retrain_raw or 0)
            last_requested_ts = int(last_requested_raw or 0)
            last_any_ts = max(last_retrain_ts, last_requested_ts)
            due_by_time = last_any_ts == 0 or (now_ts - last_any_ts) >= retrain_interval_sec
            due_by_volume = total_synced >= min_new_for_retrain or features_added >= min_new_for_retrain
            if due_by_volume or due_by_time:
                from app.ml.anomaly import fit_anomaly_model
                try:
                    await asyncio.to_thread(fit_anomaly_model, limit=10_000)
                except Exception:
                    pass
                # Ставим переобучение в очередь — выполняет ml_worker (GPU). В tt_workers нет LightGBM/GPU, прямой вызов бы падал.
                if enqueue("retrain", {"min_rows": min_new_for_retrain}):
                    await _set_app_setting(_RETRAIN_REQUESTED_TS_KEY, str(now_ts))
                    logger.info(
                        "ML retrain поставлен в очередь (min_rows=%s). Выполнит ml_worker.",
                        min_new_for_retrain,
                    )
                else:
                    logger.warning("ML retrain: не удалось добавить в очередь")
        except Exception:
            logger.exception("ML sync failed")
        finally:
            # Каждый цикл (раз в 10 мин) обновляем метки подтяжки, чтобы в админке отображалась актуальная информация
            now_ts_str = str(int(datetime.now(timezone.utc).timestamp()))
            pulled_total = int(dur_updated or 0) + int(odds_updated or 0) + int(features_added or 0) + int(daily_stats or 0) + int(style_count or 0) + int(elo_hist or 0) + int(leagues_updated or 0)
            await _set_app_setting("ml_last_autosync_at_ts", now_ts_str)
            await _set_app_setting("ml_last_data_pull_at_ts", now_ts_str)
            await _set_app_setting("ml_last_data_pull_total", str(pulled_total))
            await _set_app_setting("ml_last_data_pull_odds", str(int(odds_updated or 0)))
            await _set_app_setting("ml_last_data_pull_features", str(int(features_added or 0)))
        await asyncio.sleep(interval)
