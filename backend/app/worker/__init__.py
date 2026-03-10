"""Воркеры и очереди для фоновой обработки данных.

Использование:
- Очередь: app.worker.queue.put_batch(events) — положить батч в очередь.
- Запуск воркеров: app.worker.table_tennis_line.start_pipeline() — старт N воркеров и продюсера.
Масштабирование: увеличьте line_worker_count в .env или замените бэкенд очереди на Redis
и запускайте воркеры отдельным процессом/контейнером.
"""
from app.worker.queue import put_batch as line_put_batch

__all__ = ["line_put_batch"]
