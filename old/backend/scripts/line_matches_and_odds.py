#!/usr/bin/env python3
"""Проверка матчей в линии (БД) и ручной запрос коэффициентов по тем, у кого их нет.

Что делает:
  1) Выводит список матчей в линии (scheduled/pending_odds, start_time >= now-15 мин).
  2) По каждому — есть ли в БД line OddsSnapshot (phase=line или NULL).
  3) С опцией --fetch: для матчей без кф выполняет запросы view+odds к BetsAPI и сохраняет в БД
     (то же, что задача backfill_line_odds, но без лимита пачки за один запуск).

Запуск:
  cd backend && uv run python scripts/line_matches_and_odds.py
  cd backend && uv run python scripts/line_matches_and_odds.py --fetch
  cd backend && uv run python scripts/line_matches_and_odds.py --fetch --batch 200

Требуется .env с BETSAPI_TOKEN. Использует ту же БД, что и приложение.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Корень репо
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import create_worker_engine_and_session
from app.models import Match, MatchStatus, OddsSnapshot


async def list_line_matches(session: AsyncSession) -> list[tuple[str, str, str, datetime | None, bool]]:
    """Возвращает список (provider_match_id, home_name, away_name, start_time, has_line_odds)."""
    from sqlalchemy.orm import selectinload
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=15)
    q = (
        select(Match)
        .where(
            Match.provider == "betsapi",
            Match.status.in_([MatchStatus.SCHEDULED.value, MatchStatus.PENDING_ODDS.value]),
            Match.start_time >= cutoff,
        )
        .options(selectinload(Match.home_player), selectinload(Match.away_player))
        .order_by(Match.start_time.asc())
    )
    matches = (await session.execute(q)).scalars().unique().all()
    if not matches:
        return []
    match_ids = [m.id for m in matches]
    q_odds = (
        select(OddsSnapshot.match_id)
        .where(
            OddsSnapshot.match_id.in_(match_ids),
            or_(OddsSnapshot.phase == "line", OddsSnapshot.phase.is_(None)),
        )
        .distinct()
    )
    rows_odds = (await session.execute(q_odds)).all()
    has_odds_ids = {r[0] for r in rows_odds}
    return [
        (
            str(m.provider_match_id),
            m.home_player.name if m.home_player else "?",
            m.away_player.name if m.away_player else "?",
            m.start_time,
            m.id in has_odds_ids,
        )
        for m in matches
    ]


async def run_fetch_odds(batch_size: int) -> dict:
    """Один прогон догрузки кф (как backfill_line_odds)."""
    from app.worker.tasks.collect_betsapi import _run_line_odds_backfill_async
    return await _run_line_odds_backfill_async(batch_size=batch_size)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Матчи в линии и ручной запрос коэффициентов")
    parser.add_argument("--fetch", action="store_true", help="Запросить view+odds по матчам без кф и сохранить в БД")
    parser.add_argument("--batch", type=int, default=200, help="Макс. матчей за один проход --fetch (по умолчанию 200)")
    args = parser.parse_args()

    if not (settings.betsapi_token or "").strip():
        print("BETSAPI_TOKEN не задан в .env")
        return 1

    engine, session_maker = create_worker_engine_and_session()
    try:
        async with session_maker() as session:
            rows = await list_line_matches(session)
        if not rows:
            print("В линии (scheduled/pending_odds, start_time >= now-15min) матчей нет.")
            return 0
        with_odds = sum(1 for r in rows if r[4])
        without_odds = len(rows) - with_odds
        print(f"Матчей в линии: {len(rows)}  |  с кф: {with_odds}  |  без кф: {without_odds}")
        print()
        print("Первые 30 матчей:")
        print("-" * 80)
        for i, (pid, home, away, start_time, has_odds) in enumerate(rows[:30]):
            st = start_time.isoformat()[:16] if start_time else "?"
            flag = "✓" if has_odds else "—"
            print(f"  {flag}  {pid}  {home} — {away}  {st}")
        if len(rows) > 30:
            print(f"  ... и ещё {len(rows) - 30} матчей")
        print()

        if args.fetch and without_odds > 0:
            print(f"Запуск догрузки кф (batch={args.batch})...")
            result = await run_fetch_odds(batch_size=args.batch)
            processed = result.get("processed", 0)
            normalized = result.get("normalized", 0)
            print(f"Обработано: {processed}, нормализовано (с кф): {normalized}")
            if processed > 0 and normalized < processed:
                print("Часть матчей могла вернуть пустые odds от API — это нормально для прематча НТ.")
        elif args.fetch and without_odds == 0:
            print("Все матчи в линии уже имеют кф, --fetch не требуется.")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
