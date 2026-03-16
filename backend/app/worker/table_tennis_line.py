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
    )
    from app.services.forecast_v2_pipeline import (
        early_scan_loop,
        forecast_v2_loop,
        no_ml_forecast_loop,
        result_priority_loop,
        kpi_guard_loop,
    )
    from app.services.notification_dispatcher import forecast_notifications_loop
    from app.services.subscription_expiry_notifier import subscription_expiry_loop
    from app.services.telegram_channel_dispatcher import telegram_channel_dispatcher_loop
    from app.services.vip_channel_access import vip_channel_access_loop
    from app.services.ml_sync_loop import ml_sync_loop

    num_workers = max(1, settings.line_worker_count)
    get_line_queue()  # инициализировать очередь до старта воркеров

    for i in range(num_workers):
        asyncio.create_task(run_worker_loop(i + 1, save_table_tennis_line_to_db))
    asyncio.create_task(table_tennis_line_loop())
    asyncio.create_task(table_tennis_odds_loop())
    asyncio.create_task(table_tennis_live_loop())
    asyncio.create_task(table_tennis_results_loop())
    asyncio.create_task(early_scan_loop())
    asyncio.create_task(forecast_v2_loop())
    asyncio.create_task(no_ml_forecast_loop())
    asyncio.create_task(result_priority_loop())
    asyncio.create_task(kpi_guard_loop())
    asyncio.create_task(forecast_notifications_loop())
    asyncio.create_task(subscription_expiry_loop())
    asyncio.create_task(telegram_channel_dispatcher_loop())
    asyncio.create_task(vip_channel_access_loop())
    # Подтяжка ML: в том же процессе или отдельным сервисом (ml_sync). При ml_sync_standalone=true цикл не запускаем здесь.
    if (
        settings.ml_sync_interval_sec > 0
        and not getattr(settings, "ml_sync_standalone", False)
    ):
        asyncio.create_task(ml_sync_loop())

    logger.info(
        "Table tennis line pipeline started: %s workers, queue_maxsize=%s",
        num_workers,
        settings.line_queue_maxsize,
    )
