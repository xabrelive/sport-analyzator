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

# URL сайта, куда вводить код
FRONTEND_URL = env("FRONTEND_URL", "https://pingwin.pro").rstrip("/")
