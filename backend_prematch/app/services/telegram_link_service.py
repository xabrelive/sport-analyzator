"""Токены и коды привязки Telegram к аккаунту (Redis). Срок жизни 15 минут."""
import logging
import secrets
import string
from uuid import UUID

from redis.asyncio import from_url as redis_from_url

from app.config import settings

logger = logging.getLogger(__name__)

REDIS_PREFIX = "tg_link:"
REDIS_CODE_PREFIX = "tg_link_code:"
TTL_SECONDS = 900  # 15 min


def _redis_key(token: str) -> str:
    return f"{REDIS_PREFIX}{token}"


def _redis_code_key(code: str) -> str:
    return f"{REDIS_CODE_PREFIX}{code}"


async def create_link_token(user_id: UUID) -> str:
    """Создаёт одноразовый токен привязки, сохраняет в Redis. Возвращает токен (для ссылки)."""
    token = secrets.token_urlsafe(12)
    key = _redis_key(token)
    client = redis_from_url(settings.redis_url, decode_responses=True)
    try:
        await client.set(key, str(user_id), ex=TTL_SECONDS)
        return token
    finally:
        await client.aclose()


async def create_link_code(user_id: UUID) -> str:
    """Создаёт одноразовый 6-значный код привязки, сохраняет в Redis. Возвращает код (пользователь пишет его боту)."""
    code = "".join(secrets.choice(string.digits) for _ in range(6))
    key = _redis_code_key(code)
    client = redis_from_url(settings.redis_url, decode_responses=True)
    try:
        await client.set(key, str(user_id), ex=TTL_SECONDS)
        return code
    finally:
        await client.aclose()


async def get_user_id_by_token(token: str) -> UUID | None:
    """Возвращает user_id по токену и удаляет ключ (одноразовый)."""
    if not token or not token.strip():
        return None
    key = _redis_key(token.strip())
    client = redis_from_url(settings.redis_url, decode_responses=True)
    try:
        user_id_str = await client.get(key)
        if not user_id_str:
            return None
        await client.delete(key)
        return UUID(user_id_str)
    except (ValueError, TypeError):
        return None
    finally:
        await client.aclose()


async def get_user_id_by_code(code: str) -> UUID | None:
    """Возвращает user_id по коду и удаляет ключ (одноразовый). Код — 6 цифр."""
    if not code or not code.strip():
        return None
    raw = code.strip()
    if len(raw) != 6 or not raw.isdigit():
        return None
    key = _redis_code_key(raw)
    client = redis_from_url(settings.redis_url, decode_responses=True)
    try:
        user_id_str = await client.get(key)
        if not user_id_str:
            return None
        await client.delete(key)
        return UUID(user_id_str)
    except (ValueError, TypeError):
        return None
    finally:
        await client.aclose()
