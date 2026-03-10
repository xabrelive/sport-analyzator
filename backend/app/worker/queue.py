"""Сервис очередей для фоновой обработки.

Абстракция: put_batch(batch) и run_worker_loop(worker_id, handler).
Реализация по умолчанию — in-memory asyncio.Queue; при росте нагрузки
можно заменить на Redis/RabbitMQ и масштабировать воркеры отдельными процессами.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# Очередь батчей (один элемент = список событий для сохранения в БД)
_line_queue: asyncio.Queue[list[dict[str, Any]]] | None = None


def get_line_queue() -> asyncio.Queue[list[dict[str, Any]]]:
    """Возвращает очередь линии (ленивая инициализация)."""
    global _line_queue
    if _line_queue is None:
        maxsize = max(8, settings.line_queue_maxsize)
        _line_queue = asyncio.Queue(maxsize=maxsize)
        logger.info("Line queue initialized (maxsize=%s)", maxsize)
    return _line_queue


async def put_batch(batch: list[dict[str, Any]]) -> None:
    """Положить батч событий в очередь на обработку воркерами."""
    if not batch:
        return
    queue = get_line_queue()
    await queue.put(batch)


Handler = Callable[[list[dict[str, Any]]], Awaitable[None]]


async def run_worker_loop(
    worker_id: int,
    handler: Handler,
    *,
    queue: asyncio.Queue[list[dict[str, Any]]] | None = None,
) -> None:
    """Бесконечный цикл воркера: забирает батчи из очереди и передаёт в handler."""
    q = queue or get_line_queue()
    logger.info("Line worker %s started", worker_id)
    while True:
        batch = await q.get()
        try:
            await handler(batch)
        except Exception as e:  # noqa: BLE001
            logger.exception("Line worker %s error: %s", worker_id, e)
        finally:
            q.task_done()
