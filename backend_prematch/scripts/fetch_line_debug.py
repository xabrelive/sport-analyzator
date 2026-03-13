#!/usr/bin/env python3
"""
Ручной запрос линии к BetsAPI и вывод результата (для отладки).
Запуск из корня backend: uv run python scripts/fetch_line_debug.py
Требуется BETSAPI_TOKEN в .env.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.services.collectors.betsapi_collector import BetsApiCollector


async def main() -> None:
    token = (settings.betsapi_token or "").strip()
    if not token:
        print("BETSAPI_TOKEN не задан в .env")
        return
    sid = getattr(settings, "betsapi_table_tennis_sport_id", 92)
    print(f"Запрос GET .../v3/events/upcoming sport_id={sid} ...")
    collector = BetsApiCollector()
    events = await collector.fetch(
        sport_id=sid,
        include_upcoming=True,
        include_inplay=False,
        include_ended=False,
        fetch_event_view=False,
        fetch_event_odds=False,
        rate_limit_seconds=1.0,
    )
    print(f"Получено событий: {len(events)}")
    upcoming = [e for e in events if isinstance(e, dict) and e.get("_source") == "upcoming"]
    print(f"Из них _source=upcoming: {len(upcoming)}")
    if not upcoming:
        if events:
            print("Пример первого события (ключи):", list(events[0].keys()) if isinstance(events[0], dict) else type(events[0]))
        return
    e0 = upcoming[0]
    print("\nПример первого upcoming:")
    print("  id:", e0.get("id"))
    print("  time:", e0.get("time"), "type:", type(e0.get("time")))
    print("  home:", e0.get("home"))
    print("  away:", e0.get("away"))
    print("  league:", e0.get("league"))


if __name__ == "__main__":
    asyncio.run(main())
