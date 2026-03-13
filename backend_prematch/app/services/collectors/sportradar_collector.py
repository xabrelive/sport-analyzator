"""Sportradar collector stub — fixtures and live for table tennis."""
from typing import Any

from app.services.collectors.base import BaseCollector


class SportradarCollector(BaseCollector):
    """Stub. Replace with real Sportradar API when key is available."""

    async def fetch(self, **kwargs: Any) -> list[dict[str, Any]]:
        # TODO: Sportradar table tennis API (fixtures, live scores)
        return []
