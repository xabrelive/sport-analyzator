#!/usr/bin/env python3
"""Печатает сырой ответ GET /v2/event/odds и GET /v4/bet365/prematch для одного upcoming event."""
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

BASE_V2 = "https://api.b365api.com/v2"
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
        # Проверяем первые 5 событий: v2 odds и view.bet365_id
        for idx, e in enumerate(results[:5]):
            eid = e.get("id")
            home = (e.get("home") or {}).get("name", "?")
            away = (e.get("away") or {}).get("name", "?")
            print(f"[{idx}] id={eid}  {home} vs {away}")
            ro = await client.get(
                f"{BASE_V2}/event/odds",
                params={"token": token, "event_id": eid, "odds_market": "1,2,3"},
            )
            if ro.is_success:
                data2 = ro.json()
                res = data2.get("results") or {}
                odds = res.get("odds") if isinstance(res, dict) else None
                n_markets = len(odds) if isinstance(odds, dict) else 0
                print(f"    v2/event/odds: markets={n_markets}")
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
            await asyncio.sleep(1.1)
        print()
        # Полный дамп первого события
        e = results[0]
        eid = e.get("id")
        print("--- Полный ответ v2/event/odds для первого ---")
        ro = await client.get(
            f"{BASE_V2}/event/odds",
            params={"token": token, "event_id": eid, "odds_market": "1,2,3"},
        )
        print("Status:", ro.status_code)
        if ro.is_success:
            data2 = ro.json()
            print("Keys:", list(data2.keys()))
            res = data2.get("results")
            if res is not None:
                print("results type:", type(res).__name__)
                if isinstance(res, dict):
                    print("results keys:", list(res.keys())[:15])
                    odds = res.get("odds")
                    if odds is not None:
                        print("results.odds keys (markets):", list(odds.keys()))
                        for mk, mv in list(odds.items())[:2]:
                            print(f"  {mk}: type={type(mv).__name__}, len={len(mv) if isinstance(mv, list) else 'N/A'}")
                    else:
                        first_k = next(iter(res), None)
                        if first_k and first_k not in ("stats", "odds"):
                            block = res.get(first_k)
                            if isinstance(block, dict):
                                print(f"results['{first_k}'] keys:", list(block.keys()))
                                ob = block.get("odds")
                                if ob is not None:
                                    print(f"  odds keys: {list(ob.keys())}")
            print("Full response (truncated):")
            print(json.dumps(data2, indent=2, default=str)[:2500])
        else:
            print(ro.text[:500])
        print()

        # event/view чтобы получить bet365_id
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
