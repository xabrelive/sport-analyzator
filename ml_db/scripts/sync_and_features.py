#!/usr/bin/env python3
"""Синхронизация данных в ML-БД и расчёт фичей."""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from app.ml.feature_engine import FeatureEngine
from app.ml.pipeline import sync_finished_to_ml_once, sync_full_main_to_ml

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_features_backfill():
    """Пересчёт match_features для всех матчей в ML-БД."""
    from sqlalchemy import text
    from app.ml.db import get_ml_session

    engine = FeatureEngine()
    session = get_ml_session()
    try:
        rows = session.execute(
            text("""
                SELECT m.id, m.player1_id, m.player2_id, m.start_time, m.league_id
                FROM matches m
                LEFT JOIN match_features mf ON mf.match_id = m.id
                WHERE m.status = 'finished' AND mf.match_id IS NULL
                ORDER BY m.start_time ASC
                LIMIT 5000
            """)
        ).fetchall()
        count = 0
        for r in rows:
            match_id, p1, p2, st, lid = r[0], r[1], r[2], r[3], r[4]
            odds = session.execute(
                text("SELECT odds_p1, odds_p2 FROM odds WHERE match_id = :mid ORDER BY created_at ASC LIMIT 1"),
                {"mid": match_id},
            ).fetchone()
            o1 = float(odds[0] or 1.9) if odds else 1.9
            o2 = float(odds[1] or 1.9) if odds else 1.9
            f = engine.compute_for_match(match_id, p1, p2, st, o1, o2, lid or "")
            if f:
                engine.upsert_match_features(match_id, f)
                count += 1
        session.commit()
        logger.info("Features backfill: %s matches", count)
    finally:
        session.close()


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sync-only", action="store_true", help="Only sync, no features")
    parser.add_argument("--features-only", action="store_true", help="Only features backfill")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--days", type=int, default=0, help="0 = весь архив")
    parser.add_argument("--full", action="store_true", help="Полная синхронизация до исчерпания")
    args = parser.parse_args()

    if not args.features_only:
        days_back: int | None = 0 if args.days == 0 else args.days
        if args.full:
            res = await sync_full_main_to_ml(batch_size=min(args.limit, 5000), days_back=days_back)
        else:
            res = await sync_finished_to_ml_once(limit=args.limit, days_back=days_back)
        logger.info("Sync result: %s", res)

    if not args.sync_only:
        await run_features_backfill()


if __name__ == "__main__":
    asyncio.run(main())
