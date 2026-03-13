#!/usr/bin/env python3
"""Один полный цикл линии: только upcoming -> normalize (без view/odds для скорости). Запуск: docker compose run --rm backend uv run python -m scripts.run_line_once"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.db.session import create_worker_engine_and_session
from app.services.collectors.betsapi_collector import BetsApiCollector
from app.services.normalizer import Normalizer


async def main():
    if not (settings.betsapi_token or "").strip():
        print("BETSAPI_TOKEN не задан")
        return
    engine, session_maker = create_worker_engine_and_session()
    try:
        collector = BetsApiCollector()
        # Только список upcoming, без view и odds — быстро, достаточно для появления матчей в линии
        events = await collector.fetch(
            sport_id=getattr(settings, "betsapi_table_tennis_sport_id", 92),
            include_upcoming=True,
            include_inplay=False,
            include_ended=False,
            fetch_event_view=False,
            fetch_event_odds=False,
            rate_limit_seconds=1.0,
        )
        print(f"API вернул событий: {len(events)}")
        upcoming = [e for e in events if isinstance(e, dict) and e.get("_source") == "upcoming"]
        if not upcoming:
            print("Нет upcoming, выход.")
            return
        async with session_maker() as session:
            norm = Normalizer(session)
            try:
                match_ids = await norm.normalize_betsapi_response(events, current_event_ids=None)
                await session.commit()
                print(f"Сохранено матчей: {len(match_ids)}")
                if match_ids:
                    print("Пример id:", str(match_ids[0]))
            except Exception as e:
                await session.rollback()
                print(f"Ошибка нормализации: {e}")
                import traceback
                traceback.print_exc()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
