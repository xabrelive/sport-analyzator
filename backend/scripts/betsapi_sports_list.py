"""
Запрос актуального списка sport_id из BetsAPI (если API это поддерживает)
и проверка, что для настольного тенниса используется верный id.

Документация: https://betsapi.com/docs/ (отдельного эндпоинта "список спортов" в доке нет,
но некоторые версии API могут отдавать /sports).

Запуск из корня репозитория:
  PYTHONPATH=backend python3 backend/scripts/betsapi_sports_list.py
"""
from __future__ import annotations

import asyncio
import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql://sport:sport@localhost:5432/sport_analyzator")

import httpx

from app.config import settings

# По документации: настольный теннис = 92
TABLE_TENNIS_SPORT_ID_DOC = 92

BASE_URLS = ["https://api.b365api.com", "https://api.betsapi.com"]
PATHS = ["/v1/sports", "/v3/sports", "/sports"]


def find_table_tennis_id(data: dict) -> int | None:
    """В ответе ищем спорт с названием Table Tennis, возвращаем его id."""
    results = data.get("results") or data.get("sports") or data.get("data")
    if not isinstance(results, list):
        return None
    for item in results:
        if not isinstance(item, dict):
            continue
        name = (item.get("name") or item.get("title") or "").lower()
        sid = item.get("id") or item.get("sport_id")
        if "table tennis" in name or "table_tennis" in name:
            if sid is not None:
                return int(sid) if isinstance(sid, str) and sid.isdigit() else sid
    return None


async def main() -> None:
    token = settings.betsapi_token
    if not token:
        print("BETSAPI_TOKEN не задан в .env")
        sys.exit(1)

    params = {"token": token}
    async with httpx.AsyncClient(timeout=15.0) as client:
        for base in BASE_URLS:
            for path in PATHS:
                url = f"{base}{path}"
                try:
                    r = await client.get(url, params=params)
                    if r.status_code != 200:
                        continue
                    data = r.json()
                    if not data.get("success", True):
                        continue
                    tt_id = find_table_tennis_id(data)
                    if tt_id is not None:
                        print(f"Список спортов получен: {url}")
                        print(f"  Table Tennis sport_id = {tt_id}")
                        if tt_id != TABLE_TENNIS_SPORT_ID_DOC:
                            print(f"  Внимание: в конфиге используется {TABLE_TENNIS_SPORT_ID_DOC}, в API найден {tt_id}")
                        sys.exit(0)
                except Exception:
                    continue

    print("Эндпоинт со списком спортов не найден или не вернул Table Tennis.")
    print(f"Используем sport_id из документации: {TABLE_TENNIS_SPORT_ID_DOC} (Table Tennis)")
    print("Источник: https://betsapi.com/docs/")
    print(f"В .env задано: BETSAPI_TABLE_TENNIS_SPORT_ID={getattr(settings, 'betsapi_table_tennis_sport_id', 92)}")


if __name__ == "__main__":
    asyncio.run(main())
