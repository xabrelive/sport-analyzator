"""Base collector interface."""
from abc import ABC, abstractmethod
from typing import Any


class BaseCollector(ABC):
    """Abstract collector: fetch from provider and return raw payloads for queue."""

    @abstractmethod
    async def fetch(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Fetch data from provider. Returns list of raw dicts to be normalized."""
        ...
