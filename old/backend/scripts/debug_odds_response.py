#!/usr/bin/env python3
"""Печатает сырой ответ GET /v4/bet365/prematch для одного upcoming event (после event/view для bet365_id)."""
import asyncio
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

import httpx
from app.config import settings

BASE_V4 = "https://api.b365api.com/v4"
SPORT_ID = getattr(settings, "betsapi_table_tennis_sport_id", 92)


async def main():
    if not settings.betsapi_token:
        print("BETSAPI_TOKEN не задан")
        return
    token = settings.betsapi_token

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            f"https://api.b365api.com/v3/events/upcoming",
            params={"token": token, "sport_id": SPORT_ID},
        )
        if not r.is_success:
            print("upcoming failed:", r.status_code, r.text[:300])
            return
        data = r.json()
        results = data.get("results") or []
        if not results:
            print("Нет upcoming событий")
            return
        # Проверяем первые 5 событий: view.bet365_id и v4 prematch
        for idx, e in enumerate(results[:5]):
            eid = e.get("id")
            home = (e.get("home") or {}).get("name", "?")
            away = (e.get("away") or {}).get("name", "?")
            print(f"[{idx}] id={eid}  {home} vs {away}")
            rv = await client.get(
                "https://api.b365api.com/v1/event/view",
                params={"token": token, "event_id": eid},
            )
            if rv.is_success:
                view_data = rv.json()
                view_res = view_data.get("results") or {}
                first = next(iter(view_res.values()), None) if isinstance(view_res, dict) and view_res else (view_res[0] if isinstance(view_res, list) and view_res else None)
                bet365_id = first.get("bet365_id") if isinstance(first, dict) else None
                print(f"    view.bet365_id={bet365_id}")
                if bet365_id:
                    rp = await client.get(
                        f"{BASE_V4}/bet365/prematch",
                        params={"token": token, "FI": bet365_id},
                    )
                    if rp.is_success:
                        prematch = rp.json()
                        res = (prematch.get("results") or prematch) if isinstance(prematch, dict) else {}
                        markets = res.get("markets") if isinstance(res, dict) else None
                        n_markets = len(markets) if isinstance(markets, list) else 0
                        print(f"    v4/bet365/prematch: markets={n_markets}")
                    else:
                        print(f"    v4/bet365/prematch: HTTP {rp.status_code}")
            await asyncio.sleep(1.1)
        print()
        # Полный дамп первого события: view + v4 prematch
        e = results[0]
        eid = e.get("id")
        print("--- GET /v1/event/view (для bet365_id) ---")
        rv = await client.get(
            "https://api.b365api.com/v1/event/view",
            params={"token": token, "event_id": eid},
        )
        if rv.is_success:
            view_data = rv.json()
            view_res = (view_data.get("results") or {})
            if isinstance(view_res, dict):
                first = next(iter(view_res.values()), None) if view_res else None
            else:
                first = view_res[0] if isinstance(view_res, list) and view_res else None
            if isinstance(first, dict):
                bet365_id = first.get("bet365_id")
                print("bet365_id:", bet365_id)
                if bet365_id:
                    print()
                    print("--- GET /v4/bet365/prematch?FI=bet365_id ---")
                    rp = await client.get(
                        f"{BASE_V4}/bet365/prematch",
                        params={"token": token, "FI": bet365_id},
                    )
                    print("Status:", rp.status_code)
                    if rp.is_success:
                        prematch = rp.json()
                        print("Keys:", list(prematch.keys()) if isinstance(prematch, dict) else type(prematch))
                        print("Sample:", json.dumps(prematch, indent=2, default=str)[:2000])
                    else:
                        print(rp.text[:400])
            else:
                print("view results format:", type(view_res))
        else:
            print("view failed:", rv.status_code)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
