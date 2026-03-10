"""Auth request/response schemas."""
from pydantic import BaseModel, EmailStr, Field


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)
    accept_terms: bool = False
    accept_privacy: bool = False


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class VerifyEmailBody(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=4, max_length=10)


class ResendVerificationCodeBody(BaseModel):
    email: EmailStr


class RequestPasswordResetBody(BaseModel):
    email: EmailStr


class ResetPasswordBody(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=4, max_length=10)
    new_password: str = Field(..., min_length=6)


# Telegram Login Widget (frontend sends this after user clicks "Login with Telegram")
class TelegramAuthPayload(BaseModel):
    id: int
    first_name: str = ""
    last_name: str = ""
    username: str | None = None
    photo_url: str | None = None
    auth_date: int
    hash: str


# User on site enters code received from bot (registration or link)
class VerifyTelegramCodeBody(BaseModel):
    code: str = Field(..., min_length=4, max_length=10)
    accept_terms: bool = False
    accept_privacy: bool = False


# Login by code from Telegram bot (existing user)
class LoginByTelegramCodeBody(BaseModel):
    code: str = Field(..., min_length=4, max_length=10)


# Bot calls API to create code; backend returns code to send to user
class CreateTelegramCodeBody(BaseModel):
    telegram_id: int
    username: str | None = None
    # telegram_register | telegram_link (for link, bot must send user_id from session/token — we use header or body)
    purpose: str = "telegram_register"


# For telegram_link: bot sends code + telegram_id after user entered code in bot
class LinkTelegramByCodeBody(BaseModel):
    code: str = Field(..., min_length=4, max_length=10)
    telegram_id: int
    username: str | None = None


# Request new code for linking (logged-in user); backend creates code and returns it for user to type in bot
# No body needed — user from JWT


class RequestLinkEmailBody(BaseModel):
    email: EmailStr


class VerifyLinkEmailBody(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=4, max_length=10)
