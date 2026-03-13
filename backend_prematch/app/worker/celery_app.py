"""Celery application."""
import logging

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init

from app.config import settings

logger = logging.getLogger(__name__)

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
beat_schedule: dict = {}
if settings.enable_scheduled_collectors:
    # Единый пайплайн BetsAPI: стабильная линия и лайв. Лимит 3600/час.
    logger.info("Celery beat: ENABLE_SCHEDULED_COLLECTORS=true, simple line/live tasks scheduled")
    beat_schedule.update(
        {
            "fetch-odds": {
                "task": "app.worker.tasks.collect_odds.fetch_odds",
                "schedule": settings.live_odds_poll_interval_seconds,
                "options": {"queue": "collect"},
                "kwargs": {"sport": "table_tennis", "region": "eu"},
            },
            # Новый стабильный планировщик линии: только простой режим line в BetsAPI‑пайплайне.
            "fetch-betsapi-line-simple": {
                "task": "app.worker.tasks.collect_betsapi.fetch_betsapi_table_tennis",
                "schedule": settings.prematch_poll_interval_seconds,
                "options": {
                    "queue": "betsapi_collect",
                    # Если тик пропущен или завис, он не мешает следующему запуску.
                    "expires": max(60, int(settings.prematch_poll_interval_seconds)),
                },
                "kwargs": {"mode": "line"},
            },
            "fetch-betsapi-live": {
                "task": "app.worker.tasks.collect_betsapi.fetch_betsapi_table_tennis",
                "schedule": settings.live_poll_interval_seconds,
                "options": {
                    "queue": "betsapi_collect",
                    # Даём воркерам больше времени, чтобы успеть обработать live‑таски
                    # даже во время тяжёлого прогона линии: не хотим, чтобы live постоянно
                    # «пропускался» из‑за слишком маленького expires.
                    "expires": max(10, int(settings.live_poll_interval_seconds) * 3),
                },
                "kwargs": {"mode": "live"},
            },
            "run-disappeared-retry": {
                "task": "app.worker.tasks.collect_betsapi.run_disappeared_retry",
                "schedule": 300,
                "options": {"queue": "betsapi_collect", "expires": 120},
            },
            # Сторонний провайдер матчей (sportradar) оставляем без изменений.
            "fetch-matches": {
                "task": "app.worker.tasks.collect_matches.fetch_matches",
                "schedule": settings.prematch_poll_interval_seconds,
                "options": {"queue": "collect"},
                "kwargs": {"provider": "sportradar"},
            },
            # Лёгкий фон для линии: аккуратная догрузка коэффициентов только для матчей без line OddsSnapshot.
            # Работает в той же очереди betsapi_collect с низкой конкуррентностью воркеров, чтобы не создавать дедлоки.
            "backfill-line-odds": {
                "task": "app.worker.tasks.collect_betsapi.backfill_line_odds",
                "schedule": 180,  # раз в 3 минуты
                "options": {"queue": "betsapi_collect", "expires": 300},
            },
            # Догрузка результатов матчей (MatchResult) — нужна для корректной статистики исходов.
            # Запускаем редко и с большим expires, чтобы не мешать основной линии и лайву.
            "backfill-missing-results": {
                "task": "app.worker.tasks.collect_betsapi.backfill_missing_results",
                "schedule": 600,  # раз в 10 минут
                "options": {"queue": "betsapi_collect", "expires": 900},
            },
            # Авто-backfill рекомендаций для актуальных матчей линии/лайва:
            # раз в N секунд (по умолчанию 60) добивает отсутствующие match_recommendations.
            "precompute-active-recommendations": {
                "task": "app.worker.tasks.collect_betsapi.precompute_active_recommendations",
                "schedule": settings.recommendations_backfill_interval_seconds,
                "options": {
                    "queue": "betsapi_collect",
                    "expires": max(60, int(settings.recommendations_backfill_interval_seconds) * 2),
                },
            },
        }
    )
else:
    logger.warning(
        "Celery beat: ENABLE_SCHEDULED_COLLECTORS is false — линия и лайв не запрашиваются. "
        "Задайте ENABLE_SCHEDULED_COLLECTORS=true в .env для загрузки матчей."
    )

# Рассылка уведомлений о рекомендациях и истечение платного канала — всегда в расписании
# (отправка только пользователям с активной подпиской на сигналы).
beat_schedule.update(
    {
        "deliver-signals-batch": {
            "task": "app.worker.tasks.signals.deliver_signals_batch",
            "schedule": 120,
            "options": {"queue": "signals", "expires": 60},
        },
        "deliver-free-channel": {
            "task": "app.worker.tasks.signals.deliver_free_channel",
            "schedule": 1800,
            "options": {"queue": "signals", "expires": 300},
        },
        "deliver-paid-channel": {
            "task": "app.worker.tasks.signals.deliver_paid_channel",
            "schedule": 300,
            "options": {"queue": "signals", "expires": 300},
        },
        "process-paid-channel-expiries": {
            "task": "app.worker.tasks.signals.process_paid_channel_expiries",
            "schedule": 86400,
            "options": {"queue": "signals", "expires": 3600},
        },
        "reply-forecast-results": {
            "task": "app.worker.tasks.signals.reply_forecast_results",
            "schedule": 300,
            "options": {"queue": "signals", "expires": 120},
        },
        "send-free-channel-daily-stats": {
            "task": "app.worker.tasks.signals.send_free_channel_daily_stats",
            "schedule": crontab(hour=18, minute=0),
            "options": {"queue": "signals", "expires": 300},
        },
        "send-paid-channel-daily-stats": {
            "task": "app.worker.tasks.signals.send_paid_channel_daily_stats",
            "schedule": crontab(hour=20, minute=59),
            "options": {"queue": "signals", "expires": 300},
        },
        "run-scheduled-posts": {
            "task": "app.worker.tasks.signals.run_scheduled_posts",
            "schedule": 900,
            "options": {"queue": "signals", "expires": 600},
        },
    }
)

if settings.enable_betsapi_history_auto:
    # Архив: раз в 2 часа за текущий и предыдущий день
    beat_schedule.update(
        {
            "load-betsapi-history-today": {
                "task": "app.worker.tasks.collect_betsapi.load_betsapi_today",
                "schedule": settings.betsapi_history_auto_interval_seconds,
                "options": {"queue": "history"},
                "kwargs": {"delay_seconds": settings.betsapi_history_delay_seconds},
            }
        }
    )

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "app.worker.tasks.collect_odds.*": {"queue": "collect"},
        "app.worker.tasks.collect_betsapi.fetch_*": {"queue": "betsapi_collect"},
        "app.worker.tasks.collect_betsapi.run_disappeared_retry": {"queue": "betsapi_collect"},
        "app.worker.tasks.collect_betsapi.precompute_*": {"queue": "betsapi_collect"},
        "app.worker.tasks.collect_betsapi.load_betsapi_history": {"queue": "history"},
        "app.worker.tasks.collect_betsapi.load_betsapi_today": {"queue": "history"},
        "app.worker.tasks.collect_betsapi.backfill_missing_results": {"queue": "betsapi_collect"},
        "app.worker.tasks.collect_betsapi.backfill_line_odds": {"queue": "betsapi_collect"},
        "app.worker.tasks.collect_matches.*": {"queue": "collect"},
        "app.worker.tasks.normalize.*": {"queue": "normalize"},
        "app.worker.tasks.probability.*": {"queue": "probability"},
        "app.worker.tasks.signals.*": {"queue": "signals"},
    },
    worker_prefetch_multiplier=1,
    beat_schedule=beat_schedule,
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
