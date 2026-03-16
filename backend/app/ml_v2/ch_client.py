"""ClickHouse client helpers for ML v2."""
from __future__ import annotations

from functools import lru_cache

import clickhouse_connect

from app.config import settings


@lru_cache(maxsize=1)
def get_ch_client():
    kwargs = {
        "host": settings.clickhouse_host,
        "port": settings.clickhouse_port,
        "username": settings.clickhouse_user,
        "password": settings.clickhouse_password or "",
        "database": settings.clickhouse_database,
        "send_receive_timeout": 120,
    }
    try:
        return clickhouse_connect.get_client(**kwargs)
    except Exception as exc:
        # Fresh ClickHouse node may not have the target DB yet.
        # Connect to default DB so schema bootstrap can create it.
        if "UNKNOWN_DATABASE" not in str(exc):
            raise
        kwargs["database"] = "default"
        return clickhouse_connect.get_client(**kwargs)


def reset_ch_client() -> None:
    get_ch_client.cache_clear()

