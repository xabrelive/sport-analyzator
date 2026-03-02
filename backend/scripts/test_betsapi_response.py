"""
Проверка ответа BetsAPI: какие поля приходят в событиях (upcoming, inplay, ended).
Запуск (из корня репозитория, чтобы подхватился .env):
  PYTHONPATH=backend python3 backend/scripts/test_betsapi_response.py

По выводу сверяем: что мы уже храним (Match, League, Player, scores, result, odds)
и чего не хватает — дописываем в normalizer и при необходимости в модели.
"""
from __future__ import annotations

import asyncio
import json
import os

os.environ.setdefault("DATABASE_URL", "postgresql://sport:sport@localhost:11002/sport_analyzator")

import httpx

from app.config import settings


BETSAPI_BASE = "https://api.b365api.com/v3"

# Пример одного события по документации (если API вернёт 403 — показываем этот формат)
EXAMPLE_UPCOMING_EVENT = {
    "id": "12345678",
    "sport_id": "92",
    "time": "1730123456",
    "time_status": "0",
    "league": {"id": "1234", "name": "WTT Feeder", "cc": "WTT"},
    "home": {"id": "1001", "name": "Player A"},
    "away": {"id": "1002", "name": "Player B"},
    "ss": None,
    "score": None,
}
EXAMPLE_INPLAY_EVENT = {
    "id": "12345679",
    "ss": "2-1 (11:9 9:11 11:7)",
    "score": "2-1",
    "league": {"id": "1234", "name": "WTT Feeder"},
    "home": {"id": "1001", "name": "Player A"},
    "away": {"id": "1002", "name": "Player B"},
}


async def main() -> None:
    token = settings.betsapi_token
    if not token:
        print("BETSAPI_TOKEN не задан. Добавьте в .env: BETSAPI_TOKEN=ваш_токен")
        print("\n--- Пример формата ответа (upcoming):")
        print(json.dumps({"success": 1, "results": [EXAMPLE_UPCOMING_EVENT]}, indent=2, ensure_ascii=False))
        return
    sport_id = settings.betsapi_table_tennis_sport_id
    params = {"sport_id": sport_id, "token": token}

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Upcoming
        r = await client.get(f"{BETSAPI_BASE}/events/upcoming", params=params)
        print("=== UPCOMING response status:", r.status_code)
        if not r.is_success:
            print(r.text[:1000])
            print("\n--- Если 403: включите настольный теннис в кабинете https://betsapi.com/mm/pricing_table")
            print("\n--- Пример одного события (upcoming) по документации:")
            print(json.dumps(EXAMPLE_UPCOMING_EVENT, indent=2, ensure_ascii=False))
            print("\n--- Пример события в лайве (inplay, с полем ss — счёт по сетам):")
            print(json.dumps(EXAMPLE_INPLAY_EVENT, indent=2, ensure_ascii=False))
            return
        data = r.json()
        print("success:", data.get("success"))
        print("pagination:", data.get("pagination"))
        results = data.get("results") or []
        print("results count:", len(results))
        if results:
            print("\n--- Первое событие из ответа (пример одного ответа на запрос):")
            first = results[0]
            sample = {}
            for k, v in first.items():
                if k in ("odds", "bookmakers") and isinstance(v, (list, dict)):
                    sample[k] = f"<{type(v).__name__} len={len(v)}>"
                else:
                    sample[k] = v
            print(json.dumps(sample, indent=2, default=str, ensure_ascii=False))

        # Inplay
        r2 = await client.get(f"{BETSAPI_BASE}/events/inplay", params=params)
        print("\n=== INPLAY response status:", r2.status_code)
        if r2.is_success:
            data2 = r2.json()
            results2 = data2.get("results") or []
            print("results count:", len(results2))
            if results2:
                print("\n--- Первое inplay-событие:")
                print(json.dumps(results2[0], indent=2, default=str, ensure_ascii=False)[:2000])
        else:
            print(r2.text[:500])

        # Ended (optional)
        r3 = await client.get(f"{BETSAPI_BASE}/events/ended", params={**params, "page": 1})
        print("\n=== ENDED (page=1) status:", r3.status_code)
        if r3.is_success:
            data3 = r3.json()
            results3 = data3.get("results") or []
            print("results count:", len(results3))
            if results3:
                first3 = results3[0]
                print("First ENDED keys:", list(first3.keys()))
                for key in ("ss", "score", "time", "home", "away", "league"):
                    if key in first3:
                        print(f"  {key}: {first3[key]!r}")

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
