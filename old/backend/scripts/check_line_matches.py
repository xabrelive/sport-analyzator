#!/usr/bin/env python3
"""
Проверка, почему на странице «Линия» нет матчей.
Запуск: из корня backend: python -m scripts.check_line_matches
или: uv run python scripts/check_line_matches.py
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

# Добавляем корень backend в path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.config import settings
from app.models import Match, MatchStatus


async def main() -> None:
    print("=== Диагностика: матчи в линии ===\n")

    # 1) Конфиг
    token_set = bool((settings.betsapi_token or "").strip())
    print(f"1) BETSAPI_TOKEN задан: {token_set}")
    if not token_set:
        print("   → Задайте BETSAPI_TOKEN в .env (линия подтягивается из BetsAPI).\n")

    collectors = getattr(settings, "enable_scheduled_collectors", False)
    print(f"2) ENABLE_SCHEDULED_COLLECTORS: {collectors}")
    if not collectors:
        print("   → Включите ENABLE_SCHEDULED_COLLECTORS=true, иначе задача линии не запускается по расписанию.\n")

    # 2) БД
    engine = create_async_engine(settings.async_database_url, pool_pre_ping=True)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=15)

    async with async_session() as session:
        # Всего матчей в статусе линии
        q1 = select(Match).where(
            Match.status.in_([MatchStatus.SCHEDULED.value, MatchStatus.PENDING_ODDS.value]),
        )
        r1 = await session.execute(q1)
        all_line_status = list(r1.scalars().all())
        print(f"3) В БД матчей со статусом scheduled/pending_odds: {len(all_line_status)}")

        # С началом в «будущем» (как в API overview)
        q2 = select(Match).where(
            Match.status.in_([MatchStatus.SCHEDULED.value, MatchStatus.PENDING_ODDS.value]),
            Match.start_time >= cutoff,
        )
        r2 = await session.execute(q2)
        upcoming = list(r2.scalars().all())
        print(f"4) Из них start_time >= (now - 15 мин) — такие отдаёт API «линия»: {len(upcoming)}")

        if all_line_status and not upcoming:
            sample = all_line_status[0]
            print(f"   Пример: start_time = {sample.start_time} (сейчас {now} UTC).")
            print("   → Все матчи в линии начинаются раньше чем (now - 15 мин) — проверьте часовой пояс и время в БД.")

        # По провайдеру
        q3 = await session.execute(
            text(
                "SELECT provider, status, COUNT(*) FROM matches "
                "WHERE status IN ('scheduled','pending_odds') AND start_time >= :cutoff "
                "GROUP BY provider, status"
            ),
            {"cutoff": cutoff},
        )
        rows = q3.fetchall()
        print("5) По провайдерам (scheduled/pending_odds, start_time >= cutoff):")
        for provider, status, cnt in rows:
            print(f"   {provider} / {status}: {cnt}")

    await engine.dispose()

    if not upcoming and token_set and collectors:
        print("\n→ Задача линии должна запускаться по расписанию. Проверьте логи Celery (очередь betsapi_collect).")
    if not upcoming:
        print("\n→ Чтобы подтянуть линию вручную (в Docker через uv run):")
        print("   docker compose run --rm celery_betsapi_worker uv run celery -A app.worker.celery_app call app.worker.tasks.collect_betsapi.fetch_betsapi_table_tennis_task --kwargs='{\"mode\": \"line\"}'")


if __name__ == "__main__":
    asyncio.run(main())
