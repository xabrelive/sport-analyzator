"""Auth API: register (email + code), verify-email (code), login, Telegram code create/verify, login-telegram (widget)."""
import hashlib
import hmac
import logging
from datetime import datetime, timezone, timedelta
from uuid import UUID

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt, JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_async_session
from app.models.app_setting import AppSetting
from app.models.user import User
from app.schemas.auth import (
    CreateTelegramCodeBody,
    LinkTelegramByCodeBody,
    LoginByTelegramCodeBody,
    RequestLinkEmailBody,
    RequestPasswordResetBody,
    ResendVerificationCodeBody,
    ResetPasswordBody,
    TelegramAuthPayload,
    TokenResponse,
    UserLogin,
    UserRegister,
    VerifyEmailBody,
    VerifyLinkEmailBody,
    VerifyTelegramCodeBody,
)
from app.services.code_service import (
    TYPE_EMAIL_LINK,
    TYPE_EMAIL_VERIFY,
    TYPE_PASSWORD_RESET,
    TYPE_TELEGRAM_LINK,
    TYPE_TELEGRAM_REGISTER,
    consume_code,
    create_code,
    verify_code,
)
from app.services.email import (
    send_email_link_code_email,
    send_password_changed_email,
    send_password_reset_code_email,
    send_verification_code_email,
)

router = APIRouter()
logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session: AsyncSession = Depends(get_async_session),
) -> User:
    if not credentials or credentials.scheme != "Bearer":
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="Неверный токен")
        user_uuid = UUID(sub)
    except (JWTError, ValueError):
        raise HTTPException(status_code=401, detail="Неверный или истёкший токен")
    r = await session.execute(select(User).where(User.id == user_uuid))
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    if user.is_blocked:
        raise HTTPException(status_code=403, detail="Аккаунт заблокирован")
    if not getattr(user, "is_active", True):
        raise HTTPException(status_code=403, detail="Аккаунт деактивирован")
    return user


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(plain: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode(
        {"sub": subject, "exp": expire},
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )


def _verify_telegram_widget(payload: TelegramAuthPayload) -> bool:
    if not settings.telegram_bot_token:
        return False
    data_check = "\n".join(
        f"{k}={getattr(payload, k) or ''}"
        for k in sorted(["id", "first_name", "last_name", "username", "photo_url", "auth_date"])
    )
    secret = hashlib.sha256(settings.telegram_bot_token.encode()).digest()
    expected = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if expected != payload.hash:
        return False
    if datetime.now(timezone.utc).timestamp() - payload.auth_date > 86400:
        return False
    return True


def _require_bot_token(x_bot_token: str | None = Header(None, alias="X-Bot-Token")):
    if not settings.telegram_bot_token or x_bot_token != settings.telegram_bot_token:
        raise HTTPException(status_code=403, detail="Forbidden")
    return True


@router.post("/register", response_model=dict)
async def register(
    data: UserRegister,
    session: AsyncSession = Depends(get_async_session),
):
    """Register by email. Sends verification code. Requires accept_terms and accept_privacy."""
    if not data.accept_terms or not data.accept_privacy:
        raise HTTPException(
            status_code=400,
            detail="Необходимо принять условия использования и политику конфиденциальности",
        )
    r = await session.execute(select(User).where(User.email == data.email))
    existing = r.scalar_one_or_none()
    if existing is not None:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "Email уже зарегистрирован",
                "email_verified": existing.email_verified,
            },
        )
    now = datetime.now(timezone.utc)
    user = User(
        email=data.email,
        hashed_password=_hash_password(data.password),
        email_verified=False,
        terms_accepted_at=now,
        privacy_accepted_at=now,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    code = await create_code(session, TYPE_EMAIL_VERIFY, data.email)
    if not send_verification_code_email(data.email, code):
        raise HTTPException(
            status_code=503,
            detail="Не удалось отправить письмо. Проверьте настройки SMTP на сервере.",
        )
    return {
        "message": "check_email",
        "detail": "На почту отправлен код подтверждения. Введите его на сайте.",
    }


@router.post("/resend-verification-code", response_model=dict)
async def resend_verification_code(
    data: ResendVerificationCodeBody,
    session: AsyncSession = Depends(get_async_session),
):
    """Повторно отправить код на почту (для неподтверждённого аккаунта)."""
    r = await session.execute(
        select(User).where(User.email == data.email, User.email_verified == False)
    )
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=400,
            detail="Пользователь не найден или почта уже подтверждена. Войдите или зарегистрируйтесь заново.",
        )
    code = await create_code(session, TYPE_EMAIL_VERIFY, data.email)
    if not send_verification_code_email(data.email, code):
        raise HTTPException(
            status_code=503,
            detail="Не удалось отправить письмо. Проверьте настройки SMTP на сервере.",
        )
    return {
        "message": "ok",
        "detail": "Код отправлен повторно на указанную почту.",
    }


@router.post("/verify-email", response_model=TokenResponse)
async def verify_email(
    data: VerifyEmailBody,
    session: AsyncSession = Depends(get_async_session),
):
    """Confirm email with code. Returns JWT."""
    row = await verify_code(session, TYPE_EMAIL_VERIFY, data.code, data.email)
    if not row:
        raise HTTPException(status_code=400, detail="Неверный или истёкший код")
    r = await session.execute(select(User).where(User.email == data.email))
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if user.is_blocked:
        raise HTTPException(status_code=403, detail="Аккаунт заблокирован")
    if not getattr(user, "is_active", True):
        raise HTTPException(status_code=403, detail="Аккаунт деактивирован")
    user.email_verified = True
    user.last_login_at = datetime.now(timezone.utc)
    await session.commit()
    await consume_code(session, row)
    return TokenResponse(access_token=_create_access_token(str(user.id)))


@router.post("/request-password-reset", response_model=dict)
async def request_password_reset(
    data: RequestPasswordResetBody,
    session: AsyncSession = Depends(get_async_session),
):
    """Отправить код для сброса пароля на почту. Только для подтверждённых аккаунтов."""
    r = await session.execute(
        select(User).where(User.email == data.email, User.email_verified == True)
    )
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=400,
            detail="Пользователь не найден или почта не подтверждена. Сначала завершите регистрацию.",
        )
    if not user.hashed_password:
        raise HTTPException(
            status_code=400,
            detail="Вход через Telegram. Пароль для этого аккаунта не задан.",
        )
    code = await create_code(session, TYPE_PASSWORD_RESET, data.email)
    if not send_password_reset_code_email(data.email, code):
        raise HTTPException(
            status_code=503,
            detail="Не удалось отправить письмо. Проверьте настройки SMTP на сервере.",
        )
    return {
        "message": "ok",
        "detail": "Код для сброса пароля отправлен на почту.",
    }


@router.post("/reset-password", response_model=dict)
async def reset_password(
    data: ResetPasswordBody,
    session: AsyncSession = Depends(get_async_session),
):
    """Установить новый пароль по коду из письма."""
    row = await verify_code(session, TYPE_PASSWORD_RESET, data.code, data.email)
    if not row:
        raise HTTPException(status_code=400, detail="Неверный или истёкший код")
    r = await session.execute(select(User).where(User.email == data.email))
    user = r.scalar_one_or_none()
    if not user:
        await consume_code(session, row)
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    user.hashed_password = _hash_password(data.new_password)
    await session.commit()
    await consume_code(session, row)
    send_password_changed_email(data.email)
    return {"message": "ok", "detail": "Пароль изменён. Войдите с новым паролем."}


@router.post("/login", response_model=TokenResponse)
async def login(
    data: UserLogin,
    session: AsyncSession = Depends(get_async_session),
):
    """Login with email + password. Email must be verified."""
    r = await session.execute(select(User).where(User.email == data.email))
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    if not user.email_verified:
        return JSONResponse(
            status_code=403,
            content={
                "detail": "Подтвердите почту — введите код из письма",
                "code": "email_not_verified",
                "email": data.email,
            },
        )
    if not user.hashed_password or not _verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    if user.is_blocked:
        raise HTTPException(status_code=403, detail="Аккаунт заблокирован")
    if not getattr(user, "is_active", True):
        raise HTTPException(status_code=403, detail="Аккаунт деактивирован")
    user.last_login_at = datetime.now(timezone.utc)
    await session.commit()
    return TokenResponse(access_token=_create_access_token(str(user.id)))


@router.post("/telegram/create-code", response_model=dict)
async def telegram_create_code(
    data: CreateTelegramCodeBody,
    _: bool = Depends(_require_bot_token),
    session: AsyncSession = Depends(get_async_session),
):
    """Called by bot. Creates code for telegram_id. Bot sends this code to user."""
    contact = str(data.telegram_id)
    if data.purpose != "telegram_register":
        raise HTTPException(status_code=400, detail="Use telegram_register for new users")
    code = await create_code(session, TYPE_TELEGRAM_REGISTER, contact)
    return {"code": code, "expires_minutes": settings.verification_code_expire_minutes_telegram}


BOT_INFO_KEY = "telegram_bot_info_message"


@router.get("/telegram/bot-info")
async def get_telegram_bot_info(
    _: bool = Depends(_require_bot_token),
    session: AsyncSession = Depends(get_async_session),
):
    """Bot fetches the message for «Получить информацию» button."""
    row = (
        await session.execute(select(AppSetting).where(AppSetting.key == BOT_INFO_KEY))
    ).scalar_one_or_none()
    return {"message": (row.value if row else "") or ""}


@router.post("/telegram/verify-code", response_model=TokenResponse)
async def telegram_verify_code(
    data: VerifyTelegramCodeBody,
    session: AsyncSession = Depends(get_async_session),
):
    """User on site enters code from bot. Creates account and returns JWT. Requires accept_terms and accept_privacy."""
    if not data.accept_terms or not data.accept_privacy:
        raise HTTPException(
            status_code=400,
            detail="Необходимо принять условия использования и политику конфиденциальности",
        )
    row = await verify_code(session, TYPE_TELEGRAM_REGISTER, data.code)
    if not row:
        raise HTTPException(
            status_code=400,
            detail="Неверный или истёкший код. Получите новый в боте.",
        )
    telegram_id = int(row.contact)
    r = await session.execute(select(User).where(User.telegram_id == telegram_id))
    if r.scalar_one_or_none() is not None:
        await consume_code(session, row)
        raise HTTPException(status_code=400, detail="Этот Telegram уже зарегистрирован. Войдите через «Войти через Telegram».")
    email = User.email_placeholder(telegram_id)
    r = await session.execute(select(User).where(User.email == email))
    if r.scalar_one_or_none() is not None:
        await consume_code(session, row)
        raise HTTPException(status_code=400, detail="Аккаунт уже существует.")
    now = datetime.now(timezone.utc)
    user = User(
        email=email,
        hashed_password=None,
        email_verified=True,
        telegram_id=telegram_id,
        telegram_username=None,
        terms_accepted_at=now,
        privacy_accepted_at=now,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    user.last_login_at = datetime.now(timezone.utc)
    await session.commit()
    await consume_code(session, row)
    return TokenResponse(access_token=_create_access_token(str(user.id)))


@router.post("/telegram/link-by-code", response_model=dict)
async def link_telegram_by_code(
    data: LinkTelegramByCodeBody,
    _: bool = Depends(_require_bot_token),
    session: AsyncSession = Depends(get_async_session),
):
    """Bot calls when user entered link code. Links telegram_id to user_id from code."""
    row = await verify_code(session, TYPE_TELEGRAM_LINK, data.code)
    if not row or not row.user_id:
        raise HTTPException(status_code=400, detail="Неверный или истёкший код")
    r = await session.execute(select(User).where(User.id == row.user_id))
    user = r.scalar_one_or_none()
    if not user:
        await consume_code(session, row)
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if user.is_blocked:
        raise HTTPException(status_code=403, detail="Аккаунт заблокирован")
    if user.telegram_id is not None:
        await consume_code(session, row)
        raise HTTPException(status_code=400, detail="К аккаунту уже привязан Telegram")
    r = await session.execute(select(User).where(User.telegram_id == data.telegram_id))
    if r.scalar_one_or_none() is not None:
        await consume_code(session, row)
        raise HTTPException(status_code=400, detail="Этот Telegram уже привязан к другому аккаунту")
    user.telegram_id = data.telegram_id
    user.telegram_username = (data.username or "").strip().lstrip("@") or None
    await session.commit()
    await consume_code(session, row)
    return {"ok": True, "message": "Telegram привязан"}


@router.post("/telegram/request-link-code", response_model=dict)
async def request_link_code(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Logged-in user requests code to enter in bot. Returns code to display on site."""
    if user.telegram_id is not None:
        raise HTTPException(status_code=400, detail="Telegram уже привязан")
    code = await create_code(
        session,
        TYPE_TELEGRAM_LINK,
        contact=str(user.id),
        user_id=user.id,
    )
    return {
        "code": code,
        "expires_minutes": settings.verification_code_expire_minutes_telegram,
        "detail": "Введите этот код в боте в Telegram",
    }


@router.post("/request-link-email", response_model=dict)
async def request_link_email(
    data: RequestLinkEmailBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Отправить код на почту для привязки её к аккаунту (уведомления). Для аккаунтов, зарегистрированных через Telegram."""
    if not user.is_telegram_only():
        raise HTTPException(
            status_code=400,
            detail="Привязка почты через код только для аккаунтов, зарегистрированных через Telegram. Ваш аккаунт уже использует почту.",
        )
    if user.notification_email and user.notification_email == data.email:
        raise HTTPException(status_code=400, detail="Эта почта уже привязана")
    code = await create_code(
        session,
        TYPE_EMAIL_LINK,
        contact=data.email,
        user_id=user.id,
    )
    if not send_email_link_code_email(data.email, code):
        raise HTTPException(
            status_code=503,
            detail="Не удалось отправить письмо. Проверьте настройки SMTP на сервере.",
        )
    return {
        "message": "ok",
        "detail": "Код отправлен на указанную почту. Введите его ниже.",
    }


@router.post("/verify-link-email", response_model=dict)
async def verify_link_email(
    data: VerifyLinkEmailBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Подтвердить привязку почты по коду из письма."""
    row = await verify_code(session, TYPE_EMAIL_LINK, data.code, data.email)
    if not row or row.user_id != user.id:
        raise HTTPException(status_code=400, detail="Неверный или истёкший код")
    user.notification_email = data.email
    await session.commit()
    await consume_code(session, row)
    return {"message": "ok", "detail": "Почта привязана. Уведомления будут приходить на неё."}


@router.post("/login-telegram", response_model=TokenResponse)
async def login_telegram(
    payload: TelegramAuthPayload,
    session: AsyncSession = Depends(get_async_session),
):
    """Login via Telegram Login Widget. Returns JWT."""
    if not _verify_telegram_widget(payload):
        raise HTTPException(status_code=401, detail="Неверные данные Telegram")
    r = await session.execute(select(User).where(User.telegram_id == payload.id))
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="Сначала зарегистрируйтесь через бота (получите код и введите на сайте)",
        )
    if user.is_blocked:
        raise HTTPException(status_code=403, detail="Аккаунт заблокирован")
    if not getattr(user, "is_active", True):
        raise HTTPException(status_code=403, detail="Аккаунт деактивирован")
    user.last_login_at = datetime.now(timezone.utc)
    await session.commit()
    return TokenResponse(access_token=_create_access_token(str(user.id)))


@router.post("/telegram/login-by-code", response_model=TokenResponse)
async def login_by_telegram_code(
    data: LoginByTelegramCodeBody,
    session: AsyncSession = Depends(get_async_session),
):
    """Вход по коду из Telegram-бота (для уже зарегистрированных)."""
    row = await verify_code(session, TYPE_TELEGRAM_REGISTER, data.code, contact=None)
    if not row:
        raise HTTPException(
            status_code=400,
            detail="Неверный или истёкший код. Получите новый в боте.",
        )
    telegram_id = int(row.contact)
    r = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = r.scalar_one_or_none()
    await consume_code(session, row)
    if not user:
        raise HTTPException(
            status_code=400,
            detail="Аккаунт не найден. Сначала зарегистрируйтесь (введите этот код на странице регистрации).",
        )
    if user.is_blocked:
        raise HTTPException(status_code=403, detail="Аккаунт заблокирован")
    if not getattr(user, "is_active", True):
        raise HTTPException(status_code=403, detail="Аккаунт деактивирован")
    user.last_login_at = datetime.now(timezone.utc)
    await session.commit()
    return TokenResponse(access_token=_create_access_token(str(user.id)))
