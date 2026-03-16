"""Simple job-state cursor storage in ClickHouse."""
from __future__ import annotations

from app.ml_v2.ch_client import get_ch_client
from app.ml_v2.schema import ensure_schema


def get_job_cursor(job_name: str, default: str = "") -> str:
    ensure_schema()
    client = get_ch_client()
    rows = client.query(
        "SELECT cursor_value FROM ml.job_state WHERE job_name = %(job)s ORDER BY updated_at DESC LIMIT 1",
        {"job": job_name},
    ).result_rows
    if not rows:
        return default
    return str(rows[0][0] or default)


def set_job_cursor(job_name: str, cursor_value: str) -> None:
    ensure_schema()
    client = get_ch_client()
    client.insert(
        "ml.job_state",
        [[job_name, str(cursor_value)]],
        column_names=["job_name", "cursor_value"],
    )

