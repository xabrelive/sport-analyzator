#!/usr/bin/env python3
"""Проверка заполненности всех ML таблиц в ClickHouse.

Запуск:
  cd backend && python scripts/check_clickhouse_ml_tables.py
  docker compose exec -T backend python scripts/check_clickhouse_ml_tables.py
  docker compose exec -T ml_worker python scripts/check_clickhouse_ml_tables.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ml_v2.schema import ensure_schema
from app.ml_v2.ch_client import get_ch_client


ML_TABLES = [
    "ml.matches",
    "ml.match_sets",
    "ml.player_elo_history",
    "ml.player_match_stats",
    "ml.player_daily_stats",
    "ml.match_features",
]
OPTIONAL_TABLES = ["ml.players", "ml.leagues"]


def main() -> None:
    print("=== Схема (создание таблиц при отсутствии) ===")
    ensure_schema()
    print("OK\n")

    client = get_ch_client()

    print("=== Заполненность таблиц ML ===")
    empty: list[str] = []
    for table in ML_TABLES + OPTIONAL_TABLES:
        try:
            rows = client.query(f"SELECT count() FROM {table} FINAL").result_rows
            cnt = int(rows[0][0]) if rows else 0
            status = "заполнена" if cnt > 0 else "пустая"
            if cnt == 0 and table in ML_TABLES:
                empty.append(table)
            print(f"  {table}: {cnt:,} строк — {status}")
        except Exception as e:
            print(f"  {table}: ОШИБКА — {e}")
            if table in ML_TABLES:
                empty.append(table)

    # Дополнительно: уникальные матчи и диапазон дат
    print("\n=== Матчи и фичи (сводка) ===")
    for label, query in [
        ("Уникальных match_id в ml.matches", "SELECT uniqExact(match_id) FROM ml.matches FINAL"),
        ("Уникальных match_id в ml.match_features", "SELECT uniqExact(match_id) FROM ml.match_features FINAL"),
        ("Матчи без фичей (пропуски)", """
            SELECT count() FROM (SELECT match_id FROM ml.matches FINAL) m
            LEFT JOIN (SELECT match_id FROM ml.match_features FINAL) f ON m.match_id = f.match_id
            WHERE f.match_id IS NULL
        """),
    ]:
        try:
            r = client.query(query.strip()).result_rows
            val = int(r[0][0]) if r else 0
            print(f"  {label}: {val:,}")
        except Exception as e:
            print(f"  {label}: ошибка — {e}")

    try:
        r = client.query(
            "SELECT min(start_time), max(start_time) FROM ml.match_features FINAL"
        ).result_rows
        if r and r[0][0] and r[0][1]:
            print(f"  match_features: даты от {r[0][0]} до {r[0][1]}")
    except Exception as e:
        print(f"  match_features даты: ошибка — {e}")

    print()
    if empty:
        print("ВНИМАНИЕ: пустые обязательные таблицы:", ", ".join(empty))
        print("Заполнение: sync + backfill (full-rebuild или ml_sync_loop).")
        sys.exit(1)
    print("Все обязательные таблицы заполнены.")
    sys.exit(0)


if __name__ == "__main__":
    main()
