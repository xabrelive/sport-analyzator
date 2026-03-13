"""
Запрос к BetsAPI: сколько событий сейчас в лайве (inplay) по настольному теннису.
Требует BETSAPI_TOKEN в .env или в окружении.

Запуск (из каталога backend, с venv/uv):
  uv run python scripts/count_betsapi_inplay.py
  docker compose exec backend uv run python scripts/count_betsapi_inplay.py

Через curl (подставьте TOKEN и sport_id=92 при необходимости):
  curl -s "https://api.b365api.com/v3/events/inplay?token=TOKEN&sport_id=92" | jq '.results | length'
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Загружаем .env из корня репозитория
_root = Path(__file__).resolve().parent.parent.parent
_env = _root / ".env"
if _env.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env)
    except ImportError:
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "postgresql://localhost/sport_analyzator")

import httpx

from app.config import settings

BASE = "https://api.b365api.com/v3"
SPORT_ID = getattr(settings, "betsapi_table_tennis_sport_id", 92)


async def main() -> None:
    token = settings.betsapi_token
    if not token:
        print("BETSAPI_TOKEN не задан в .env")
        sys.exit(1)
    params = {"sport_id": SPORT_ID, "token": token}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{BASE}/events/inplay", params=params)
    if not r.is_success:
        print(f"HTTP {r.status_code}: {r.text[:200]}")
        sys.exit(1)
    data = r.json()
    if not data.get("success"):
        print("success=false:", data.get("error") or data)
        sys.exit(1)
    results = data.get("results") or []
    print(f"Inplay (sport_id={SPORT_ID}): {len(results)} событий")
    if results:
        for i, e in enumerate(results[:5]):
            eid = e.get("id")
            ss = e.get("ss") or e.get("scores") or ""
            time_status = e.get("time_status", "")
            print(f"  [{i+1}] id={eid} time_status={time_status} ss={ss}")
        if len(results) > 5:
            print(f"  ... и ещё {len(results) - 5}")


if __name__ == "__main__":
    asyncio.run(main())
