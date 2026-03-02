"""Recompute match probability (Beta-Bayes + Markov) and cache."""
from app.worker.celery_app import celery_app


@celery_app.task(bind=True, name="app.worker.tasks.probability.recompute_match_probability")
def recompute_match_probability_task(self, match_id: str):
    # TODO: load match + scores, run probability_engine, store in Redis
    return {"match_id": match_id, "p_home": None, "p_away": None}
