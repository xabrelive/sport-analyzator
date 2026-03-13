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
    data[op].update(kwargs)
    path.write_text(json.dumps(data, ensure_ascii=False))


def _reset_progress(op: str) -> None:
    _write_progress(op, status="idle", message="", current=0, total=0, result=None, error=None)


def run_backfill_odds(limit: int = 50000) -> int:
    """Дозаполняет ML odds из основной БД."""
    from app.ml.pipeline import backfill_odds_from_main_once
    return backfill_odds_from_main_once(limit=limit)


def run_sync(limit: int, days_back: int, full: bool) -> None:
    from app.ml.pipeline import sync_leagues_to_ml, sync_players_to_ml, sync_finished_to_ml_once, sync_full_main_to_ml
    from app.config import settings

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


def run_backfill(limit: int, workers: int = 6) -> None:
    from app.ml.pipeline import backfill_features_once
    from app.config import settings

    workers = workers or getattr(settings, "ml_backfill_workers", 6)

    def cb(current: int, total: int, message: str) -> None:
        _write_progress("backfill", status="running", current=current, total=total, message=message)
        if total and (current % 10000 == 0 or current == total):
            _echo(f"  Backfill: {message}")

    count = backfill_features_once(limit=limit, progress_callback=cb, workers=workers)
    _write_progress("backfill", status="done", result={"features_added": count}, message=f"Добавлено фичей: {count}")


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
    from app.ml.model_trainer import retrain_models_if_needed

    def cb(current: int, total: int, message: str) -> None:
        _write_progress("retrain", status="running", current=current, total=total, message=message)
        _echo(f"  [{current}/{total}] {message}")

    result = retrain_models_if_needed(min_rows=min_rows, version="v1", progress_callback=cb)
    if os.environ.get("ML_GPU_ONLY", "true").strip().lower() not in ("1", "true", "yes"):
        try:
            from app.ml.anomaly import fit_anomaly_model
            fit_anomaly_model(limit=10_000)
        except Exception:
            pass
    _write_progress("retrain", status="done", result=result, message="Готово")


def run_full_rebuild(
    sync_limit: int = 50000,
    backfill_limit: int = 100000,
    player_stats_limit: int = 50000,
    league_limit: int = 50000,
    min_rows: int = 500,
) -> dict:
    """Полный цикл: sync → backfill → player_stats → league_performance → retrain.
    Возвращает итоговую сводку."""
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
    elif typ == "retrain":
        _reset_progress("retrain")
        _write_progress("retrain", status="running", message="Старт…")
        run_retrain(params.get("min_rows", 100))
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
    retrain_p.add_argument("--min-rows", type=int, default=100)
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
    args = parser.parse_args()

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
    except Exception as e:
        _write_progress(args.op, status="done", error=str(e), message="Ошибка")
        raise


if __name__ == "__main__":
    main()
