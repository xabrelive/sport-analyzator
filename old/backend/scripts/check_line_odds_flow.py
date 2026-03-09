#!/usr/bin/env python3
"""Диагностика: матчи из BetsAPI upcoming -> запрос odds -> сравнение с нашей линией в БД.

Запуск из корня проекта:
  cd backend && uv run python scripts/check_line_odds_flow.py

Требуется .env с BETSAPI_TOKEN. Использует ту же БД, что и приложение.
"""
import asyncio
import os
import sys
from pathlib import Path

# Корень репо для загрузки .env и PYTHONPATH
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

from sqlalchemy import select

from app.config import settings
from app.models import Match, OddsSnapshot
from app.services.collectors.betsapi_collector import BetsApiCollector
from app.services.betsapi_pipeline import fetch_line_data
from app.services.normalizer import Normalizer
from app.db.session import create_worker_engine_and_session


async def main():
    if not settings.betsapi_token:
        print("BETSAPI_TOKEN не задан в .env")
        return 1

    sid = settings.betsapi_table_tennis_sport_id
    collector = BetsApiCollector()

    print("=" * 60)
    print("1) Список upcoming из BetsAPI")
    print("=" * 60)
    events = await collector.fetch(
        sport_id=sid,
        include_upcoming=True,
        include_inplay=False,
        include_ended=False,
        fetch_event_view=False,
        fetch_event_odds=False,
        rate_limit_seconds=1.0,
    )
    upcoming = [e for e in events if isinstance(e, dict) and e.get("_source") == "upcoming"]
    upcoming_ids = [str(e["id"]) for e in upcoming if e.get("id") is not None]
    print(f"Upcoming событий: {len(upcoming_ids)}")
    for i, e in enumerate(upcoming[:5]):
        home = (e.get("home") or {}).get("name", "?")
        away = (e.get("away") or {}).get("name", "?")
        print(f"  [{i}] id={e.get('id')}  {home} vs {away}")

    if not upcoming_ids:
        print("Нет upcoming — нечего проверять.")
        return 0

    print()
    print("=" * 60)
    print("2) Запрос view (для bet365_id), затем odds (v4 prematch) для первых 3 upcoming")
    print("=" * 60)
    ids_for_odds = upcoming_ids[:3]
    # Сначала view, чтобы в событиях был bet365_id (v4 prematch требует FI=bet365_id)
    events_with_view = await collector.fetch(
        sport_id=sid,
        include_upcoming=False,
        include_inplay=False,
        include_ended=False,
        fetch_event_view=True,
        fetch_event_odds=False,
        events_from_lists=events,
        event_ids_for_view=ids_for_odds,
        event_ids_for_odds=[],
        rate_limit_seconds=1.0,
    )
    events2 = await collector.fetch(
        sport_id=sid,
        include_upcoming=False,
        include_inplay=False,
        include_ended=False,
        fetch_event_view=False,
        fetch_event_odds=True,
        events_from_lists=events_with_view,
        event_ids_for_view=[],
        event_ids_for_odds=ids_for_odds,
        rate_limit_seconds=1.0,
    )
    for eid in ids_for_odds:
        ev = next((x for x in events2 if isinstance(x, dict) and str(x.get("id")) == eid), None)
        if not ev:
            print(f"  {eid}: событие не найдено в ответе")
            continue
        bm = ev.get("bookmakers") or ev.get("odds")
        if isinstance(bm, list) and bm:
            markets = bm[0].get("markets") or []
            snap_count = sum(len(m.get("snapshots") or []) for m in markets if isinstance(m, dict))
            print(f"  {eid}: bookmakers={len(bm)}, рынков={len(markets)}, снимков={snap_count}")
        else:
            print(f"  {eid}: нет bookmakers (BetsAPI мог не вернуть odds для прематча)")

    print()
    print("=" * 60)
    print("3) Состояние в БД ДО нормализации")
    print("=" * 60)
    engine, session_maker = create_worker_engine_and_session()
    try:
        async with session_maker() as session:
            for pid in ids_for_odds:
                r = await session.execute(
                    select(Match.id, Match.provider_match_id, Match.status).where(
                        Match.provider == "betsapi",
                        Match.provider_match_id == pid,
                    )
                )
                row = r.one_or_none()
                if not row:
                    print(f"  {pid}: матча нет в БД")
                    continue
                match_id, _, status = row
                cnt = await session.execute(
                    select(OddsSnapshot.id).where(
                        OddsSnapshot.match_id == match_id,
                        OddsSnapshot.phase.in_(["line", None]),
                    ).limit(1)
                )
                has_line = cnt.scalar_one_or_none() is not None
                print(f"  {pid}: match_id={match_id}, status={status}, line_odds_in_db={has_line}")
    finally:
        await engine.dispose()

    print()
    print("=" * 60)
    print("4) Запуск полного цикла линии (fetch_line_data + normalize)")
    print("=" * 60)
    engine2, session_maker2 = create_worker_engine_and_session()
    try:
        line_events, current_ids = await fetch_line_data(collector, session_maker2)
        print(f"  fetch_line_data: событий={len(line_events)}, current_upcoming_ids={len(current_ids)}")
        if not line_events:
            print("  Событий нет — нормализацию не запускаем.")
        else:
            async with session_maker2() as session:
                norm = Normalizer(session)
                match_ids = await norm.normalize_betsapi_response(line_events, current_event_ids=None)
                await session.commit()
                print(f"  normalize: обработано match_ids={len(match_ids)}")
    finally:
        await engine2.dispose()

    print()
    print("=" * 60)
    print("5) Состояние в БД ПОСЛЕ нормализации")
    print("=" * 60)
    engine3, session_maker3 = create_worker_engine_and_session()
    try:
        async with session_maker3() as session:
            for pid in ids_for_odds[:5]:
                r = await session.execute(
                    select(Match.id, Match.provider_match_id, Match.status).where(
                        Match.provider == "betsapi",
                        Match.provider_match_id == pid,
                    )
                )
                row = r.one_or_none()
                if not row:
                    print(f"  {pid}: матча нет в БД")
                    continue
                match_id, _, status = row
                cnt = await session.execute(
                    select(OddsSnapshot.id).where(
                        OddsSnapshot.match_id == match_id,
                        OddsSnapshot.phase.in_(["line", None]),
                    )
                )
                count = len(cnt.all())
                print(f"  {pid}: match_id={match_id}, status={status}, line_odds_snapshots={count}")
    finally:
        await engine3.dispose()

    print()
    print("Готово.")
    return 0


if __name__ == "__main__":
    exit(asyncio.run(main()))
