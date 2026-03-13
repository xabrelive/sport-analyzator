#!/usr/bin/env python3
"""Загружает завершённые матчи из архива BetsAPI в main DB.

Использование:
  python scripts/load_archive_to_main.py [--days 90]
  docker compose run --rm backend python scripts/load_archive_to_main.py --days 90
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# app доступен из корня backend (/app в контейнере)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    from app.db.migrations import run_migrations
    from app.db.session import init_db
    from app.services.betsapi_table_tennis import load_archive_to_main

    run_migrations()
    await init_db()

    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90, help="Дней назад для загрузки архива")
    parser.add_argument("--pages-per-day", type=int, default=10, help="Макс. страниц на день")
    args = parser.parse_args()

    res = await load_archive_to_main(days_back=args.days, max_pages_per_day=args.pages_per_day)
    logger.info("load_archive_to_main: %s", res)
    if res.get("inserted", 0) == 0 and res.get("updated", 0) == 0:
        logger.warning(
            "Архив пуст или BETSAPI_TOKEN не задан. "
            "Проверьте .env и что BetsAPI возвращает данные за последние %s дней.",
            args.days,
        )


if __name__ == "__main__":
    asyncio.run(main())
