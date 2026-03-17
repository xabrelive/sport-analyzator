#!/usr/bin/env python3
"""Ручной перезапуск проверки результатов для cancelled-матчей с прогнозами.

Запуск (из корня проекта, когда docker-compose уже поднят):

  docker compose exec backend python scripts/revalidate_cancelled_forecasts.py

Скрипт:
- сначала пытается починить cancelled матчи, у которых уже есть счёт по сетам (repair_cancelled_with_scores_once)
- затем запускает revalidate_cancelled_forecast_events_once, который ходит в BetsAPI (event + архив),
  обновляет статус/счёт матчей и сразу пересчитывает исход прогнозов.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.betsapi_table_tennis import (  # noqa: E402
    repair_cancelled_with_scores_once,
    revalidate_cancelled_forecast_events_once,
)


async def main() -> None:
    print("=== Repair cancelled with scores (by sets) ===")
    fixed = await repair_cancelled_with_scores_once(limit=500)
    print(f"fixed_by_sets = {fixed}")

    print("\n=== Revalidate cancelled forecast events via BetsAPI ===")
    res = await revalidate_cancelled_forecast_events_once(limit=500)
    print(f"result = {res}")


if __name__ == "__main__":
    asyncio.run(main())

