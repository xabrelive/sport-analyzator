#!/usr/bin/env python3
"""Проверка ответов BetsAPI: что приходит в каждом запросе.

Запуск из корня backend: python scripts/inspect_betsapi_responses.py
Требуется .env с BETSAPI_TOKEN и опционально BETSAPI_TABLE_TENNIS_SPORT_ID.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from app.config import settings

SPORT_ID = getattr(settings, "betsapi_table_tennis_sport_id", 92)
BASE_V3 = "https://api.b365api.com/v3"
BASE_V1 = "https://api.b365api.com/v1"
BASE_V2 = "https://api.b365api.com/v2"


def _describe(obj, max_items=2, depth=0):
    """Краткое описание структуры: тип, ключи, пример значений."""
    if depth > 4:
        return "..."
    if obj is None:
        return "null"
    if isinstance(obj, (bool, int, float)):
        return str(obj)
    if isinstance(obj, str):
        return f"str({len(obj)} chars)" if len(obj) > 40 else repr(obj)
    if isinstance(obj, list):
        if not obj:
            return "[]"
        head = obj[:max_items]
        return "[" + ", ".join(_describe(x, max_items=1, depth=depth + 1) for x in head) + (" ..." if len(obj) > max_items else "") + "]"
    if isinstance(obj, dict):
        keys = list(obj.keys())
        if not keys:
            return "{}"
        parts = []
        for k in keys[:10]:
            v = obj[k]
            parts.append(f"{k!r}: {_describe(v, max_items=1, depth=depth + 1)}")
        if len(keys) > 10:
            parts.append("...")
        return "{" + ", ".join(parts) + "}"
    return type(obj).__name__


async def main():
    if not settings.betsapi_token:
        print("BETSAPI_TOKEN не задан в .env")
        return
    token = settings.betsapi_token
    params = {"token": token, "sport_id": SPORT_ID}

    async with httpx.AsyncClient(timeout=30.0) as client:
        # ---- 1) GET /v3/events/upcoming ----
        print("=" * 60)
        print("1) GET /v3/events/upcoming")
        print("=" * 60)
        r = await client.get(f"{BASE_V3}/events/upcoming", params=params)
        print(f"Status: {r.status_code}")
        if not r.is_success:
            print(r.text[:500])
            return
        data = r.json()
        print("Верхний уровень:", list(data.keys()))
        results = data.get("results")
        if isinstance(results, list):
            print(f"results: list, len={len(results)}")
            if results:
                print("Первый элемент (ключи и типы):")
                first = results[0]
                for k, v in first.items():
                    print(f"  {k}: {type(v).__name__} = {_describe(v)}")
        else:
            print("results:", type(results).__name__, _describe(results))
        first_event_id = None
        if isinstance(results, list) and results and isinstance(results[0], dict):
            first_event_id = results[0].get("id")
        print()

        # ---- 2) GET /v3/events/inplay ----
        print("=" * 60)
        print("2) GET /v3/events/inplay")
        print("=" * 60)
        r2 = await client.get(f"{BASE_V3}/events/inplay", params=params)
        print(f"Status: {r2.status_code}")
        if r2.is_success:
            data2 = r2.json()
            print("Верхний уровень:", list(data2.keys()))
            res2 = data2.get("results")
            if isinstance(res2, list):
                print(f"results: list, len={len(res2)}")
                if res2:
                    print("Первый элемент (ключи и типы):")
                    for k, v in res2[0].items():
                        print(f"  {k}: {type(v).__name__} = {_describe(v)}")
                    # Статус матча в inplay: time_status (и опционально status)
                    print("  --- Статус матча (time_status): 0=линия, 1=лайв, 3/100=завершён ---")
                    for i, ev in enumerate(res2[:5]):
                        ts = ev.get("time_status")
                        st = ev.get("status")
                        print(f"  [{i}] time_status={ts!r}, status={st!r}")
                    if first_event_id is None:
                        first_event_id = res2[0].get("id")
            else:
                print("results:", _describe(res2))
        else:
            res2 = []
            print(r2.text[:300])
        odds_eid = None
        if isinstance(res2, list) and res2:
            odds_eid = res2[0].get("id")
        if not odds_eid:
            odds_eid = first_event_id or "1"
        print()

        # ---- 3) GET /v1/event/view?event_id=... ----
        eid = first_event_id or "1"
        print("=" * 60)
        print(f"3) GET /v1/event/view?event_id={eid}")
        print("=" * 60)
        r3 = await client.get(
            f"{BASE_V1}/event/view",
            params={"token": token, "event_id": str(eid)},
        )
        print(f"Status: {r3.status_code}")
        if r3.is_success:
            data3 = r3.json()
            print("Верхний уровень:", list(data3.keys()))
            res3 = data3.get("results")
            if isinstance(res3, dict):
                print(f"results: dict, ключи (event_id): {list(res3.keys())[:5]}")
                for eid_key, ev in list(res3.items())[:1]:
                    if isinstance(ev, dict):
                        print(f"  event_id={eid_key} (ключи): {list(ev.keys())}")
                        for k, v in list(ev.items())[:12]:
                            print(f"    {k}: {type(v).__name__} = {_describe(v)}")
            elif isinstance(res3, list):
                print(f"results: list, len={len(res3)}")
                if res3:
                    print("  первый элемент ключи:", list(res3[0].keys()))
            else:
                print("results:", _describe(res3))
        else:
            print(r3.text[:300])
        print()

        # ---- 4) GET /v2/event/odds?event_id=... ----
        print("=" * 60)
        print(f"4) GET /v2/event/odds?event_id={odds_eid}")
        print("=" * 60)
        r4 = await client.get(
            f"{BASE_V2}/event/odds",
            params={"token": token, "event_id": str(odds_eid)},
        )
        print(f"Status: {r4.status_code}")
        if r4.is_success:
            data4 = r4.json()
            print("Верхний уровень:", list(data4.keys()))
            res4 = data4.get("results")
            if isinstance(res4, dict):
                print(f"results: ключи = {list(res4.keys())}")
                odds_container = res4.get("odds")
                if odds_container is not None and isinstance(odds_container, dict):
                    print(f"  results['odds']: ключи (рынки) = {list(odds_container.keys())}")
                    for mk, mv in list(odds_container.items())[:5]:
                        print(f"    рынок {mk!r}: тип={type(mv).__name__}, len={len(mv) if isinstance(mv, list) else 'N/A'}")
                        if isinstance(mv, list) and mv:
                            first = mv[0]
                            print(f"      ключи снимка: {list(first.keys())}")
                            for line_key in ("handicap", "total", "line", "handicap_line", "total_line", "spread", "point"):
                                if line_key in first:
                                    print(f"      {line_key!r} = {first[line_key]!r}")
                            print(f"      пример: {_describe(first)}")
                stats = res4.get("stats")
                if stats is not None:
                    print(f"  results['stats']: {type(stats).__name__} {_describe(stats)}")
            else:
                print("results:", _describe(res4))
        else:
            print(r4.text[:300])

    print()
    print("Готово.")


if __name__ == "__main__":
    asyncio.run(main())
