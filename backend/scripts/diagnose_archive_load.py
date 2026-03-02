#!/usr/bin/env python3
"""Диагностика загрузки архива BetsAPI: почему не записались матчи за день.

Проверяет:
1. Применена ли миграция 011 (колонка last_processed_page) — без неё задача падает.
2. Что возвращает API GET /v3/events/ended за указанный день (страница 1).
3. Что в БД: прогресс по дню и количество матчей за этот день.

Запуск:
  cd backend && uv run python scripts/diagnose_archive_load.py [YYYYMMDD]
  docker compose exec backend uv run python scripts/diagnose_archive_load.py 20250101
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATABASE_URL", "postgresql://sport:sport@localhost:5432/sport_analyzator")

import httpx
from sqlalchemy import text

from app.config import settings

SPORT_ID = getattr(settings, "betsapi_table_tennis_sport_id", 92)
BASE_V3 = "https://api.b365api.com/v3"
DAY = (sys.argv[1] if len(sys.argv) > 1 else "20250101").strip()


def _sync_db_url():
    url = getattr(settings, "database_url", None) or os.environ.get("DATABASE_URL", "")
    if not url:
        return None
    if "+asyncpg" in url or "asyncpg" in url:
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


async def main() -> None:
    print(f"Диагностика архива за день: {DAY}")
    print("=" * 60)

    # 1) Миграция 011: есть ли колонка last_processed_page
    db_url = _sync_db_url()
    if not db_url:
        print("DATABASE_URL не задан. Пропуск проверки БД.")
    else:
        from sqlalchemy import create_engine
        engine = create_engine(db_url.replace("postgresql+asyncpg://", "postgresql://", 1), pool_pre_ping=True)
        with engine.connect() as conn:
            r = conn.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'betsapi_archive_progress' AND column_name = 'last_processed_page'
            """))
            has_column = r.fetchone() is not None
        if not has_column:
            print("ОШИБКА: В таблице betsapi_archive_progress нет колонки last_processed_page.")
            print("        Задача загрузки архива падает на первом же запросе к этой таблице.")
            print("        Выполните миграции: docker compose exec backend uv run alembic upgrade head")
            print()
        else:
            print("OK: миграция 011 применена (колонка last_processed_page есть).")
            with engine.connect() as conn:
                r = conn.execute(text("""
                    SELECT day_yyyymmdd, last_processed_page, completed_at IS NOT NULL AS completed
                    FROM betsapi_archive_progress
                    WHERE provider = 'betsapi' AND day_yyyymmdd = :day
                """), {"day": DAY})
                row = r.fetchone()
                if row:
                    print(f"      Прогресс по дню {DAY}: last_processed_page={row[1]}, completed={row[2]}.")
                else:
                    print(f"      В прогрессе записей по дню {DAY} нет.")
                # Матчи за этот день (по start_time дате)
                r2 = conn.execute(text("""
                    SELECT COUNT(*) FROM matches m
                    WHERE m.provider = 'betsapi'
                      AND m.start_time::date = to_date(:day, 'YYYYMMDD')
                """), {"day": DAY})
                cnt = r2.scalar() or 0
                print(f"      Матчей в БД за {DAY} (по start_time): {cnt}.")
        print()

    # 2) Ответ API за день
    if not settings.betsapi_token:
        print("BETSAPI_TOKEN не задан в .env. Пропуск запроса к API.")
        return
    print("Запрос к API: GET /v3/events/ended")
    print(f"  day={DAY}, sport_id={SPORT_ID}, page=1")
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            f"{BASE_V3}/events/ended",
            params={
                "token": settings.betsapi_token,
                "sport_id": SPORT_ID,
                "day": DAY,
                "page": 1,
            },
        )
    print(f"  HTTP status: {r.status_code}")
    if not r.is_success:
        print(f"  Тело: {r.text[:500]}")
        return
    data = r.json()
    success = data.get("success")
    results = data.get("results")
    if not success:
        print("  success=false в ответе. Проверьте токен и лимиты API.")
        print(f"  Ответ: {list(data.keys())}")
        return
    if not isinstance(results, list):
        print(f"  results не список: {type(results).__name__}")
        return
    print(f"  results: список из {len(results)} событий.")
    if results:
        first = results[0]
        print(f"  Первое событие: id={first.get('id')}, time={first.get('time')}, home={first.get('home', {}).get('name')}, away={first.get('away', {}).get('name')}.")
    else:
        print("  Пустой список — для этого дня у поставщика нет завершённых матчей (наст. теннис).")
        print("  Задача в этом случае помечает день как завершённый и переходит к следующему.")

    print()
    print("Итог:")
    if not db_url:
        print("  Задайте DATABASE_URL и перезапустите скрипт.")
    elif not has_column:
        print("  Примените миграции (alembic upgrade head), перезапустите воркер и снова запустите загрузку архива.")
    elif len(results) == 0:
        print("  API по этому дню возвращает 0 событий — записывать нечего. День будет помечен как completed.")
    else:
        print("  API отдаёт события. Если матчей в БД нет — смотрите логи Celery при выполнении задачи load_betsapi_history.")


if __name__ == "__main__":
    asyncio.run(main())
