"""Рассылка сигналов по новым прогнозам из match_recommendations (батч за 5 минут) и обработка истечения подписок на платный канал."""
import asyncio
import logging
from datetime import date, datetime, timezone

from sqlalchemy import select, update

from app.db.session import create_worker_engine_and_session
from app.models import User, UserSubscription
from app.models.user_subscription import AccessType
from app.services.signal_delivery_service import (
    deliver_signals_batch_async,
    deliver_free_channel_async,
    deliver_paid_channel_async,
    reply_forecast_results_async,
    send_dm_batch_results_async,
    send_dm_single_results_async,
    send_free_channel_daily_stats_async,
    send_paid_channel_daily_stats_async,
)
from app.services.telegram_channel_service import remove_from_paid_channel_and_notify_async
from app.services.telegram_promo_service import run_scheduled_posts as run_scheduled_posts_async
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.worker.tasks.signals.deliver_signals_batch")
def deliver_signals_batch():
    """
    Находит рекомендации за последние 5 минут без signals_sent_at,
    отправляет одним сообщением в Telegram и/или на почту всем подписчикам на сигналы,
    помечает рекомендации как отправленные.
    """
    engine, session_maker = create_worker_engine_and_session()
    try:
        sent = asyncio.run(deliver_signals_batch_async(session_maker))
        return {"deliveries": sent}
    except Exception as e:
        logger.exception("deliver_signals_batch failed: %s", e)
        raise
    finally:
        engine.sync_engine.dispose()


@celery_app.task(name="app.worker.tasks.signals.deliver_free_channel")
def deliver_free_channel():
    """
    Бесплатный канал: до 3–4 прогнозов в сутки, кф ≤2, до начала матча ≥60 мин,
    уверенность ~100%, окно 9–21 МСК, между сообщениями ≥1 ч. Включено при free_channel_enabled=True.
    """
    engine, session_maker = create_worker_engine_and_session()
    try:
        sent = asyncio.run(deliver_free_channel_async(session_maker))
        return {"deliveries": sent}
    except Exception as e:
        logger.exception("deliver_free_channel failed: %s", e)
        raise
    finally:
        engine.sync_engine.dispose()


@celery_app.task(name="app.worker.tasks.signals.deliver_paid_channel")
def deliver_paid_channel():
    """
    Платный канал: 1–3 раза в час один прогноз с макс. вероятностью захода (по одному из спортов); экспресс позже.
    """
    engine, session_maker = create_worker_engine_and_session()
    try:
        sent = asyncio.run(deliver_paid_channel_async(session_maker))
        return {"deliveries": sent}
    except Exception as e:
        logger.exception("deliver_paid_channel failed: %s", e)
        raise
    finally:
        engine.sync_engine.dispose()


async def process_paid_channel_expiries_async(session_maker):
    """
    Находит подписки на сигналы с истёкшим valid_until, по которым ещё не отправляли уведомление в Telegram.
    Удаляет пользователя из платного канала, шлёт в личку ссылку на тарифы, помечает подписку как обработанную.
    """
    today = date.today()
    async with session_maker() as session:
        q = (
            select(UserSubscription.id, User.telegram_id)
            .join(User, UserSubscription.user_id == User.id)
            .where(
                UserSubscription.access_type == AccessType.SIGNALS.value,
                UserSubscription.valid_until < today,
                UserSubscription.expiry_telegram_sent_at.is_(None),
                User.telegram_id.isnot(None),
            )
        )
        rows = (await session.execute(q)).all()
    processed = 0
    for sub_id, telegram_id in rows:
        if not telegram_id:
            continue
        try:
            await remove_from_paid_channel_and_notify_async(telegram_id)
        except Exception as e:
            logger.warning("remove_from_paid_channel_and_notify failed for telegram_id %s: %s", telegram_id, e)
        async with session_maker() as session:
            await session.execute(
                update(UserSubscription)
                .where(UserSubscription.id == sub_id)
                .values(expiry_telegram_sent_at=datetime.now(timezone.utc))
            )
            await session.commit()
        processed += 1
    return processed


@celery_app.task(name="app.worker.tasks.signals.process_paid_channel_expiries")
def process_paid_channel_expiries():
    """
    Истечение подписок на платный канал: удалить из канала, отправить в личку ссылку на тарифы, пометить подписку.
    """
    engine, session_maker = create_worker_engine_and_session()
    try:
        n = asyncio.run(process_paid_channel_expiries_async(session_maker))
        return {"processed": n}
    except Exception as e:
        logger.exception("process_paid_channel_expiries failed: %s", e)
        raise
    finally:
        engine.sync_engine.dispose()


@celery_app.task(name="app.worker.tasks.signals.reply_forecast_results")
def reply_forecast_results():
    """
    Для прогнозов, отправленных в каналы (free/paid), у которых матч завершён и результат известен,
    отправляет в Telegram ответ на исходное сообщение: «✅ Угадали» или «❌ Не угадали».
    Для личных сообщений: по батчам (несколько матчей в одном сообщении), когда по всем известны исходы,
    отправляет одно сообщение с итогами по каждому матчу.
    """
    engine, session_maker = create_worker_engine_and_session()
    try:
        n = asyncio.run(reply_forecast_results_async(session_maker))
        dm_batches = asyncio.run(send_dm_batch_results_async(session_maker))
        dm_singles = asyncio.run(send_dm_single_results_async(session_maker))
        return {"replies": n, "dm_batch_results": dm_batches, "dm_single_results": dm_singles}
    except Exception as e:
        logger.exception("reply_forecast_results failed: %s", e)
        raise
    finally:
        engine.sync_engine.dispose()


@celery_app.task(name="app.worker.tasks.signals.send_free_channel_daily_stats")
def send_free_channel_daily_stats():
    """Статистика за день в бесплатный канал (вызов в 21:00 МСК)."""
    engine, session_maker = create_worker_engine_and_session()
    try:
        ok = asyncio.run(send_free_channel_daily_stats_async(session_maker))
        return {"ok": ok}
    except Exception as e:
        logger.exception("send_free_channel_daily_stats failed: %s", e)
        raise
    finally:
        engine.sync_engine.dispose()


@celery_app.task(name="app.worker.tasks.signals.send_paid_channel_daily_stats")
def send_paid_channel_daily_stats():
    """Итоги за сутки в VIP-чат (вызов в 23:59 МСК)."""
    engine, session_maker = create_worker_engine_and_session()
    try:
        ok = asyncio.run(send_paid_channel_daily_stats_async(session_maker))
        return {"ok": ok}
    except Exception as e:
        logger.exception("send_paid_channel_daily_stats failed: %s", e)
        raise
    finally:
        engine.sync_engine.dispose()


@celery_app.task(name="app.worker.tasks.signals.run_scheduled_posts")
def run_scheduled_posts():
    """Проверяет отложенные посты (реклама/статистика) по расписанию и отправляет в каналы или в личку."""
    engine, session_maker = create_worker_engine_and_session()
    try:
        n = asyncio.run(run_scheduled_posts_async(session_maker))
        return {"sent": n}
    except Exception as e:
        logger.exception("run_scheduled_posts failed: %s", e)
        raise
    finally:
        engine.sync_engine.dispose()
