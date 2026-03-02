"""Celery tasks."""
from app.worker.tasks.collect_odds import fetch_odds_task
from app.worker.tasks.collect_betsapi import fetch_betsapi_table_tennis_task
from app.worker.tasks.collect_matches import fetch_matches_task
from app.worker.tasks.normalize import normalize_fixture_task
from app.worker.tasks.probability import recompute_match_probability_task
from app.worker.tasks.signals import check_value_and_send_signals_task

__all__ = [
    "fetch_odds_task",
    "fetch_betsapi_table_tennis_task",
    "fetch_matches_task",
    "normalize_fixture_task",
    "recompute_match_probability_task",
    "check_value_and_send_signals_task",
]
