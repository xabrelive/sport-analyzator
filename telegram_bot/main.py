"""
PingWin Telegram Bot.
Меню: код для регистрации и авторизации, привязать аккаунт, получить информацию.
"""
import asyncio
import logging
import sys

import httpx
from telegram import BotCommand, KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from config import (
    BACKEND_URL,
    FRONTEND_URL,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_BOT_USERNAME,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# Тексты кнопок меню (должны совпадать с клавиатурой)
BTN_GET_CODE = "Код для регистрации и авторизации"
BTN_GET_INFO = "Получить информацию"
BTN_LINK_ACCOUNT = "Привязать аккаунт"

# Клавиатура меню под полем ввода
MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton(BTN_GET_CODE)],
        [KeyboardButton(BTN_LINK_ACCOUNT)],
        [KeyboardButton(BTN_GET_INFO)],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)


async def request_registration_code(telegram_id: int, username: str | None) -> tuple[str | None, str]:
    """
    Запрос кода у бэкенда. Возвращает (code, error_message).
    Если code не None — ошибки нет. При ошибке соединения — одна повторная попытка.
    """
    url = f"{BACKEND_URL}/api/v1/auth/telegram/create-code"
    headers = {"Content-Type": "application/json", "X-Bot-Token": TELEGRAM_BOT_TOKEN}
    payload = {"telegram_id": telegram_id, "purpose": "telegram_register"}
    if username:
        payload["username"] = username

    async def _do_request() -> tuple[str | None, str]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=payload, headers=headers)
        if r.status_code != 200:
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            msg = data.get("detail", r.text or str(r.status_code))
            return None, msg
        data = r.json()
        code = data.get("code")
        if not code:
            return None, "Бэкенд не вернул код"
        return code, ""

    try:
        return await _do_request()
    except httpx.ConnectError as e:
        logger.warning("Backend unreachable (will retry once): %s", e)
        await asyncio.sleep(3)
        try:
            return await _do_request()
        except httpx.ConnectError as e2:
            logger.warning("Backend unreachable after retry: %s", e2)
            return None, "Сервис временно недоступен. Попробуйте позже."
    except Exception as e:
        logger.exception("Request code failed: %s", e)
        return None, "Ошибка при получении кода. Попробуйте позже."


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Приветствие и показ меню."""
    if not update.effective_user or not update.message:
        return
    await update.message.reply_text(
        "Привет! Я бот аналитики PingWin (pingwin.pro).\n\n"
        f"Выберите действие в меню ниже или используйте команды.",
        reply_markup=MENU_KEYBOARD,
    )


async def cmd_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Выдать код для регистрации на сайте (действует 10 минут)."""
    if not update.effective_user or not update.message:
        return
    user = update.effective_user
    telegram_id = user.id
    username = user.username

    await update.message.reply_text("Запрашиваю код для регистрации…", reply_markup=MENU_KEYBOARD)

    code, err = await request_registration_code(telegram_id, username)
    if err:
        await update.message.reply_text(f"❌ {err}")
        return

    text = (
        f"Ваш код для регистрации на {TELEGRAM_BOT_USERNAME}:\n\n"
        f"<b>{code}</b>\n\n"
        f"Введите этот код на сайте:\n{FRONTEND_URL}/register\n\n"
        "Код действует 10 минут."
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def fetch_bot_info_message() -> str:
    """Запросить сообщение «Получить информацию» с бэкенда."""
    url = f"{BACKEND_URL}/api/v1/auth/telegram/bot-info"
    headers = {"Content-Type": "application/json", "X-Bot-Token": TELEGRAM_BOT_TOKEN}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url, headers=headers)
        if r.status_code == 200:
            data = r.json()
            msg = (data.get("message") or "").strip()
            if msg:
                return msg
    except Exception as e:
        logger.warning("Failed to fetch bot info: %s", e)
    return "Здесь будет информация о сервисе PingWin."


async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Пункт «Получить информацию» — сообщение из админки."""
    if not update.message:
        return
    text = await fetch_bot_info_message()
    await update.message.reply_text(text, reply_markup=MENU_KEYBOARD)


async def cmd_link_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Инструкция: как привязать аккаунт по коду с сайта."""
    if not update.message:
        return
    settings_url = f"{FRONTEND_URL}/dashboard/settings"
    await update.message.reply_text(
        "Чтобы привязать этот Telegram к аккаунту на сайте:\n\n"
        "1. Откройте Настройки на сайте (нужно быть авторизованным).\n"
        f"2. Перейдите: {settings_url}\n"
        "3. В блоке «Telegram» нажмите «Получить код для привязки».\n"
        "4. Скопируйте код и введите его сюда в ответном сообщении.",
        reply_markup=MENU_KEYBOARD,
    )


async def link_by_code(telegram_id: int, username: str | None, code: str) -> tuple[bool, str]:
    """Вызов API привязки аккаунта по коду. Возвращает (success, message)."""
    url = f"{BACKEND_URL}/api/v1/auth/telegram/link-by-code"
    headers = {"Content-Type": "application/json", "X-Bot-Token": TELEGRAM_BOT_TOKEN}
    payload = {"code": code.strip(), "telegram_id": telegram_id}
    if username:
        payload["username"] = username
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=payload, headers=headers)
        if r.status_code == 200:
            return True, "Аккаунт привязан. Уведомления будут приходить сюда."
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        msg = data.get("detail", r.text or str(r.status_code))
        return False, msg
    except httpx.ConnectError:
        return False, "Сервис временно недоступен. Попробуйте позже."
    except Exception as e:
        logger.exception("link_by_code failed: %s", e)
        return False, "Ошибка при привязке. Попробуйте позже."


async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка нажатий кнопок меню и ввод кода для привязки."""
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if text == BTN_GET_CODE:
        await cmd_code(update, context)
        return
    if text == BTN_GET_INFO:
        await cmd_info(update, context)
        return
    if text == BTN_LINK_ACCOUNT:
        await cmd_link_account(update, context)
        return
    # Сообщение из одних цифр 4–10 символов — возможно код для привязки
    if text.isdigit() and 4 <= len(text) <= 10:
        user = update.effective_user
        if not user:
            return
        ok, msg = await link_by_code(user.id, user.username, text)
        if ok:
            await update.message.reply_text(f"✅ {msg}", reply_markup=MENU_KEYBOARD)
        else:
            await update.message.reply_text(f"❌ {msg}", reply_markup=MENU_KEYBOARD)


async def post_init(app: Application) -> None:
    """Установка списка команд в меню бота (кнопка «/» в чате)."""
    await app.bot.set_my_commands([
        BotCommand("start", "Старт / меню"),
        BotCommand("code", "Код для регистрации и авторизации"),
        BotCommand("link", "Привязать аккаунт по коду с сайта"),
        BotCommand("info", "Получить информацию"),
    ])


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не задан. Заполните .env")
        sys.exit(1)

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("code", cmd_code))
    app.add_handler(CommandHandler("link", cmd_link_account))
    app.add_handler(CommandHandler("info", cmd_info))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_button_handler))

    logger.info("Bot starting (BACKEND_URL=%s)", BACKEND_URL)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
