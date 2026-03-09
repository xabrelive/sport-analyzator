#!/usr/bin/env python3
"""Проверка парсинга коэффициентов: ответ GET /v4/bet365/prematch → _parse_v4_prematch_odds → формат для normalizer.

Запуск: PYTHONPATH=backend python backend/scripts/verify_odds_parsing.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.collectors.betsapi_collector import _parse_v4_prematch_odds


# Формат v4: results.markets[] с name/id, outcomes[] с name/NA, price/OD
MOCK_V4_PREMATCH = {
    "results": {
        "markets": [
            {
                "name": "1_1",
                "outcomes": [
                    {"name": "1", "price": "1.85"},
                    {"name": "2", "price": "1.95"},
                ],
            },
            {
                "id": "92_1",
                "outcomes": [
                    {"NA": "home", "OD": "1.90"},
                    {"NA": "away", "OD": "1.92"},
                ],
            },
        ],
    },
}


def main() -> int:
    errors: list[str] = []

    out = _parse_v4_prematch_odds(MOCK_V4_PREMATCH)
    if not out or not isinstance(out, list):
        errors.append(f"Expected list of bookmakers, got {type(out).__name__!r} {out!r}")
    else:
        if len(out) != 1:
            errors.append(f"Expected 1 bookmaker (b365), got {len(out)}")
        bm = out[0]
        if bm.get("name") != "b365":
            errors.append(f"bookmaker name expected 'b365', got {bm.get('name')!r}")
        markets = bm.get("markets") or []
        if len(markets) < 2:
            errors.append(f"Expected at least 2 markets, got {len(markets)}")
        for m in markets:
            if not m.get("outcomes"):
                errors.append(f"market {m.get('name')!r}: outcomes empty")
            for o in m.get("outcomes") or []:
                if o.get("name") is None or o.get("price") is None:
                    errors.append(f"outcome missing name/price: {o!r}")

    empty = _parse_v4_prematch_odds({})
    if empty:
        errors.append(f"Empty response should return [], got {empty!r}")

    if errors:
        print("FAIL: v4 prematch odds parsing verification")
        for e in errors:
            print("  -", e)
        return 1
    print("OK: v4 bet365/prematch parsing (markets, outcomes, name/price)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
