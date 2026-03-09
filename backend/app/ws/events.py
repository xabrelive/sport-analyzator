"""Realtime events bridge: Redis pubsub -> WebSocket clients."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from redis.asyncio import from_url as redis_from_url

from app.config import settings
from app.ws.manager import ws_manager

logger = logging.getLogger(__name__)
MATCHES_EVENTS_CHANNEL = "realtime:matches"


async def publish_matches_updated(match_ids: list[str], *, mode: str) -> None:
    """Publish lightweight match-update event for frontend subscribers."""
    if not match_ids:
        return
    client = redis_from_url(settings.redis_url, decode_responses=True)
    try:
        payload = {
            "type": "matches_updated",
            "mode": mode,
            "count": len(match_ids),
            "match_ids": match_ids[:200],
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        await client.publish(MATCHES_EVENTS_CHANNEL, json.dumps(payload))
    except Exception as exc:
        logger.debug("Failed to publish matches update event: %s", exc)
    finally:
        await client.aclose()


class RedisWsBridge:
    def __init__(self) -> None:
        self._client = None
        self._pubsub = None
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        try:
            self._client = redis_from_url(settings.redis_url, decode_responses=True)
            self._pubsub = self._client.pubsub()
            await self._pubsub.subscribe(MATCHES_EVENTS_CHANNEL)
            self._task = asyncio.create_task(self._run(), name="redis-ws-bridge")
            logger.info("Realtime bridge started")
        except Exception:
            self._running = False
            self._client = None
            self._pubsub = None
            self._task = None
            raise

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._pubsub is not None:
            try:
                await self._pubsub.unsubscribe(MATCHES_EVENTS_CHANNEL)
                await self._pubsub.close()
            except Exception:
                pass
            self._pubsub = None
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    async def _run(self) -> None:
        assert self._pubsub is not None
        while self._running:
            try:
                msg = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if not msg or msg.get("type") != "message":
                    await asyncio.sleep(0.05)
                    continue
                raw = msg.get("data")
                if not isinstance(raw, str):
                    continue
                payload = json.loads(raw)
                await ws_manager.broadcast(payload)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Realtime bridge loop error: %s", exc)
                await asyncio.sleep(0.5)


redis_ws_bridge = RedisWsBridge()

