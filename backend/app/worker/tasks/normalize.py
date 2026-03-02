"""Normalize raw fixture/odds and write to PostgreSQL."""
from app.worker.celery_app import celery_app


@celery_app.task(bind=True, name="app.worker.tasks.normalize.normalize_fixture")
def normalize_fixture_task(self, payload: dict):
    # TODO: map provider_match_id to internal match, upsert leagues/players/matches/odds_snapshots
    return {"normalized": False, "match_id": None}
