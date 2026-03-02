"""Auth API: register (email + verify), login, Telegram register/login, verify email."""
import hashlib
import hmac
import logging
from datetime import datetime, timezone, timedelta
from uuid import UUID

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import RedirectResponse, JSONResponse
from jose import jwt, JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_async_session
from app.models.user import User
from app.schemas.auth import (
    RegisterTelegramBody,
    TelegramAuthPayload,
    TokenResponse,
    UserLogin,
    UserRegister,
)
from app.services.email import send_verification_email

router = APIRouter()
logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)

VERIFY_EMAIL_EXPIRE_HOURS = 24


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session: AsyncSession = Depends(get_async_session),
) -> User:
    """Require JWT and return current user. 401 if missing or invalid."""
    if not credentials or credentials.scheme != "Bearer":
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.secret_key,
            algorithms=[settings.algorithm],
        )
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="Неверный токен")
        user_uuid = UUID(sub)
    except (JWTError, ValueError) as e:
        logger.debug("JWT decode failed: %s", e)
        raise HTTPException(status_code=401, detail="Неверный или истёкший токен")
    r = await session.execute(select(User).where(User.id == user_uuid))
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return user


def hash_password(password: str) -> str:
    """Bcrypt hash (без passlib из-за несовместимости с новым bcrypt)."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode = {"sub": subject, "exp": expire}
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def create_verify_email_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=VERIFY_EMAIL_EXPIRE_HOURS)
    to_encode = {"sub": user_id, "purpose": "verify_email", "exp": expire}
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_verify_email_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        if payload.get("purpose") != "verify_email":
            return None
        return payload.get("sub")
    except JWTError:
        return None


def verify_telegram_widget_hash(payload: TelegramAuthPayload) -> bool:
    """Verify hash from Telegram Login Widget (https://core.telegram.org/widgets/login)."""
    if not settings.telegram_bot_token:
        logger.warning("Telegram bot token not set, cannot verify widget")
        return False
    data_copy = {
        "id": payload.id,
        "first_name": payload.first_name,
        "last_name": payload.last_name,
        "username": payload.username or "",
        "photo_url": payload.photo_url or "",
        "auth_date": payload.auth_date,
    }
    data_check_arr = [f"{k}={v}" for k in sorted(data_copy.keys()) for v in [data_copy[k]]]
    data_check_string = "\n".join(data_check_arr)
    secret_key = hashlib.sha256(settings.telegram_bot_token.encode("utf-8")).digest()
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if expected_hash != payload.hash:
        return False
    # Optional: reject if auth_date older than 24 hours
    if datetime.now(timezone.utc).timestamp() - payload.auth_date > 86400:
        return False
    return True


@router.post("/register", response_model=dict)
async def register(data: UserRegister, session: AsyncSession = Depends(get_async_session)):
    """Register with email. Sends verification link; account active after verify."""
    try:
        r = await session.execute(select(User).where(User.email == data.email))
        if r.scalar_one_or_none() is not None:
            raise HTTPException(status_code=400, detail="Email already registered")
        user = User(
            email=data.email,
            hashed_password=hash_password(data.password),
            email_verified=False,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        token = create_verify_email_token(str(user.id))
        verify_link = f"{settings.frontend_url}/verify-email?token={token}"
        try:
            send_verification_email(data.email, verify_link)
        except Exception as e:
            logger.warning("Could not send verification email (link in logs): %s", e)
        return {"message": "check_email", "detail": "Перейдите по ссылке из письма для подтверждения почты."}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Register failed: %s", e)
        return JSONResponse(
            status_code=500,
            content={"detail": "Ошибка при регистрации. Попробуйте позже."},
        )


@router.get("/verify-email")
async def verify_email(
    token: str,
    session: AsyncSession = Depends(get_async_session),
):
    """Confirm email; redirect to login with success or error."""
    user_id = decode_verify_email_token(token)
    if not user_id:
        return RedirectResponse(url=f"{settings.frontend_url}/login?error=invalid_token", status_code=302)
    try:
        user_uuid = UUID(user_id)
    except ValueError:
        return RedirectResponse(url=f"{settings.frontend_url}/login?error=invalid_token", status_code=302)
    r = await session.execute(select(User).where(User.id == user_uuid))
    user = r.scalar_one_or_none()
    if not user:
        return RedirectResponse(url=f"{settings.frontend_url}/login?error=user_not_found", status_code=302)
    user.email_verified = True
    await session.commit()
    # Optional: auto-login by redirecting with token
    access_token = create_access_token(str(user.id))
    return RedirectResponse(
        url=f"{settings.frontend_url}/login?verified=1&token={access_token}",
        status_code=302,
    )


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, session: AsyncSession = Depends(get_async_session)):
    """Login with email + password. Only for email-registered verified users."""
    r = await session.execute(select(User).where(User.email == data.email))
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    if not user.email_verified:
        raise HTTPException(status_code=403, detail="Подтвердите почту по ссылке из письма")
    if not user.hashed_password or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token)


async def require_bot_token(x_bot_token: str | None = Header(None, alias="X-Bot-Token")):
    """Require bot token for Telegram registration (called by our bot)."""
    if not settings.telegram_bot_token or x_bot_token != settings.telegram_bot_token:
        raise HTTPException(status_code=403, detail="Forbidden")
    return True


@router.post("/register-telegram", response_model=TokenResponse)
async def register_telegram(
    data: RegisterTelegramBody,
    _: bool = Depends(require_bot_token),
    session: AsyncSession = Depends(get_async_session),
):
    """Called by Telegram bot after user confirmed and sent DOB + optional email. Creates user and returns token."""
    r = await session.execute(select(User).where(User.telegram_id == data.telegram_id))
    if r.scalar_one_or_none() is not None:
        raise HTTPException(status_code=400, detail="Telegram already registered")
    email = data.email if data.email else User.email_placeholder(data.telegram_id)
    r = await session.execute(select(User).where(User.email == email))
    if r.scalar_one_or_none() is not None:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=email,
        hashed_password=None,
        email_verified=True,
        telegram_id=data.telegram_id,
        date_of_birth=data.date_of_birth,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token)


@router.post("/login-telegram", response_model=TokenResponse)
async def login_telegram(
    payload: TelegramAuthPayload,
    session: AsyncSession = Depends(get_async_session),
):
    """Login via Telegram Login Widget. Verifies hash and returns JWT."""
    if not verify_telegram_widget_hash(payload):
        raise HTTPException(status_code=401, detail="Invalid Telegram auth")
    r = await session.execute(select(User).where(User.telegram_id == payload.id))
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="Сначала зарегистрируйтесь через бота в Telegram",
        )
    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token)
