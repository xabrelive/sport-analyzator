"""Celery application."""
from celery import Celery
from celery.signals import worker_process_init

from app.config import settings

celery_app = Celery(
    "sport_analyzator",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.worker.tasks.collect_odds",
        "app.worker.tasks.collect_betsapi",
        "app.worker.tasks.collect_matches",
        "app.worker.tasks.normalize",
        "app.worker.tasks.probability",
        "app.worker.tasks.signals",
    ],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "app.worker.tasks.collect_odds.*": {"queue": "collect"},
        "app.worker.tasks.collect_betsapi.*": {"queue": "collect"},
        "app.worker.tasks.collect_matches.*": {"queue": "collect"},
        "app.worker.tasks.normalize.*": {"queue": "normalize"},
        "app.worker.tasks.probability.*": {"queue": "probability"},
        "app.worker.tasks.signals.*": {"queue": "signals"},
    },
    beat_schedule=(
        {
            # Один регион = 1 запрос к квоте API; несколько регионов (eu,uk,us,au) = 4 запроса
            "fetch-odds": {
                "task": "app.worker.tasks.collect_odds.fetch_odds",
                "schedule": settings.live_poll_interval_seconds,
                "options": {"queue": "collect"},
                "kwargs": {"sport": "table_tennis", "region": "eu"},
            },
            "fetch-betsapi-table-tennis-full": {
                "task": "app.worker.tasks.collect_betsapi.fetch_betsapi_table_tennis",
                "schedule": settings.prematch_poll_interval_seconds,
                "options": {"queue": "collect"},
                "kwargs": {"mode": "full"},
            },
            "fetch-betsapi-table-tennis-live": {
                "task": "app.worker.tasks.collect_betsapi.fetch_betsapi_table_tennis",
                "schedule": settings.live_poll_interval_seconds,
                "options": {"queue": "collect"},
                "kwargs": {"mode": "live"},
            },
            "fetch-matches": {
                "task": "app.worker.tasks.collect_matches.fetch_matches",
                "schedule": settings.prematch_poll_interval_seconds,
                "options": {"queue": "collect"},
                "kwargs": {"provider": "sportradar"},
            },
        }
        if settings.enable_scheduled_collectors
        else {}
    ),
)


@worker_process_init.connect
def _dispose_engine_after_fork(**kwargs):
    """После fork воркера сбрасываем пул соединений БД, чтобы asyncio.run() в задачах
    создавал новые соединения в своём event loop (избегаем "Future attached to a different loop")."""
    try:
        from app.db.session import engine
        engine.sync_engine.dispose()
    except Exception:
        pass
