"""Запуск воркеров линии настольного тенниса.

Стартует N воркеров (читают из очереди, сохраняют в БД) и одного продюсера
(опрашивает BetsAPI и кладёт батчи в очередь).
Масштабирование: увеличьте line_worker_count в .env или запускайте воркеры
отдельным процессом (будущая поддержка Redis-очереди).
"""
from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.worker.queue import get_line_queue, run_worker_loop

logger = logging.getLogger(__name__)


async def start_pipeline() -> None:
    """Запустить продюсер линии и воркеров обработки очереди."""
    from app.services.betsapi_table_tennis import (
        save_table_tennis_line_to_db,
        table_tennis_line_loop,
        table_tennis_odds_loop,
        table_tennis_live_loop,
        table_tennis_results_loop,
        table_tennis_forecast_loop,
    )

    num_workers = max(1, settings.line_worker_count)
    get_line_queue()  # инициализировать очередь до старта воркеров

    for i in range(num_workers):
        asyncio.create_task(run_worker_loop(i + 1, save_table_tennis_line_to_db))
    asyncio.create_task(table_tennis_line_loop())
    asyncio.create_task(table_tennis_odds_loop())
    asyncio.create_task(table_tennis_live_loop())
    asyncio.create_task(table_tennis_results_loop())
    asyncio.create_task(table_tennis_forecast_loop())

    logger.info(
        "Table tennis line pipeline started: %s workers, queue_maxsize=%s",
        num_workers,
        settings.line_queue_maxsize,
    )
