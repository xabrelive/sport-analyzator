"""Auth schemas."""
from datetime import date

from pydantic import BaseModel, EmailStr, Field


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class VerifyEmailQuery(BaseModel):
    token: str


# Telegram: from bot after user confirmed and sent DOB + optional email
class RegisterTelegramBody(BaseModel):
    telegram_id: int
    first_name: str = ""
    last_name: str = ""
    username: str | None = None
    date_of_birth: date | None = None
    email: EmailStr | None = None


# Telegram Login Widget callback payload (from frontend)
class TelegramAuthPayload(BaseModel):
    id: int  # telegram user id
    first_name: str = ""
    last_name: str = ""
    username: str | None = None
    photo_url: str | None = None
    auth_date: int
    hash: str


# Привязка Telegram к аккаунту (вызов от бота после /start link_XXX)
class LinkTelegramBody(BaseModel):
    token: str
    telegram_id: int
    username: str | None = None


# Привязка по коду: пользователь получает код на сайте и пишет его боту
class LinkTelegramByCodeBody(BaseModel):
    code: str
    telegram_id: int
    username: str | None = None
