"""Verification code: generate, hash, store, verify."""
import hashlib
import random
import string
from datetime import datetime, timezone, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.verification_code import VerificationCode

TYPE_EMAIL_VERIFY = "email_verify"
TYPE_TELEGRAM_REGISTER = "telegram_register"
TYPE_TELEGRAM_LINK = "telegram_link"


def _generate_code() -> str:
    length = max(4, min(10, settings.verification_code_length))
    return "".join(random.choices(string.digits, k=length))


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _expires_at() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=settings.verification_code_expire_minutes)


async def create_code(
    session: AsyncSession,
    code_type: str,
    contact: str,
    user_id: UUID | None = None,
) -> str:
    """Create a new code, store hash, return plain code."""
    code = _generate_code()
    code_hash = _hash_code(code)
    row = VerificationCode(
        type=code_type,
        contact=contact,
        code_hash=code_hash,
        expires_at=_expires_at(),
        user_id=user_id,
    )
    session.add(row)
    await session.commit()
    return code


async def verify_code(
    session: AsyncSession,
    code_type: str,
    code: str,
    contact: str | None = None,
) -> VerificationCode | None:
    """Find valid code by type and code (and optionally contact). Returns row or None. Does not delete (caller may delete after use)."""
    code_hash = _hash_code(code)
    now = datetime.now(timezone.utc)
    q = select(VerificationCode).where(
        VerificationCode.type == code_type,
        VerificationCode.code_hash == code_hash,
        VerificationCode.expires_at > now,
    )
    if contact is not None:
        q = q.where(VerificationCode.contact == contact)
    r = await session.execute(q)
    return r.scalar_one_or_none()


async def consume_code(session: AsyncSession, row: VerificationCode) -> None:
    """Delete code so it cannot be reused."""
    await session.delete(row)
    await session.commit()
