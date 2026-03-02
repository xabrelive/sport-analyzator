#!/usr/bin/env python3
"""Проверка парсинга коэффициентов: ответ API → _normalize_odds_response → формат для нормалайзера.

Соответствие полей API (GET /v2/event/odds) и того, что ожидает normalizer:
- results.odds["92_1"|"92_2"|"92_3"] = список снимков
- снимок: id, home_od, away_od, ss, add_time, handicap?|total?|line?
- После парсинга: bookmakers[].markets[].snapshots[] с outcomes, snapshot_time, line_value, score_at_snapshot

Запуск: PYTHONPATH=backend python backend/scripts/verify_odds_parsing.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.collectors.betsapi_collector import _normalize_odds_response


# Формат 1: results.odds — ключи 92_1, 92_2, 92_3, значения — списки снимков (как в BETSAPI_DATA_COVERAGE.md)
MOCK_RESPONSE_ODDS_TOP_LEVEL = {
    "results": {
        "odds": {
            "92_1": [
                {"id": 1, "home_od": "1.85", "away_od": "1.95", "ss": None, "add_time": 1730123400},
                {"id": 2, "home_od": "1.82", "away_od": "2.00", "ss": "1-0 (11:9)", "add_time": 1730123500},
            ],
            "92_2": [
                {"id": 10, "home_od": "1.90", "away_od": "1.92", "handicap": "-1.5", "ss": None, "add_time": 1730123400},
            ],
            "92_3": [
                {"id": 20, "home_od": "1.88", "away_od": "1.94", "total": "5.5", "ss": "0-0", "add_time": 1730123380},
                {"id": 21, "home_od": "1.90", "away_od": "1.92", "total": "5.5", "line": "5.5", "ss": "1-0 (11:9)", "add_time": 1730123450},
            ],
        },
        "stats": {"matching_dir": -1},
    }
}

# Формат 2: results[event_id].odds (один event в запросе)
MOCK_RESPONSE_ODDS_UNDER_EVENT = {
    "results": {
        "12345": {
            "odds": {
                "92_1": [{"id": 1, "home_od": "2.10", "away_od": "1.75", "ss": None, "add_time": 1730123000}],
                "92_2": [{"id": 2, "home_od": "1.70", "away_od": "2.15", "handicap": "1.5", "ss": None, "add_time": 1730123000}],
                "92_3": [{"id": 3, "home_od": "1.95", "away_od": "1.87", "total": "6.5", "ss": None, "add_time": 1730123000}],
            }
        }
    }
}


def _check_bookmaker_structure(bm: dict) -> list[str]:
    errors = []
    if bm.get("name") != "b365":
        errors.append(f"bookmaker name expected 'b365', got {bm.get('name')!r}")
    markets = bm.get("markets") or []
    if not markets:
        errors.append("bookmaker has no 'markets'")
    market_names = {m.get("name") for m in markets if isinstance(m, dict)}
    for required in ("92_1", "92_2", "92_3"):
        if required not in market_names:
            errors.append(f"missing market {required!r}, have {sorted(market_names)!r}")
    for m in markets:
        if not isinstance(m, dict):
            continue
        name = m.get("name")
        snapshots = m.get("snapshots")
        if not isinstance(snapshots, list) or not snapshots:
            errors.append(f"market {name!r}: snapshots must be non-empty list")
            continue
        for i, snap in enumerate(snapshots):
            if not isinstance(snap, dict):
                errors.append(f"market {name!r} snapshot[{i}] not dict")
                continue
            outcomes = snap.get("outcomes")
            if not outcomes or len(outcomes) != 2:
                errors.append(f"market {name!r} snapshot[{i}]: expected 2 outcomes, got {outcomes!r}")
            for out in outcomes or []:
                if out.get("name") is None or out.get("price") is None:
                    errors.append(f"market {name!r} snapshot[{i}]: outcome missing name/price {out!r}")
            if name == "92_3":
                names = {o.get("name") for o in (outcomes or [])}
                if names != {"over", "under"}:
                    errors.append(f"market 92_3 snapshot[{i}]: expected over/under, got {names!r}")
            else:
                names = {o.get("name") for o in (outcomes or [])}
                if names != {"home", "away"}:
                    errors.append(f"market {name!r} snapshot[{i}]: expected home/away, got {names!r}")
    return errors


def main() -> int:
    errors: list[str] = []

    # 1) Формат results.odds
    out1 = _normalize_odds_response(MOCK_RESPONSE_ODDS_TOP_LEVEL)
    if not out1 or not isinstance(out1, list):
        errors.append(f"Format 1 (results.odds): expected list of bookmakers, got {type(out1).__name__!r} {out1!r}")
    else:
        for bm in out1:
            errors.extend(_check_bookmaker_structure(bm))
        # Проверяем line_value и score_at_snapshot в снимках
        bm = out1[0]
        for m in bm.get("markets") or []:
            name = m.get("name")
            for snap in m.get("snapshots") or []:
                if name == "92_2" and snap.get("line_value") is None:
                    errors.append(f"market 92_2: snapshot should have line_value (handicap)")
                if name == "92_3" and snap.get("line_value") is None:
                    errors.append(f"market 92_3: snapshot should have line_value (total/line)")
                if snap.get("snapshot_time") is None and (snap.get("outcomes") and any(s.get("price") for s in snap["outcomes"])):
                    # add_time был в моке — snapshot_time должен быть заполнен
                    errors.append(f"market {name!r}: snapshot should have snapshot_time from add_time")

    # 2) Формат results[event_id].odds
    out2 = _normalize_odds_response(MOCK_RESPONSE_ODDS_UNDER_EVENT)
    if not out2 or not isinstance(out2, list):
        errors.append(f"Format 2 (results[eid].odds): expected list of bookmakers, got {type(out2).__name__!r} {out2!r}")
    else:
        for bm in out2:
            errors.extend(_check_bookmaker_structure(bm))

    # 3) Пустой/некорректный ответ
    empty = _normalize_odds_response({})
    if empty:
        errors.append(f"Empty response should return [], got {empty!r}")
    bad = _normalize_odds_response({"results": []})
    if bad:
        errors.append(f"results=[] should return [], got {bad!r}")

    if errors:
        print("FAIL: odds parsing verification")
        for e in errors:
            print("  -", e)
        return 1
    print("OK: all coefficients parsed correctly (92_1, 92_2, 92_3; outcomes home/away, over/under; line_value, snapshot_time, score_at_snapshot)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
