"""Check value and send Telegram signals."""
from app.worker.celery_app import celery_app


@celery_app.task(bind=True, name="app.worker.tasks.signals.check_value_and_send")
def check_value_and_send_signals_task(self, match_id: str | None = None):
    # TODO: load odds + model probability, compute EV, if above threshold send to Telegram
    return {"signals_sent": 0}
