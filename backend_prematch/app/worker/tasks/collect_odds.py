"""Fetch odds from The Odds API and save to DB."""
import asyncio
import logging
from typing import Any

import httpx

from app.config import settings
from app.db.session import async_session_maker
from app.services.normalizer import Normalizer
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

BASE_URL = "https://api.the-odds-api.com/v4"


def _fetch_odds_sync(sport: str = "table_tennis", regions: str = "eu", markets: str = "h2h") -> list[dict[str, Any]]:
    """Sync HTTP request to The Odds API. Each region in `regions` counts as 1 request for quota."""
    if not settings.the_odds_api_key:
        logger.warning("THE_ODDS_API_KEY not set, skipping odds fetch")
        return []
    url = f"{BASE_URL}/sports/{sport}/odds"
    params = {
        "apiKey": settings.the_odds_api_key,
        "regions": regions,
        "markets": markets,
    }
    with httpx.Client(timeout=60.0) as client:
        resp = client.get(url, params=params)
        if resp.status_code == 404:
            logger.warning("Sport %s not found (404). For table tennis use another provider; trying soccer_epl for demo.", sport)
            if sport == "table_tennis":
                return _fetch_odds_sync(sport="soccer_epl", regions=regions, markets=markets)
            return []
        resp.raise_for_status()
        data = resp.json()
    return data if isinstance(data, list) else [data]


async def _normalize_odds_async(payload: list[dict[str, Any]]) -> list:
    """Run normalizer with async session."""
    async with async_session_maker() as session:
        norm = Normalizer(session)
        return await norm.normalize_odds_response(payload)


@celery_app.task(bind=True, name="app.worker.tasks.collect_odds.fetch_odds")
def fetch_odds_task(self, sport: str = "table_tennis", region: str = "eu", regions: str | None = None):
    """Fetch odds from The Odds API and save to PostgreSQL."""
    reg = regions if regions is not None else region
    try:
        payload = _fetch_odds_sync(sport=sport, regions=reg)
        if not payload:
            return {"collected": 0, "sport": sport, "message": "no data or key missing"}
        match_ids = asyncio.run(_normalize_odds_async(payload))
        return {"collected": len(match_ids), "sport": sport, "match_ids": [str(m) for m in match_ids]}
    except httpx.HTTPStatusError as e:
        logger.exception("Odds API HTTP error: %s", e)
        raise
    except Exception as e:
        logger.exception("Odds fetch failed: %s", e)
        raise
