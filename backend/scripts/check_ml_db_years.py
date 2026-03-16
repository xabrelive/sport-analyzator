#!/usr/bin/env python3
"""Проверка ML-базы: количество матчей по годам (finished + с фичами).
Запуск из backend/ (или из контейнера, рабочая директория /app):
  python scripts/check_ml_db_years.py
В контейнере:
  docker compose run --rm ml_train_gpu python scripts/check_ml_db_years.py
"""
from __future__ import annotations

import os
import sys

# чтобы подхватить app.config и DATABASE_URL_ML
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.ml.db import get_ml_engine


def main() -> None:
    engine = get_ml_engine()
    sql = """
        SELECT
            EXTRACT(YEAR FROM m.start_time)::int AS year,
            COUNT(*) AS cnt
        FROM match_features mf
        JOIN matches m ON m.id = mf.match_id
        WHERE m.status = 'finished'
          AND m.score_sets_p1 IS NOT NULL
          AND m.score_sets_p2 IS NOT NULL
        GROUP BY EXTRACT(YEAR FROM m.start_time)
        ORDER BY year
    """
    with engine.connect() as conn:
        rows = conn.execute(text(sql)).fetchall()
    total = sum(r[1] for r in rows)
    print("ML DB: матчи (finished + match_features) по годам:")
    print("Year  Count")
    print("----  -----")
    for year, cnt in rows:
        print(f"{year}  {cnt:,}")
    print("----  -----")
    print(f"Total {total:,}")
    engine.dispose()


if __name__ == "__main__":
    main()
