"""The Odds API collector — table tennis odds."""
from typing import Any

import httpx

from app.config import settings
from app.services.collectors.base import BaseCollector


class OddsApiCollector(BaseCollector):
    """Fetch odds from https://the-odds-api.com/ (sport key: table_tennis)."""

    BASE_URL = "https://api.the-odds-api.com/v4"

    async def fetch(
        self,
        sport: str = "table_tennis",
        regions: str = "eu",
        markets: str = "h2h",
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        if not settings.the_odds_api_key:
            return []
        url = f"{self.BASE_URL}/sports/{sport}/odds"
        params = {
            "apiKey": settings.the_odds_api_key,
            "regions": regions,
            "markets": markets,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        return data if isinstance(data, list) else [data]
