#!/usr/bin/env python3
"""Пересчёт рейтингов в ML-базе (ClickHouse) и проверка наличия/заполненности таблиц."""
from __future__ import annotations

import os
import sys

# backend как корень для импортов
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ml_v2.schema import ensure_schema
from app.ml_v2.ch_client import get_ch_client
from app.ml_v2.sync import recompute_elo_from_matches


ML_TABLES = [
    "ml.players",
    "ml.leagues",
    "ml.matches",
    "ml.match_sets",
    "ml.player_elo_history",
    "ml.player_match_stats",
    "ml.player_daily_stats",
    "ml.match_features",
]


def main() -> None:
    print("=== 1) Проверка схемы (создание таблиц при отсутствии) ===")
    ensure_schema()
    print("OK: схема применена\n")

    client = get_ch_client()

    print("=== 2) Наличие и заполненность таблиц ===")
    for table in ML_TABLES:
        try:
            rows = client.query(f"SELECT count() FROM {table} FINAL").result_rows
            cnt = int(rows[0][0]) if rows else 0
            status = "заполнена" if cnt > 0 else "пустая"
            print(f"  {table}: {cnt} строк ({status})")
        except Exception as e:
            print(f"  {table}: ОШИБКА — {e}")

    print("\n=== 3) Пересчёт рейтингов (recompute_elo_from_matches) ===")
    result = recompute_elo_from_matches()
    print(f"  Обработано матчей: {result.get('recomputed_matches', 0)}")
    print(f"  Записей в player_elo_history: {result.get('elo_rows', 0)}")

    print("\n=== 4) Повторная проверка таблиц после пересчёта ===")
    for table in ML_TABLES:
        try:
            rows = client.query(f"SELECT count() FROM {table} FINAL").result_rows
            cnt = int(rows[0][0]) if rows else 0
            status = "заполнена" if cnt > 0 else "пустая"
            print(f"  {table}: {cnt} строк ({status})")
        except Exception as e:
            print(f"  {table}: ОШИБКА — {e}")

    print("\nГотово.")


if __name__ == "__main__":
    main()
