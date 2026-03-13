"""ML sync loop: синхронизация main→ML, backfill, дообучение. ML берёт все данные только из основной БД."""
import asyncio
import logging

from sqlalchemy import text

from app.config import settings
from app.ml.pipeline import (
    sync_finished_to_ml_once,
    sync_full_main_to_ml,
    sync_leagues_to_ml,
    sync_players_to_ml,
    backfill_features_once,
    backfill_duration_from_main_once,
    backfill_odds_from_main_once,
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

logger = logging.getLogger(__name__)

_did_initial_full_sync = False


def _ml_matches_count() -> int:
    try:
        s = get_ml_session()
        r = s.execute(text("SELECT COUNT(*) FROM matches")).scalar_one()
        s.close()
        return int(r or 0)
    except Exception:
        return 0


async def ml_sync_loop() -> None:
    """Синхронизирует main→ML, заполняет фичи/odds из main, дообучает модели. BetsAPI не используется."""
    global _did_initial_full_sync
    interval = max(300, settings.ml_sync_interval_sec)  # мин. 5 мин, типично 600 (10 мин)
    logger.info("ML sync loop: автодогрузка main→ML каждые %s сек", interval)
    min_new_for_retrain = max(50, settings.ml_retrain_min_new_matches)
    days_back_raw = getattr(settings, "ml_sync_days_back", 3650)
    days_back: int | None = 0 if days_back_raw == 0 else max(365, days_back_raw)
    batch_size = max(500, getattr(settings, "ml_sync_batch_size", 3000))

    while True:
        try:
            total_synced = 0
            need_full_sync = not _did_initial_full_sync or _ml_matches_count() < 100

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
                _did_initial_full_sync = True
                if total_synced > 0:
                    logger.info("ML full sync: total synced=%s", total_synced)
            else:
                res = await sync_finished_to_ml_once(limit=batch_size, days_back=90)
                total_synced = res.get("synced", 0)
                if total_synced > 0:
                    logger.info("ML sync: synced=%s skipped=%s", total_synced, res.get("skipped"))

            # Всегда заполняем ML-таблицы (даже без новых матчей — догоняем пропущенное)
            def _safe(name: str, fn, *args, **kwargs):
                try:
                    return fn(*args, **kwargs) or 0
                except Exception as e:
                    logger.debug("ML %s: %s", name, e)
                    return 0

            try:
                dur_updated = await backfill_duration_from_main_once(limit=5000)
                if dur_updated and dur_updated > 0:
                    logger.info("ML duration backfill: %s matches", dur_updated)
            except Exception as e:
                logger.debug("ML duration backfill: %s", e)
            try:
                odds_updated = await asyncio.to_thread(backfill_odds_from_main_once, 50000)
                if odds_updated and odds_updated > 0:
                    logger.info("ML odds backfill from main: %s rows", odds_updated)
            except Exception as e:
                logger.debug("ML odds backfill: %s", e)
            features_added = _safe(
                "features",
                lambda: backfill_features_once(
                    limit=20000,
                    workers=getattr(settings, "ml_backfill_workers", 6),
                ),
            )
            if features_added > 0:
                logger.info("ML features backfill: %s matches", features_added)
            suspicious_count = _safe("suspicious", check_suspicious_matches_once, 2000)
            if suspicious_count > 0:
                logger.info("ML suspicious matches: %s flagged", suspicious_count)
            daily_stats = _safe("player_daily_stats", backfill_player_daily_stats_once, 5000)
            if daily_stats > 0:
                logger.info("ML player_daily_stats: %s rows", daily_stats)
            style_count = _safe("player_style", backfill_player_style_once, 2000)
            if style_count > 0:
                logger.info("ML player_style: %s players", style_count)
            elo_hist = _safe("player_elo_history", backfill_player_elo_history_once, 10000)
            if elo_hist > 0:
                logger.info("ML player_elo_history: %s rows", elo_hist)
            leagues_updated = _safe("league_performance", update_league_performance_once, 10000)
            if leagues_updated > 0:
                logger.info("ML league performance: %s leagues updated", leagues_updated)

            if total_synced >= min_new_for_retrain or features_added >= min_new_for_retrain:
                from app.ml.anomaly import fit_anomaly_model
                try:
                    fit_anomaly_model(limit=10_000)
                except Exception:
                    pass
                retrain_res = retrain_models_if_needed(
                    min_rows=min_new_for_retrain,
                    version="v1",
                )
                if retrain_res.get("trained"):
                    logger.info(
                        "ML retrain: rows=%s path=%s",
                        retrain_res.get("rows"),
                        retrain_res.get("path"),
                    )
        except Exception:
            logger.exception("ML sync failed")
        await asyncio.sleep(interval)
