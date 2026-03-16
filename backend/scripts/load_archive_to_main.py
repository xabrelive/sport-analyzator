#!/usr/bin/env python3
"""Загружает завершённые матчи из архива BetsAPI в main DB.

Использование:
  python scripts/load_archive_to_main.py [--days 90]
  python scripts/load_archive_to_main.py --date-from 20250313 --date-to 20250314
  docker compose run --rm backend python scripts/load_archive_to_main.py --date-from 20250313 --date-to 20250314
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

# app доступен из корня backend (/app в контейнере)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _parse_date(s: str) -> date:
    d = date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    return d


async def main() -> None:
    from app.db.migrations import run_migrations
    from app.db.session import init_db
    from app.services.betsapi_table_tennis import load_archive_to_main

    run_migrations()
    await init_db()

    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=None, help="Дней назад для загрузки архива")
    parser.add_argument("--pages-per-day", type=int, default=10, help="Макс. страниц на день")
    parser.add_argument("--date-from", type=str, default=None, help="Начало диапазона YYYYMMDD (напр. 20250313)")
    parser.add_argument("--date-to", type=str, default=None, help="Конец диапазона YYYYMMDD (напр. 20250314)")
    args = parser.parse_args()

    date_from = _parse_date(args.date_from) if args.date_from else None
    date_to = _parse_date(args.date_to) if args.date_to else None
    days = args.days if args.days is not None else 90
    if date_from and date_to:
        logger.info("Загрузка архива за %s — %s", date_from, date_to)
        res = await load_archive_to_main(
            date_from=date_from,
            date_to=date_to,
            max_pages_per_day=args.pages_per_day,
        )
    else:
        res = await load_archive_to_main(days_back=days, max_pages_per_day=args.pages_per_day)
    logger.info("load_archive_to_main: %s", res)
    if res.get("inserted", 0) == 0 and res.get("updated", 0) == 0:
        range_desc = f"{date_from} — {date_to}" if (date_from and date_to) else f"последние {days} дней"
        logger.warning(
            "Архив пуст или BETSAPI_TOKEN не задан. "
            "Проверьте .env и что BetsAPI возвращает данные за %s.",
            range_desc,
        )


if __name__ == "__main__":
    asyncio.run(main())
