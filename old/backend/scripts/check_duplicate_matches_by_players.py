#!/usr/bin/env python3
"""Проверка: есть ли в БД пары матчей с одними и теми же игроками в том же порядке (хозяин/гость) и временем начала в пределах 1 часа, но разными provider_match_id.
Порядок важен: если те же два игрока поменялись местами — это другой матч, дубликатом не считается.

Возможная причина: в линии матч пришёл с одним id, в лайве — с другим, и создались два матча.

Запуск: PYTHONPATH=backend python backend/scripts/check_duplicate_matches_by_players.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.session import create_worker_engine_and_session
from app.models import Match


WINDOW_HOURS = 1


async def main() -> int:
    engine, session_maker = create_worker_engine_and_session()
    try:
        async with session_maker() as session:
            q = (
                select(Match)
                .where(Match.provider == "betsapi")
                .options(
                    selectinload(Match.home_player),
                    selectinload(Match.away_player),
                    selectinload(Match.league),
                )
                .order_by(Match.start_time.desc())
            )
            r = await session.execute(q)
            matches = list(r.scalars().all())
            if not matches:
                print("Нет матчей betsapi в БД.")
                return 0

            from collections import defaultdict

            by_players: dict[tuple, list[Match]] = defaultdict(list)
            for m in matches:
                key = (m.home_player_id, m.away_player_id)
                by_players[key].append(m)

            duplicates: list[tuple[Match, Match]] = []
            for key, group in by_players.items():
                if len(group) < 2:
                    continue
                group_sorted = sorted(group, key=lambda x: x.start_time)
                for i, a in enumerate(group_sorted):
                    for b in group_sorted[i + 1 :]:
                        if a.provider_match_id == b.provider_match_id:
                            continue
                        delta = abs((a.start_time - b.start_time).total_seconds())
                        if delta <= WINDOW_HOURS * 3600:
                            duplicates.append((a, b))

            if not duplicates:
                print("Дубликатов не найдено: нет пар матчей с одними игроками и временем в пределах 1 ч при разных provider_match_id.")
                return 0

            print(f"Найдено пар возможных дубликатов (те же игроки, время в пределах {WINDOW_HOURS} ч, разный provider_match_id): {len(duplicates)}\n")
            for a, b in duplicates[:50]:
                home = a.home_player.name if a.home_player else "?"
                away = a.away_player.name if a.away_player else "?"
                league = a.league.name if a.league else "?"
                print(f"  {home} – {away} ({league})")
                print(f"    A: id={a.id} provider_match_id={a.provider_match_id} status={a.status} start={a.start_time}")
                print(f"    B: id={b.id} provider_match_id={b.provider_match_id} status={b.status} start={b.start_time}")
                print()
            if len(duplicates) > 50:
                print(f"  ... и ещё {len(duplicates) - 50} пар.")
            return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
