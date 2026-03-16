#!/usr/bin/env python3
"""Расширенная проверка датасета ML v2 (ClickHouse).

Пример запуска:
  python scripts/check_ml_v2_dataset_report.py

В Docker:
  docker compose exec -T backend python scripts/check_ml_v2_dataset_report.py
"""
from __future__ import annotations

import math
import os
import sys
from typing import Any

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ml_v2.ch_client import get_ch_client
from app.ml_v2.schema import ensure_schema


def _fmt_int(v: int) -> str:
    return f"{int(v):,}"


def _fmt_num(v: Any) -> str:
    if v is None:
        return "null"
    try:
        x = float(v)
    except Exception:
        return str(v)
    if math.isfinite(x):
        return f"{x:.3f}"
    return str(v)


def _print_years(client) -> None:
    rows = client.query(
        """
        SELECT toYear(m.start_time) AS year, count() AS cnt
        FROM ml.match_features mf
        INNER JOIN ml.matches m ON m.match_id = mf.match_id
        GROUP BY year
        ORDER BY year
        """
    ).result_rows
    total = sum(int(r[1]) for r in rows)
    print("=== ML DB: матчи (finished + match_features) по годам ===")
    print("Year    Count")
    print("----    -----")
    for year, cnt in rows:
        print(f"{int(year)}    {_fmt_int(cnt)}")
    print("----    -----")
    print(f"Total   {_fmt_int(total)}")
    print()


def _print_target_dist(client, col: str) -> None:
    rows = client.query(
        f"""
        SELECT {col} AS y, count() AS cnt
        FROM ml.match_features
        GROUP BY y
        ORDER BY y
        """
    ).result_rows
    print(f"=== Таргет {col}{' (проверка бинарности)' if col == 'target_match' else ''} ===")
    print(col)
    total = 0
    ones = 0
    for y, cnt in rows:
        yi = int(y)
        ci = int(cnt)
        total += ci
        if yi == 1:
            ones = ci
        print(f"{yi}    {ci}")
    if col == "target_match" and total > 0:
        print(f"  Доля P1 (класс 1): {ones / total:.3f}")
    print()


def _describe_columns(client) -> list[tuple[str, str]]:
    rows = client.query("DESCRIBE TABLE ml.match_features").result_rows
    cols = [(str(r[0]), str(r[1])) for r in rows]
    print("=== Колонки match_features ===")
    print(f"  Всего колонок: {len(cols)}")
    print()
    return cols


def _print_fill_report(client, all_cols: list[str]) -> None:
    inspect_cols = [
        "dominance_last_50_diff",
        "fatigue_index_diff",
        "fatigue_ratio",
        "minutes_to_match",
        "odds_shift_p1",
        "odds_shift_p2",
        "elo_volatility_p1",
        "elo_volatility_p2",
        "elo_volatility_diff",
        "daily_performance_trend_diff",
        "dominance_trend_diff",
        "style_clash",
        "hours_since_last_h2h",
        "league_upset_rate",
    ]
    cols = [c for c in inspect_cols if c in all_cols]
    if not cols:
        return

    total_rows = int(client.query("SELECT count() FROM ml.match_features").result_rows[0][0])
    print("=== Заполнение v3 колонок (на всех матчах с фичами) ===")
    print(f"  Всего строк match_features: {_fmt_int(total_rows)}")
    print("  Колонка                              NOT NULL  % заполнено   distinct        мин       макс  статус")
    print("  -----------------------------------------------------------------------------------------------")

    for col in cols:
        q = (
            f"SELECT count() AS total, countIf(NOT isNull({col})) AS not_null, "
            f"uniqExact({col}) AS distinct_cnt, min({col}) AS min_v, max({col}) AS max_v "
            f"FROM ml.match_features"
        )
        total, not_null, distinct_cnt, min_v, max_v = client.query(q).result_rows[0]
        total_i = int(total or 0)
        nn_i = int(not_null or 0)
        dist_i = int(distinct_cnt or 0)
        pct = (100.0 * nn_i / total_i) if total_i else 0.0
        if nn_i == 0:
            status = "EMPTY"
        elif dist_i <= 1:
            status = "константа"
        elif pct < 70:
            status = "низкое заполнение"
        else:
            status = "OK"
        print(
            f"  {col:<34} {nn_i:>8}    {pct:>7.1f}%   {dist_i:>8}  "
            f"{_fmt_num(min_v):>9}  {_fmt_num(max_v):>9}  {status}"
        )
    print()


def _print_variance_report(client, cols_with_types: list[tuple[str, str]]) -> None:
    numeric_types = ("Int", "UInt", "Float", "Decimal")
    excluded = {"target_match", "target_set1"}
    feature_cols = [
        c
        for c, t in cols_with_types
        if c not in excluded
        and not c.endswith("_id")
        and c not in {"match_id", "start_time", "league_id", "player1_id", "player2_id", "created_at"}
        and any(nt in t for nt in numeric_types)
    ]
    if not feature_cols:
        return
    sample_n = 10_000
    q = f"SELECT {', '.join(feature_cols)} FROM ml.match_features ORDER BY start_time DESC LIMIT {sample_n}"
    rows = client.query(q).result_rows
    if not rows:
        return
    arr = np.asarray(rows, dtype=float)
    valid = 0
    for i in range(arr.shape[1]):
        col = arr[:, i]
        finite = col[np.isfinite(col)]
        if finite.size < 2:
            continue
        if float(np.var(finite)) > 1e-12:
            valid += 1
    print("=== Фичи с дисперсией (сэмпл 10k строк) ===")
    print(f"  Фичей с дисперсией: {valid} из {len(feature_cols)} (рекомендуется >80)")
    print()


def main() -> None:
    ensure_schema()
    client = get_ch_client()
    _print_years(client)
    _print_target_dist(client, "target_match")
    _print_target_dist(client, "target_set1")
    cols_with_types = _describe_columns(client)
    all_cols = [c for c, _ in cols_with_types]
    _print_fill_report(client, all_cols)
    _print_variance_report(client, cols_with_types)


if __name__ == "__main__":
    main()
