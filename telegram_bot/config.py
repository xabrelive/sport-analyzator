"""Настройки бота из переменных окружения."""
import os
from pathlib import Path

# Загружаем .env из папки telegram_bot (при локальном запуске)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


# Токен бота от @BotFather (обязательно)
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")

# URL бэкенда для POST /api/v1/auth/telegram/create-code
BACKEND_URL = env("BACKEND_URL", "http://localhost:11001").rstrip("/")

# Имя бота без @ (для текста в сообщениях)
TELEGRAM_BOT_USERNAME = env("TELEGRAM_BOT_USERNAME", "PingWin")

# URL сайта для ссылок в сообщениях пользователям. Всегда публичный домен, не localhost.
_PUBLIC_DEFAULT = "https://pingwin.pro"
_raw = env("FRONTEND_PUBLIC_URL") or env("FRONTEND_URL") or _PUBLIC_DEFAULT
FRONTEND_URL = _raw.rstrip("/")
if "localhost" in FRONTEND_URL or "127.0.0.1" in FRONTEND_URL:
    FRONTEND_URL = _PUBLIC_DEFAULT

# Режимы: user_notifications (основной бот) | channel_only (канальный бот)
BOT_MODE = env("BOT_MODE", "user_notifications").lower()
CHANNEL_BOT_DM_REPLY = env(
    "CHANNEL_BOT_DM_REPLY",
    "Этот бот публикует сообщения только в канал. Все настройки доступны на https://pingwin.pro",
)
