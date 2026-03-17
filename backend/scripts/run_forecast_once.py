#!/usr/bin/env python3
"""Один проход расчёта ML и no-ML прогнозов. Выводит количество созданных прогнозов.

Запуск (из корня проекта, после docker compose up -d):
  docker compose exec backend python scripts/run_forecast_once.py
  # или пересоберите образ и запустите: docker compose up -d --build backend && docker compose exec backend python scripts/run_forecast_once.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.forecast_v2_pipeline import run_forecast_v2_once, run_no_ml_forecast_once


async def main() -> None:
    batch = 400
    print("Запуск одного прохода расчёта прогнозов (limit=%s)...\n" % batch)

    ml_count = await run_forecast_v2_once(limit=batch, channel="paid")
    print("ML (paid): создано прогнозов:", ml_count)

    no_ml_count = await run_no_ml_forecast_once(limit=batch, channel="no_ml")
    print("no-ML: создано прогнозов:", no_ml_count)

    print("\nИтого: ML=%s, no-ML=%s, всего=%s" % (ml_count, no_ml_count, ml_count + no_ml_count))


if __name__ == "__main__":
    asyncio.run(main())
