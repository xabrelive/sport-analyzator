"""CLI для ML-операций. Режимы:
  python -m app.ml.worker_cli run   — воркер-демон, обрабатывает очередь (отдельный контейнер)
  python -m app.ml.worker_cli sync --limit 5000  — разовый запуск (для тестов)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


def _echo(msg: str) -> None:
    """Вывод в stdout с flush — видно в docker logs."""
    print(msg, flush=True)


def _progress_file() -> Path:
    base = os.environ.get("ML_MODEL_DIR", "/tmp/pingwin_ml_models")
    return Path(base) / "progress.json"


def _write_progress(op: str, **kwargs: object) -> None:
    path = _progress_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except Exception:
            pass
    if op not in data:
        data[op] = {"status": "idle", "message": "", "current": 0, "total": 0, "result": None, "error": None}
    now_ts = int(time.time())
    data[op]["updated_at_ts"] = now_ts
    data[op].update(kwargs)
    if data[op].get("status") == "done":
        data[op]["completed_at_ts"] = now_ts
    path.write_text(json.dumps(data, ensure_ascii=False))


def _reset_progress(op: str) -> None:
    _write_progress(op, status="idle", message="", current=0, total=0, result=None, error=None)


def _save_runtime_meta(values: dict[str, object]) -> None:
    """Сохраняет служебные метрики в app_setting (основная БД)."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool
    from app.config import settings

    try:
        engine = create_engine(settings.database_url, poolclass=NullPool)
        with engine.begin() as conn:
            for key, value in values.items():
                conn.execute(
                    text(
                        "INSERT INTO app_setting (key, value) VALUES (:k, :v) "
                        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
                    ),
                    {"k": str(key), "v": str(value)},
                )
        engine.dispose()
    except Exception as e:
        logger.warning("Failed to save ML runtime meta: %s", e)


def run_backfill_odds(limit: int = 50000) -> int:
    """Дозаполняет ML odds из основной БД."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool
    from app.config import settings
    from app.ml.pipeline import backfill_odds_from_main_incremental_once

    cursor_key = "ml_odds_backfill_cursor_v1"
    cursor = 0
    try:
        engine = create_engine(settings.database_url, poolclass=NullPool)
        with engine.connect() as conn:
            raw = conn.execute(
                text("SELECT value FROM app_setting WHERE key = :k"),
                {"k": cursor_key},
            ).scalar_one_or_none()
        engine.dispose()
        cursor = int(raw or 0)
    except Exception:
        cursor = 0

    result = backfill_odds_from_main_incremental_once(limit=limit, after_match_id=cursor)
    added = int((result or {}).get("added", 0) or 0)
    fetched = int((result or {}).get("fetched", 0) or 0)
    last_match_id = int((result or {}).get("last_match_id", cursor) or cursor or 0)
    if fetched > 0:
        _save_runtime_meta({cursor_key: last_match_id})
    return added


def run_odds_backfill_bg(limit: int = 5000, batches: int = 100, pause_ms: int = 600) -> dict:
    """Фоновая догрузка odds батчами с курсором и fallback через BetsAPI."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool
    from app.config import settings
    from app.ml.pipeline import backfill_odds_from_main_incremental_once

    cursor_key = "ml_odds_backfill_cursor_v1"
    engine = create_engine(settings.database_url, poolclass=NullPool)
    with engine.connect() as conn:
        raw = conn.execute(
            text("SELECT value FROM app_setting WHERE key = :k"),
            {"k": cursor_key},
        ).scalar_one_or_none()
    cursor = int(raw or 0)

    total_added = 0
    total_api = 0
    total_fetched = 0
    zero_added_streak = 0
    steps = max(1, int(batches or 1))

    for i in range(1, steps + 1):
        res = backfill_odds_from_main_incremental_once(limit=max(100, int(limit or 100)), after_match_id=cursor)
        fetched = int((res or {}).get("fetched", 0) or 0)
        added = int((res or {}).get("added", 0) or 0)
        api = int((res or {}).get("fetched_from_api", 0) or 0)
        cursor = int((res or {}).get("last_match_id", cursor) or cursor)

        total_fetched += fetched
        total_added += added
        total_api += api

        if fetched > 0:
            _save_runtime_meta({cursor_key: cursor})

        _write_progress(
            "odds_backfill",
            status="running",
            current=i,
            total=steps,
            message=f"batch={i}/{steps}: fetched={fetched}, added={added}, api={api}",
            result={
                "fetched_total": total_fetched,
                "added_total": total_added,
                "api_total": total_api,
                "cursor": cursor,
            },
        )

        if fetched == 0:
            break
        if added == 0:
            zero_added_streak += 1
        else:
            zero_added_streak = 0
        if zero_added_streak >= 20:
            break
        time.sleep(max(0, int(pause_ms)) / 1000.0)

    summary = {
        "fetched_total": total_fetched,
        "added_total": total_added,
        "api_total": total_api,
        "cursor": cursor,
    }
    _write_progress("odds_backfill", status="done", result=summary, message="Готово")
    _save_runtime_meta(
        {
            "ml_last_odds_backfill_at_ts": int(time.time()),
            "ml_last_odds_backfill_added_total": int(total_added),
            "ml_last_odds_backfill_api_total": int(total_api),
            "ml_last_odds_backfill_cursor": int(cursor),
        }
    )
    engine.dispose()
    return summary


def run_sync(limit: int, days_back: int, full: bool) -> None:
    from app.config import settings
    if str(getattr(settings, "ml_engine", "v1")).lower() == "v2":
        from app.ml_v2.sync import (
            sync_finished_to_ch_once,
            sync_missing_finished_to_ch_full_scan_once,
        )
        from app.ml_v2.schema import ensure_schema

        ensure_schema()
        base_limit = max(1000, int(limit or 1000))
        full_limit = max(5000, base_limit) if full else 0
        max_passes = 200 if full else 0

        _echo("  Sync: cursor pass (limit=%s)..." % base_limit)

        async def _v2_sync_all() -> dict:
            """Single event loop: cursor sync + optional full-scan passes + match_sets backfill."""
            from app.ml_v2.sync import backfill_match_sets_from_main

            result = await sync_finished_to_ch_once(limit=base_limit)
            cur_synced = int((result or {}).get("synced", 0) or 0)
            _echo("  Sync: cursor done, synced=%s" % cur_synced)
            full_synced = 0
            if full and max_passes > 0:
                for pass_no in range(1, max_passes + 1):
                    miss = await sync_missing_finished_to_ch_full_scan_once(limit=full_limit)
                    synced_now = int((miss or {}).get("synced", 0) or 0)
                    full_synced += synced_now
                    _echo("  Sync: full-scan pass %s, synced=%s, total_full=%s" % (pass_no, synced_now, full_synced))
                    if synced_now <= 0:
                        break
            # Дозаполнение ml.match_sets для матчей без сетов (разрыв по сетовой детализации)
            sets_filled_total = 0
            for _ in range(50):
                sb = await backfill_match_sets_from_main(limit=3000)
                filled = int((sb or {}).get("filled", 0) or 0)
                sets_filled_total += filled
                if filled <= 0:
                    break
                _echo("  Sync: match_sets backfill, filled=%s sets_inserted=%s remaining=%s" % (
                    sb.get("filled"), sb.get("sets_inserted"), sb.get("remaining")))
            if sets_filled_total > 0:
                _echo("  Sync: match_sets backfill total filled=%s" % sets_filled_total)
            out = dict(result or {})
            out["synced"] = int(out.get("synced", 0) or 0) + int(full_synced)
            out["match_sets_filled"] = sets_filled_total
            if full:
                out["full_scan_synced"] = int(full_synced)
            return out

        result = asyncio.run(_v2_sync_all())
        _echo("  Sync: total synced=%s" % (result.get("synced", 0) or 0))
        _write_progress("sync", status="done", result=result, message="ML v2 sync done")
        _save_runtime_meta(
            {
                "ml_last_sync_at_ts": int(time.time()),
                "ml_last_sync_synced": int(result.get("synced", 0) or 0),
                "ml_last_sync_skipped": 0,
                "ml_last_sync_full": "1" if full else "0",
            }
        )
        return

    from app.ml.pipeline import sync_leagues_to_ml, sync_players_to_ml, sync_finished_to_ml_once, sync_full_main_to_ml

    def cb(current: int, total: int, message: str) -> None:
        _write_progress("sync", status="running", current=current, total=total or 0, message=message)
        _echo(f"  Sync: {message}")

    async def _do() -> dict:
        d_back: int | None = 0 if days_back == 0 else days_back
        batch_size = min(max(limit, getattr(settings, "ml_sync_batch_size", 15000)), 50000) if full else limit
        if full:
            _write_progress("sync", status="running", message="Синхр. лиг и игроков…")
            await sync_leagues_to_ml()
            await sync_players_to_ml()
            return await sync_full_main_to_ml(batch_size=batch_size, days_back=d_back, progress_callback=cb)
        return await sync_finished_to_ml_once(limit=limit, days_back=d_back)

    result = asyncio.run(_do())
    if not full:
        _write_progress("sync", message=f"Синхронизировано: {result.get('synced', 0)}, пропущено: {result.get('skipped', 0)}")
    _write_progress("sync", status="done", result=result, message="Готово")
    _save_runtime_meta(
        {
            "ml_last_sync_at_ts": int(time.time()),
            "ml_last_sync_synced": int(result.get("synced", 0) or 0),
            "ml_last_sync_skipped": int(result.get("skipped", 0) or 0),
            "ml_last_sync_full": "1" if full else "0",
        }
    )


def run_backfill(limit: int, workers: int = 6) -> None:
    from app.config import settings
    if str(getattr(settings, "ml_engine", "v1")).lower() == "v2":
        from app.ml_v2.features import rebuild_features_to_ch, feature_coverage_stats, feature_schema_signature

        batch = max(1000, int(limit or 1000))
        # 1) incremental pass for newly synced matches
        _echo("  Backfill: incremental pass (limit=%s)..." % batch)
        inc = rebuild_features_to_ch(mode="incremental", limit=batch)
        total_added = int((inc or {}).get("features_added", 0) or 0)
        _echo("  Backfill: incremental done, added=%s" % total_added)
        # 2) missing pass: catches historical gaps where features were never built
        missing_added = 0
        max_passes = 200
        for i in range(1, max_passes + 1):
            miss = rebuild_features_to_ch(mode="missing", limit=batch)
            added = int((miss or {}).get("features_added", 0) or 0)
            missing_added += added
            total_added += added
            remaining = int((miss or {}).get("remaining_missing", 0) or 0)
            _echo("  Backfill: missing pass %s, +%s, remaining=%s (total_added=%s)" % (i, added, remaining, total_added))
            _write_progress(
                "backfill",
                status="running",
                current=i,
                total=max_passes,
                message=f"ML v2 missing backfill: +{added}, remaining={remaining}",
                result={
                    "features_added_total": total_added,
                    "features_added_missing": missing_added,
                    "remaining_missing": remaining,
                },
            )
            if added <= 0 or remaining <= 0:
                break
        # 3) schema-refresh pass: for new columns, rewrite historical rows progressively.
        refresh_added = 0
        sig_key = "ml_v2_features_applied_signature"
        cursor_key = "ml_v2_features_refresh_cursor"
        target_sig = feature_schema_signature()
        current_sig = ""
        current_cursor = ""
        try:
            from sqlalchemy import create_engine, text
            from sqlalchemy.pool import NullPool
            from app.config import settings as _s

            e = create_engine(_s.database_url, poolclass=NullPool)
            with e.connect() as conn:
                current_sig = str(
                    conn.execute(text("SELECT value FROM app_setting WHERE key=:k"), {"k": sig_key}).scalar_one_or_none()
                    or ""
                ).strip()
                current_cursor = str(
                    conn.execute(text("SELECT value FROM app_setting WHERE key=:k"), {"k": cursor_key}).scalar_one_or_none()
                    or ""
                ).strip()
            e.dispose()
        except Exception:
            current_sig = ""
            current_cursor = ""
        if current_sig != target_sig:
            _echo("  Backfill: schema refresh (signature changed)...")
            c_dt = None
            c_mid = ""
            if current_cursor:
                if "|" in current_cursor:
                    dt_raw, c_mid = current_cursor.split("|", 1)
                    try:
                        from datetime import datetime

                        c_dt = datetime.fromisoformat(dt_raw)
                    except Exception:
                        c_dt = None
                        c_mid = ""
                else:
                    try:
                        from datetime import datetime

                        c_dt = datetime.fromisoformat(current_cursor)
                    except Exception:
                        c_dt = None
            refresh_limit = max(
                1000,
                int(getattr(settings, "ml_v2_refresh_backfill_limit", batch) or batch),
            )
            rr = rebuild_features_to_ch(
                mode="refresh",
                limit=refresh_limit,
                cursor_start_time=c_dt,
                cursor_match_id=c_mid,
            )
            refresh_added = int((rr or {}).get("features_added", 0) or 0)
            total_added += refresh_added
            _echo("  Backfill: schema refresh done, added=%s" % refresh_added)
            next_ts = str((rr or {}).get("refresh_next_cursor_start_time", "") or "")
            next_mid = str((rr or {}).get("refresh_next_cursor_match_id", "") or "")
            refresh_done = bool((rr or {}).get("refresh_done", False))
            try:
                from sqlalchemy import create_engine, text
                from sqlalchemy.pool import NullPool
                from app.config import settings as _s

                e = create_engine(_s.database_url, poolclass=NullPool)
                with e.begin() as conn:
                    if refresh_done:
                        conn.execute(
                            text(
                                "INSERT INTO app_setting (key, value) VALUES (:k,:v) "
                                "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value"
                            ),
                            {"k": sig_key, "v": target_sig},
                        )
                        conn.execute(
                            text(
                                "INSERT INTO app_setting (key, value) VALUES (:k,:v) "
                                "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value"
                            ),
                            {"k": cursor_key, "v": ""},
                        )
                    else:
                        conn.execute(
                            text(
                                "INSERT INTO app_setting (key, value) VALUES (:k,:v) "
                                "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value"
                            ),
                            {"k": cursor_key, "v": f"{next_ts}|{next_mid}" if next_ts else ""},
                        )
                e.dispose()
            except Exception:
                pass
        cov = feature_coverage_stats()
        remaining = int(cov.get("missing_features", 0))
        _echo(
            "  Backfill: done. total_added=%s (incremental + missing=%s + refresh=%s), remaining_missing=%s, features_total=%s"
            % (total_added, missing_added, refresh_added, remaining, int(cov.get("features_total", 0) or 0))
        )
        _write_progress(
            "backfill",
            status="done",
            result={
                "features_added": total_added,
                "features_added_missing": missing_added,
                "features_added_refresh": refresh_added,
                "remaining_missing": remaining,
                "matches_total": int(cov.get("matches_total", 0)),
                "features_total": int(cov.get("features_total", 0)),
            },
            message=(
                f"Добавлено фичей v2: {total_added} "
                f"(missing: {missing_added}, refresh: {refresh_added}), осталось: {remaining}"
            ),
        )
        return

    from app.ml.pipeline import backfill_features_incremental_once

    workers = workers or getattr(settings, "ml_backfill_workers", 6)
    cursor_key = "ml_features_backfill_cursor_v1"
    cursor = 0
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.pool import NullPool
        engine = create_engine(settings.database_url, poolclass=NullPool)
        with engine.connect() as conn:
            raw = conn.execute(
                text("SELECT value FROM app_setting WHERE key = :k"),
                {"k": cursor_key},
            ).scalar_one_or_none()
        engine.dispose()
        cursor = int(raw or 0)
    except Exception:
        cursor = 0

    def cb(current: int, total: int, message: str) -> None:
        _write_progress("backfill", status="running", current=current, total=total, message=message)
        if total and (current % 10000 == 0 or current == total):
            _echo(f"  Backfill: {message}")

    result = backfill_features_incremental_once(
        limit=limit,
        after_match_id=int(cursor or 0),
        progress_callback=cb,
        workers=workers,
    )
    count = int((result or {}).get("features_added", 0) or 0)
    fetched = int((result or {}).get("fetched", 0) or 0)
    last_match_id = int((result or {}).get("last_match_id", cursor) or cursor or 0)
    if fetched > 0:
        _save_runtime_meta({cursor_key: last_match_id})
    _write_progress(
        "backfill",
        status="done",
        result={"features_added": count, "fetched": fetched, "last_match_id": last_match_id},
        message=f"Добавлено фичей: {count}",
    )


def run_player_stats(limit: int) -> None:
    """Backfill player_daily_stats, player_style, player_elo_history."""
    from app.ml.player_stats import (
        backfill_player_daily_stats_once,
        backfill_player_style_once,
        backfill_player_elo_history_once,
    )
    _echo("  Player stats: daily_stats…")
    d = backfill_player_daily_stats_once(limit=limit)
    _echo("  Player stats: daily_stats=%d, style…" % d)
    s = backfill_player_style_once(limit=min(limit, 5000))
    _echo("  Player stats: style=%d, elo_history…" % s)
    e = backfill_player_elo_history_once(limit=limit * 2)
    _echo("  Player stats: elo_history=%d" % e)
    _write_progress(
        "player_stats",
        status="done",
        result={"daily_stats": d, "style": s, "elo_history": e},
        message=f"daily_stats={d}, style={s}, elo_history={e}",
    )


def run_league_performance(limit: int) -> None:
    from app.ml.league_performance import update_league_performance_once

    count = update_league_performance_once(limit=limit)
    _write_progress("league_performance", status="done", result={"leagues_updated": count}, message=f"Обновлено лиг: {count}")


def run_retrain(min_rows: int) -> None:
    from app.config import settings

    def cb(current: int, total: int, message: str) -> None:
        _write_progress("retrain", status="running", current=current, total=total, message=message)
        _echo(f"  [{current}/{total}] {message}")

    is_v2 = str(getattr(settings, "ml_engine", "v1")).lower() == "v2"
    if is_v2:
        from app.ml_v2.eval import evaluate_filtered_signals
        from app.ml_v2.trainer import retrain_models_v2

        _echo("  Retrain: ML v2 start (min_rows=%s)..." % min_rows)
        _write_progress("retrain", status="running", current=0, total=3, message="ML v2 retrain: старт (GPU)")
        result = retrain_models_v2(min_rows=min_rows)
        _echo("  Retrain: training done, evaluating KPI...")
        _write_progress("retrain", status="running", current=2, total=3, message="ML v2 retrain: KPI evaluation")
        kpi = evaluate_filtered_signals()
        result = dict(result)
        result["kpi"] = kpi
        result["train_device"] = "cuda"
    else:
        from app.ml.model_trainer import retrain_models_if_needed

        result = retrain_models_if_needed(min_rows=min_rows, version="v1", progress_callback=cb)

    if (not is_v2) and os.environ.get("ML_GPU_ONLY", "true").strip().lower() not in ("1", "true", "yes"):
        try:
            from app.ml.anomaly import fit_anomaly_model
            fit_anomaly_model(limit=10_000)
        except Exception:
            pass
    if is_v2 and result:
        _echo("  Retrain: trained=%s, rows=%s, path=%s" % (
            result.get("trained"), result.get("rows", 0) or 0, result.get("path", "") or "",
        ))
    _write_progress("retrain", status="done", result=result, message="Готово")
    meta = {
        "ml_last_retrain_at_ts": int(time.time()),
        "ml_last_retrain_trained": "1" if bool(result.get("trained")) else "0",
        "ml_last_retrain_rows": int(result.get("rows", 0) or 0),
        "ml_last_retrain_path": str(result.get("path", "") or ""),
    }
    if bool(result.get("trained")):
        meta["ml_last_model_created_at_ts"] = int(time.time())
    if is_v2:
        meta["ml_v2_last_retrain_at_ts"] = int(time.time())
        meta["ml_v2_last_retrain_trained"] = "1" if bool(result.get("trained")) else "0"
        meta["ml_v2_last_retrain_rows"] = int(result.get("rows", 0) or 0)
        if bool(result.get("trained")):
            meta["ml_v2_last_model_created_at_ts"] = int(time.time())
        meta["ml_v2_last_retrain_device"] = str(result.get("train_device", "cuda"))
        if result.get("kpi") is not None:
            meta["ml_v2_last_kpi"] = json.dumps(result.get("kpi"), ensure_ascii=False)
    _save_runtime_meta(meta)


def run_full_rebuild(
    sync_limit: int = 50000,
    backfill_limit: int = 100000,
    player_stats_limit: int = 50000,
    league_limit: int = 50000,
    min_rows: int = 500,
) -> dict:
    """Полный цикл: sync → backfill → player_stats → league_performance → retrain.
    Возвращает итоговую сводку."""
    from app.config import settings
    if str(getattr(settings, "ml_engine", "v1")).lower() == "v2":
        from app.ml_v2.eval import evaluate_filtered_signals

        _echo("")
        _echo("[Full rebuild] 1/3 Sync main -> ML (limit=%s)..." % sync_limit)
        w = int(getattr(settings, "ml_backfill_workers", 6) or 6)
        run_sync(sync_limit, days_back=0, full=True)
        try:
            data = json.loads(_progress_file().read_text())
            sync_res = (data.get("sync") or {}).get("result") or {}
            _echo("[Full rebuild] Sync done: synced=%s" % (sync_res.get("synced", 0) or 0))
        except Exception:
            _echo("[Full rebuild] Sync done.")
        _echo("")
        _echo("[Full rebuild] 2/3 Backfill features (limit=%s)..." % backfill_limit)
        run_backfill(backfill_limit, workers=w)
        try:
            data = json.loads(_progress_file().read_text())
            bf_res = (data.get("backfill") or {}).get("result") or {}
            _echo("[Full rebuild] Backfill done: features_added=%s, remaining_missing=%s" % (
                bf_res.get("features_added", 0) or 0,
                bf_res.get("remaining_missing", 0) or 0,
            ))
        except Exception:
            _echo("[Full rebuild] Backfill done.")
        _echo("")
        _echo("[Full rebuild] 3/3 Retrain models (min_rows=%s)..." % min_rows)
        run_retrain(min_rows=min_rows)
        _echo("[Full rebuild] Retrain done. Evaluating KPI...")
        kpi = evaluate_filtered_signals()
        _echo("[Full rebuild] KPI: %s" % (kpi or {}))
        _echo("")
        _echo("[Full rebuild] Done.")
        out = {
            "sync": {},
            "backfill": {},
            "retrain": {},
            "kpi": kpi,
            "ok": True,
        }
        _write_progress("full_rebuild", status="done", result=out, message="ML v2 full rebuild done")
        return out

    def _get_result(op: str) -> dict:
        try:
            data = json.loads(_progress_file().read_text())
            return data.get(op, {}).get("result") or {}
        except Exception:
            return {}

    def _log(msg: str, *args: object) -> None:
        s = "[Full rebuild] " + (msg % args if args else msg)
        logger.info(s)
        _echo(s)

    _log("1/6 Синхронизация main→ML…")
    _write_progress("full_rebuild", status="running", message="1/6 Синхронизация…")
    run_sync(sync_limit, days_back=0, full=True)
    sync_res = _get_result("sync")
    _log("Sync готово: synced=%s, skipped=%s", sync_res.get("synced", 0), sync_res.get("skipped", 0))

    _echo("")
    _log("2/6 Backfill odds из main…")
    _write_progress("full_rebuild", status="running", message="2/6 Backfill odds…")
    odds_count = run_backfill_odds(limit=50000)
    _log("Odds backfill: %s rows", odds_count)

    _echo("")
    _log("3/6 Player stats (daily, style, elo_history)…")
    _write_progress("full_rebuild", status="running", message="3/6 Player stats…")
    run_player_stats(player_stats_limit)
    ps_res = _get_result("player_stats")
    _log("Player stats готово: %s", ps_res)

    _echo("")
    _log("4/6 Backfill фичей…")
    _write_progress("full_rebuild", status="running", message="4/6 Backfill фичей…")
    run_backfill(backfill_limit)
    backfill_res = _get_result("backfill")
    _log("Backfill готово: features_added=%s", backfill_res.get("features_added", 0))

    _echo("")
    _log("5/6 League performance…")
    _write_progress("full_rebuild", status="running", message="5/6 League performance…")
    run_league_performance(league_limit)
    _log("League performance готово")

    _echo("")
    _log("6/6 Обучение моделей (retrain)…")
    _write_progress("full_rebuild", status="running", message="6/6 Обучение моделей…")
    run_retrain(min_rows=min_rows)
    retrain_res = _get_result("retrain")
    _log("Retrain готово: trained=%s, rows=%s", retrain_res.get("trained"), retrain_res.get("rows"))

    _echo("")
    _log("=== Full rebuild завершён ===")
    summary = {"sync": sync_res, "backfill": backfill_res, "retrain": retrain_res}
    _write_progress("full_rebuild", status="done", result=summary, message="Готово")
    logger.info("Full rebuild done: sync=%s, backfill=%s, retrain=%s", sync_res, backfill_res, retrain_res)
    return summary


def run_sync_audit(sample_limit: int = 5000, missing_preview: int = 20) -> dict:
    """Ручная сверка main↔ML по матчам/игрокам/лигам + preview пропусков. Для ML_ENGINE=v2 — main vs ClickHouse."""
    from sqlalchemy import create_engine, text
    from app.config import settings

    main_engine = create_engine(settings.database_url)
    is_v2 = str(getattr(settings, "ml_engine", "v1")).lower() == "v2"

    if is_v2:
        from app.ml_v2.ch_client import get_ch_client
        from app.ml_v2.schema import ensure_schema
        ensure_schema()
        client = get_ch_client()
        main_finished = int(
            main_engine.connect()
            .execute(
                text(
                    "SELECT COUNT(*) FROM table_tennis_line_events "
                    "WHERE status='finished' AND live_sets_score IS NOT NULL"
                )
            ).scalar()
            or 0
        )
        ch_matches = int(client.query("SELECT count() FROM ml.matches FINAL").result_rows[0][0] or 0)
        ch_features = int(client.query("SELECT count() FROM ml.match_features FINAL").result_rows[0][0] or 0)
        ch_players = int(client.query("SELECT count() FROM ml.players FINAL").result_rows[0][0] or 0)
        ch_leagues = int(client.query("SELECT count() FROM ml.leagues FINAL").result_rows[0][0] or 0)
        with main_engine.connect() as m:
            recent_main_ids = [
                str(r[0])
                for r in m.execute(
                    text(
                        "SELECT id FROM table_tennis_line_events "
                        "WHERE status='finished' AND live_sets_score IS NOT NULL "
                        "ORDER BY starts_at DESC LIMIT :lim"
                    ),
                    {"lim": max(100, int(sample_limit))},
                ).fetchall()
            ]
        existing_recent = set()
        if recent_main_ids:
            chunk_size = 1500
            for i in range(0, min(len(recent_main_ids), 5000), chunk_size):
                chunk = recent_main_ids[i : i + chunk_size]
                placeholders = ",".join([f"'{str(x)}'" for x in chunk])
                rows = client.query(f"SELECT match_id FROM ml.matches WHERE match_id IN ({placeholders})").result_rows
                existing_recent.update(str(r[0]) for r in rows)
        missing_recent = [eid for eid in recent_main_ids if eid not in existing_recent]
        main_engine.dispose()
        result = {
            "engine": "v2",
            "main_finished_events": main_finished,
            "ch_matches": ch_matches,
            "ch_match_features": ch_features,
            "delta_matches_main_minus_ch": main_finished - ch_matches,
            "delta_ch_matches_minus_features": ch_matches - ch_features,
            "ch_players": ch_players,
            "ch_leagues": ch_leagues,
            "recent_sample_checked": len(recent_main_ids),
            "recent_missing_in_ch_count": len(missing_recent),
            "recent_missing_preview": missing_recent[: max(1, int(missing_preview))],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return result

    ml_engine = create_engine(settings.database_url_ml.replace("+asyncpg", ""))
    result = {}
    with main_engine.connect() as m, ml_engine.connect() as d:
        main_finished = int(
            m.execute(
                text(
                    "SELECT COUNT(*) FROM table_tennis_line_events "
                    "WHERE status='finished' AND live_sets_score IS NOT NULL"
                )
            ).scalar()
            or 0
        )
        ml_matches = int(d.execute(text("SELECT COUNT(*) FROM matches")).scalar() or 0)
        main_players = int(m.execute(text("SELECT COUNT(*) FROM table_tennis_players")).scalar() or 0)
        ml_players = int(d.execute(text("SELECT COUNT(*) FROM players")).scalar() or 0)
        main_leagues = int(m.execute(text("SELECT COUNT(*) FROM table_tennis_leagues")).scalar() or 0)
        ml_leagues = int(d.execute(text("SELECT COUNT(*) FROM leagues")).scalar() or 0)
        recent_main_ids = [
            str(r[0])
            for r in m.execute(
                text(
                    "SELECT id FROM table_tennis_line_events "
                    "WHERE status='finished' AND live_sets_score IS NOT NULL "
                    "ORDER BY starts_at DESC LIMIT :lim"
                ),
                {"lim": max(100, int(sample_limit))},
            ).fetchall()
        ]
        existing_recent = set()
        if recent_main_ids:
            existing_recent = {
                str(r[0])
                for r in d.execute(
                    text("SELECT external_id FROM matches WHERE external_id = ANY(:ids)"),
                    {"ids": recent_main_ids},
                ).fetchall()
            }
        missing_recent = [eid for eid in recent_main_ids if eid not in existing_recent]
    result = {
        "engine": "v1",
        "main_finished_events": main_finished,
        "ml_matches": ml_matches,
        "delta_matches_main_minus_ml": main_finished - ml_matches,
        "main_players": main_players,
        "ml_players": ml_players,
        "delta_players_main_minus_ml": main_players - ml_players,
        "main_leagues": main_leagues,
        "ml_leagues": ml_leagues,
        "delta_leagues_main_minus_ml": main_leagues - ml_leagues,
        "recent_sample_checked": len(recent_main_ids),
        "recent_missing_count": len(missing_recent),
        "recent_missing_preview": missing_recent[: max(1, int(missing_preview))],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return result


def request_full_sync_once() -> None:
    """Ставит флаг: следующий проход ml_sync_loop выполнит полную синхронизацию."""
    from sqlalchemy import select
    from app.db.session import async_session_maker
    from app.models.app_setting import AppSetting

    async def _do() -> None:
        async with async_session_maker() as session:
            row = (
                await session.execute(
                    select(AppSetting).where(AppSetting.key == "ml_sync_force_full_once")
                )
            ).scalar_one_or_none()
            if row:
                row.value = "1"
            else:
                session.add(AppSetting(key="ml_sync_force_full_once", value="1"))
            await session.commit()
        print("ml_sync_force_full_once=1", flush=True)

    asyncio.run(_do())


def _execute_job(job: dict) -> None:
    typ = job.get("type")
    params = job.get("params", {})
    if typ == "sync":
        _reset_progress("sync")
        _write_progress("sync", status="running", message="Старт…")
        run_sync(
            params.get("limit", 500),
            params.get("days_back", 0),
            params.get("full", False),
        )
    elif typ == "backfill":
        _reset_progress("backfill")
        _write_progress("backfill", status="running", message="Старт…")
        run_backfill(params.get("limit", 50000), workers=params.get("workers"))
    elif typ == "odds_backfill":
        _reset_progress("odds_backfill")
        _write_progress("odds_backfill", status="running", message="Старт…")
        run_odds_backfill_bg(
            limit=params.get("limit", 5000),
            batches=params.get("batches", 100),
            pause_ms=params.get("pause_ms", 600),
        )
    elif typ == "retrain":
        _reset_progress("retrain")
        _write_progress("retrain", status="running", message="Старт…")
        from app.config import settings as _s
        default_min_rows = 1000 if str(getattr(_s, "ml_engine", "v1")).lower() == "v2" else 100
        run_retrain(params.get("min_rows", default_min_rows))
    elif typ == "league_performance":
        _reset_progress("league_performance")
        _write_progress("league_performance", status="running", message="Старт…")
        run_league_performance(params.get("limit", 10000))
    elif typ == "player_stats":
        _reset_progress("player_stats")
        _write_progress("player_stats", status="running", message="Старт…")
        run_player_stats(params.get("limit", 10000))
    elif typ == "full_rebuild":
        _reset_progress("full_rebuild")
        _write_progress("full_rebuild", status="running", message="Старт…")
        run_full_rebuild(
            sync_limit=params.get("sync_limit", 50000),
            backfill_limit=params.get("backfill_limit", 100000),
            player_stats_limit=params.get("player_stats_limit", 50000),
            league_limit=params.get("league_limit", 50000),
            min_rows=params.get("min_rows", 500),
        )
    elif typ == "sync_audit":
        _reset_progress("sync_audit")
        _write_progress("sync_audit", status="running", message="Проверка синхронизации…")
        res = run_sync_audit(
            sample_limit=params.get("sample_limit", 5000),
            missing_preview=params.get("missing_preview", 20),
        )
        _write_progress("sync_audit", status="done", result=res, message="Готово")
    elif typ == "request_full_sync":
        request_full_sync_once()
    else:
        logger.warning("Unknown job type: %s", typ)


def run_daemon() -> None:
    """Демон: опрашивает очередь и выполняет задачи."""
    from app.services.ml_queue import dequeue

    logger.info("ML worker daemon started, polling queue every 5s")
    while True:
        try:
            job = dequeue()
            if job:
                logger.info("Processing job: %s", job.get("type"))
                try:
                    _execute_job(job)
                except Exception as e:
                    logger.exception("Job failed: %s", e)
                    _write_progress(job.get("type", "?"), status="done", error=str(e), message="Ошибка")
        except Exception as e:
            logger.exception("Daemon error: %s", e)
        time.sleep(5)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="op", required=True)
    sub.add_parser("run", help="Слушать очередь и выполнять задачи (в отдельном контейнере)")
    sync_p = sub.add_parser("sync")
    sync_p.add_argument("--limit", type=int, default=500)
    sync_p.add_argument("--days-back", type=int, default=0)
    sync_p.add_argument("--full", action="store_true")
    backfill_p = sub.add_parser("backfill")
    backfill_p.add_argument("--limit", type=int, default=50000)
    backfill_p.add_argument("--workers", type=int, default=0, help="0 = из ML_BACKFILL_WORKERS")
    retrain_p = sub.add_parser("retrain")
    retrain_p.add_argument("--min-rows", type=int, default=1000)
    league_p = sub.add_parser("league-performance")
    league_p.add_argument("--limit", type=int, default=10000)
    player_stats_p = sub.add_parser("player-stats")
    player_stats_p.add_argument("--limit", type=int, default=10000)
    rebuild_p = sub.add_parser("full-rebuild", help="Полный цикл: sync → odds backfill → player_stats → backfill → league_performance → retrain")
    rebuild_p.add_argument("--sync-limit", type=int, default=50000)
    rebuild_p.add_argument("--backfill-limit", type=int, default=100000)
    rebuild_p.add_argument("--player-stats-limit", type=int, default=50000)
    rebuild_p.add_argument("--league-limit", type=int, default=50000)
    rebuild_p.add_argument("--min-rows", type=int, default=500)
    audit_p = sub.add_parser("sync-audit", help="Ручная сверка main↔ML (покрытие + пропуски).")
    audit_p.add_argument("--sample-limit", type=int, default=5000)
    audit_p.add_argument("--missing-preview", type=int, default=20)
    sub.add_parser("request-full-sync", help="Поставить флаг полной синхронизации на следующий проход loop.")
    sub.add_parser(
        "sync-loop",
        help="Только цикл подтяжки main→ML каждые 10 мин (отдельный процесс, не зависит от API/воркеров).",
    )
    args = parser.parse_args()

    if args.op == "sync-loop":
        import asyncio
        from app.services.ml_sync_loop import ml_sync_loop
        logger.info("ML sync loop started (standalone process, interval=ML_SYNC_INTERVAL_SEC)")
        asyncio.run(ml_sync_loop())
        return

    if args.op == "run":
        run_daemon()
        return

    try:
        if args.op == "sync":
            _reset_progress("sync")
            _write_progress("sync", status="running", message="Старт…")
            run_sync(args.limit, args.days_back, args.full)
        elif args.op == "backfill":
            _reset_progress("backfill")
            _write_progress("backfill", status="running", message="Старт…")
            run_backfill(args.limit, workers=args.workers or None)
        elif args.op == "retrain":
            _reset_progress("retrain")
            _write_progress("retrain", status="running", message="Старт…")
            run_retrain(args.min_rows)
        elif args.op == "league-performance":
            _reset_progress("league_performance")
            _write_progress("league_performance", status="running", message="Старт…")
            run_league_performance(args.limit)
        elif args.op == "player-stats":
            _reset_progress("player_stats")
            _write_progress("player_stats", status="running", message="Старт…")
            run_player_stats(args.limit)
        elif args.op == "full-rebuild":
            _reset_progress("full_rebuild")
            _write_progress("full_rebuild", status="running", message="Старт…")
            run_full_rebuild(
                sync_limit=args.sync_limit,
                backfill_limit=args.backfill_limit,
                player_stats_limit=args.player_stats_limit,
                league_limit=args.league_limit,
                min_rows=args.min_rows,
            )
        elif args.op == "sync-audit":
            _reset_progress("sync_audit")
            _write_progress("sync_audit", status="running", message="Проверка синхронизации…")
            res = run_sync_audit(sample_limit=args.sample_limit, missing_preview=args.missing_preview)
            _write_progress("sync_audit", status="done", result=res, message="Готово")
        elif args.op == "request-full-sync":
            request_full_sync_once()
    except Exception as e:
        _write_progress(args.op, status="done", error=str(e), message="Ошибка")
        raise


if __name__ == "__main__":
    main()
