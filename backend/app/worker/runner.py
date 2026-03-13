"""Запуск фоновых воркеров (BetsAPI, прогнозы, ML sync) без API.

Используется для масштабирования: API в отдельных контейнерах (быстро, много реплик),
воркеры — в одном контейнере (нагрузка на CPU/БД не влияет на ответы API).
"""
from __future__ import annotations

import asyncio
import logging
import sys

# Настройка логов до импорта app
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def main() -> None:
    from app.config import settings
    from app.db.session import init_db

    # Миграции и init_db — воркеры пишут в ту же БД
    from app.db.migrations import run_migrations

    run_migrations()
    await init_db()

    if not (settings.betsapi_token or "").strip():
        logger.warning("BetsAPI: betsapi_token пуст — BetsAPI-воркеры не запускаются.")
        if settings.ml_sync_interval_sec > 0:
            from app.services.ml_sync_loop import ml_sync_loop
            asyncio.create_task(ml_sync_loop())
            logger.info("ML sync loop запущен (без BetsAPI).")
        await asyncio.Event().wait()
        return

    from app.worker.table_tennis_line import start_pipeline

    await start_pipeline()
    logger.info("Фоновые воркеры запущены. Ожидание...")
    # Держим процесс живым
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
