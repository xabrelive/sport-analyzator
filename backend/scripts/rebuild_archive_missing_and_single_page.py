#!/usr/bin/env python3
"""Пересборка архива за недостающие дни и дни с одной страницей (last_processed_page=1).

1. Запрашивает статус загрузки за диапазон day_from..day_to.
2. Сбрасывает прогресс по дням с одной страницей (чтобы перезапросить их).
3. Запускает задачу загрузки архива для того же диапазона (подхватятся и not_completed, и сброшенные дни).

Запуск (backend должен быть доступен по API_BASE):
  cd backend && uv run python scripts/rebuild_archive_missing_and_single_page.py [day_from] [day_to]
  docker compose exec backend uv run python scripts/rebuild_archive_missing_and_single_page.py 20200101 20251231

Переменные окружения:
  API_BASE — базовый URL API (по умолчанию http://localhost:11001)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

Path(__file__).resolve().parent.parent
API_BASE = os.environ.get("API_BASE", "http://localhost:11001").rstrip("/")


def main() -> None:
    day_from = (sys.argv[1] if len(sys.argv) > 1 else "20160901").strip()
    day_to = (sys.argv[2] if len(sys.argv) > 2 else "").strip()
    if not day_to:
        from datetime import datetime, timezone
        day_to = datetime.now(timezone.utc).strftime("%Y%m%d")

    print(f"Диапазон: {day_from} .. {day_to}")
    print("1. Запрос статуса загрузки архива...")
    with httpx.Client(timeout=30.0) as client:
        r = client.get(
            f"{API_BASE}/api/v1/matches/load-history/status",
            params={"day_from": day_from, "day_to": day_to},
        )
        r.raise_for_status()
        data = r.json()
    not_completed = data.get("not_completed") or []
    single_page_days = data.get("single_page_days") or []
    print(f"   Недостающие дни (not_completed): {len(not_completed)}")
    print(f"   Дни с одной страницей (single_page_days): {len(single_page_days)}")
    if single_page_days:
        print(f"   Примеры одностраничных: {single_page_days[:5]}{'...' if len(single_page_days) > 5 else ''}")

    if not single_page_days and not not_completed:
        print("Нет недостающих дней и нет дней с одной страницей в диапазоне. Выход.")
        return

    if single_page_days:
        print("2. Сброс прогресса по одностраничным дням...")
        with httpx.Client(timeout=30.0) as client:
            r = client.post(
                f"{API_BASE}/api/v1/matches/load-history/reset-progress",
                json={
                    "day_from": day_from,
                    "day_to": day_to,
                    "reset_single_page_only": True,
                },
            )
            r.raise_for_status()
            res = r.json()
        reset_days = res.get("reset_days") or []
        print(f"   Сброшено дней: {len(reset_days)}")
    else:
        print("2. Одностраничных дней нет — сброс не выполняем.")

    print("3. Запуск загрузки архива (POST load-history)...")
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            f"{API_BASE}/api/v1/matches/load-history",
            json={
                "day_from": day_from,
                "day_to": day_to,
                "delay_seconds": 1.0,
                "resume_from_progress": True,
            },
        )
        r.raise_for_status()
        task = r.json()
    print(f"   task_id: {task.get('task_id', '')}")
    print(f"   {task.get('message', '')}")
    print("Готово. Следите за логами Celery (очередь history).")


if __name__ == "__main__":
    main()
