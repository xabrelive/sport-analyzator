"""Fetch matches/fixtures from Sportradar or SportMonks (stub)."""
from app.worker.celery_app import celery_app


@celery_app.task(bind=True, name="app.worker.tasks.collect_matches.fetch_matches")
def fetch_matches_task(self, provider: str = "sportradar"):
    # TODO: call provider API, push raw fixtures to Redis queue
    return {"collected": 0, "provider": provider}
