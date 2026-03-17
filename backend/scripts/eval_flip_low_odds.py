#!/usr/bin/env python3
"""Оценка правила переворота ML-пиков при низком коэффициенте.

Считает две метрики по истории:
- baseline: как если бы переворота не было (используем фактический pick_side);
- flip_low_odds: если odds_used < threshold → считаем прогноз как перевёрнутый (home<->away).

Выводит hit-rate и sample size отдельно по:
- рынку match;
- рынку set1;
- совокупно (match+set1).

Запуск (из корня проекта, когда docker-compose уже поднят):

  docker compose exec backend python scripts/eval_flip_low_odds.py
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

from sqlalchemy import and_, select

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings  # noqa: E402
from app.db.session import async_session_maker  # noqa: E402
from app.models.table_tennis_forecast_v2 import TableTennisForecastV2  # noqa: E402
from app.models.table_tennis_line_event import TableTennisLineEvent  # noqa: E402
from app.services.outcome_resolver_v2 import _winner_set  # noqa: E402


async def _load_finished_with_forecasts(limit: int = 50000) -> list[tuple[TableTennisForecastV2, TableTennisLineEvent]]:
    """Загружает последние N прогнозов ML (channel='paid') с завершёнными матчами и счётом по сетам."""
    async with async_session_maker() as session:
        stmt = (
            select(TableTennisForecastV2, TableTennisLineEvent)
            .join(TableTennisLineEvent, TableTennisLineEvent.id == TableTennisForecastV2.event_id)
            .where(
                and_(
                    TableTennisForecastV2.channel == "paid",
                    TableTennisForecastV2.market.in_(["match", "set1"]),
                    TableTennisLineEvent.status.in_(["finished", "cancelled"]),
                    TableTennisLineEvent.live_sets_score.is_not(None),
                )
            )
            .order_by(TableTennisLineEvent.starts_at.desc())
            .limit(limit)
        )
        rows = (await session.execute(stmt)).all()
    return [(r[0], r[1]) for r in rows]


def _winner_match_by_sets(event: TableTennisLineEvent) -> str | None:
    """Простейший winner_by_sets: сравниваем счёт live_sets_score."""
    score = (event.live_sets_score or "").strip()
    if "-" not in score:
        return None
    left, right = score.split("-", 1)
    try:
        l = int(left)
        r = int(right)
    except ValueError:
        return None
    if l == r:
        return None
    return "home" if l > r else "away"


def _evaluate_one(
    fc: TableTennisForecastV2,
    ev: TableTennisLineEvent,
    odds_threshold: float,
) -> tuple[bool | None, bool | None]:
    """Возвращает (baseline_hit, flipped_hit) для одного прогноза.

    None = нельзя посчитать (нет победителя).
    """
    if fc.market == "match":
        winner = _winner_match_by_sets(ev)
    elif fc.market == "set1":
        winner = _winner_set(ev, "1")
    else:
        return None, None

    if winner is None:
        return None, None

    baseline_hit = winner == fc.pick_side

    # Эмулируем правило переворота: если odds_used < threshold → flip side.
    odds = float(fc.odds_used or 0.0)
    if odds > 0.0 and odds < odds_threshold:
        flipped_side = "away" if fc.pick_side == "home" else "home"
    else:
        flipped_side = fc.pick_side
    flipped_hit = winner == flipped_side
    return baseline_hit, flipped_hit


async def main() -> None:
    # CLI:
    #   1) limit      (опц.) — сколько прогнозов брать, по умолчанию 50000
    #   2) threshold  (опц.) — порог odds для переворота, по умолчанию из настроек
    import sys as _sys

    try:
        limit = int(_sys.argv[1]) if len(_sys.argv) > 1 else 50000
    except ValueError:
        limit = 50000
    if len(_sys.argv) > 2:
        try:
            threshold = float(_sys.argv[2])
        except ValueError:
            threshold = float(getattr(settings, "betsapi_table_tennis_v2_invert_low_odds_threshold", 1.5) or 1.5)
    else:
        threshold = float(getattr(settings, "betsapi_table_tennis_v2_invert_low_odds_threshold", 1.5) or 1.5)
    rows = await _load_finished_with_forecasts(limit=limit)
    if not rows:
        print("Нет данных для оценки (нет завершённых матчей с ML-прогнозами).")
        return

    stats = {
        "match": defaultdict(int),
        "set1": defaultdict(int),
        "all": defaultdict(int),
    }

    for fc, ev in rows:
        baseline_hit, flipped_hit = _evaluate_one(fc, ev, threshold)
        if baseline_hit is None:
            continue
        key = fc.market
        stats[key]["n"] += 1
        stats["all"]["n"] += 1
        if baseline_hit:
            stats[key]["baseline_hit"] += 1
            stats["all"]["baseline_hit"] += 1
        if flipped_hit:
            stats[key]["flipped_hit"] += 1
            stats["all"]["flipped_hit"] += 1

    def _print_bucket(name: str) -> None:
        n = stats[name]["n"]
        if n == 0:
            print(f"{name}: n=0 (нет данных)")
            return
        b = stats[name]["baseline_hit"]
        f = stats[name]["flipped_hit"]
        print(
            f"{name}: n={n}, "
            f"baseline_hit={b} ({b / n * 100:.2f}%), "
            f"flipped_hit={f} ({f / n * 100:.2f}%), "
            f"delta={(f - b):+d} ({(f - b) / n * 100:.2f} п.п.)"
        )

    print(f"Порог для переворота по коэффициенту: odds < {threshold:.2f}")
    print(f"Всего загружено прогнозов (match+set1, finished/cancelled): {len(rows)}\n")
    _print_bucket("match")
    _print_bucket("set1")
    _print_bucket("all")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())

