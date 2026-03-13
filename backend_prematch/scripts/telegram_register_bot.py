#!/usr/bin/env python3
"""
Telegram bot for PingWin registration.
User sends /start -> bot asks date of birth (YYYY-MM-DD) -> optional email -> calls backend API.
Run: TELEGRAM_BOT_TOKEN=... BACKEND_URL=http://localhost:12000 python -m scripts.telegram_register_bot
"""
from datetime import datetime
import logging
import os

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:12000").rstrip("/")

DOB, EMAIL = 1, 2


def parse_date(text: str) -> datetime | None:
    try:
        d = datetime.strptime(text.strip(), "%Y-%m-%d")
        if d.date() > datetime.now().date():
            return None
        return d
    except ValueError:
        return None


async def link_by_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Привязка по коду: пользователь отправил 6-значный код с сайта."""
    code = update.message.text.strip()
    user = update.effective_user
    if not user:
        await update.message.reply_text("Ошибка: не удалось определить пользователя.")
        return
    headers = {"Content-Type": "application/json", "X-Bot-Token": TELEGRAM_BOT_TOKEN}
    payload = {
        "code": code,
        "telegram_id": user.id,
        "username": user.username,
    }
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{BACKEND_URL}/api/v1/auth/link-telegram-by-code",
                json=payload,
                headers=headers,
                timeout=10.0,
            )
        if r.status_code == 200:
            await update.message.reply_text("Telegram привязан к вашему аккаунту. Уведомления о прогнозах будут приходить только вам в этот чат.")
        else:
            err = r.json().get("detail", r.text) if r.headers.get("content-type", "").startswith("application/json") else r.text
            await update.message.reply_text(f"Не удалось привязать: {err}\n\nЗапросите новый код в личном кабинете на сайте.")
    except Exception as e:
        logger.exception("link-telegram-by-code request failed: %s", e)
        await update.message.reply_text("Сервис временно недоступен. Попробуйте позже.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Привязка Telegram к аккаунту (ссылка из личного кабинета)
    if context.args and context.args[0].startswith("link_"):
        token = context.args[0][5:]
        user = update.effective_user
        if not user:
            await update.message.reply_text("Ошибка: не удалось определить пользователя.")
            return ConversationHandler.END
        headers = {"Content-Type": "application/json", "X-Bot-Token": TELEGRAM_BOT_TOKEN}
        payload = {
            "token": token,
            "telegram_id": user.id,
            "username": user.username,
        }
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"{BACKEND_URL}/api/v1/auth/link-telegram",
                    json=payload,
                    headers=headers,
                    timeout=10.0,
                )
            if r.status_code == 200:
                await update.message.reply_text("Telegram привязан к вашему аккаунту. Уведомления будут приходить только вам в этот чат.")
            else:
                err = r.json().get("detail", r.text) if r.headers.get("content-type", "").startswith("application/json") else r.text
                await update.message.reply_text(f"Не удалось привязать: {err}")
        except Exception as e:
            logger.exception("link-telegram request failed: %s", e)
            await update.message.reply_text("Сервис временно недоступен. Попробуйте позже.")
        return ConversationHandler.END

    # Регистрация нового пользователя
    await update.message.reply_text(
        "Подтвердите регистрацию в PingWin.\n\n"
        "Укажите дату рождения в формате ГГГГ-ММ-ДД (например 1990-05-15):"
    )
    return DOB


async def receive_dob(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("Введите дату в формате ГГГГ-ММ-ДД.")
        return DOB
    dob = parse_date(text)
    if not dob:
        await update.message.reply_text("Неверный формат или дата в будущем. Введите ГГГГ-ММ-ДД.")
        return DOB
    context.user_data["date_of_birth"] = dob.strftime("%Y-%m-%d")
    await update.message.reply_text(
        "Дата рождения сохранена.\n\n"
        "Укажите email (или отправьте минус «-» чтобы пропустить):"
    )
    return EMAIL


async def receive_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    email = None if text == "-" or not text else text
    if email and "@" not in email:
        await update.message.reply_text("Введите корректный email или «-» чтобы пропустить.")
        return EMAIL

    user = update.effective_user
    if not user:
        await update.message.reply_text("Ошибка: не удалось определить пользователя.")
        return ConversationHandler.END

    payload = {
        "telegram_id": user.id,
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "username": user.username,
        "date_of_birth": context.user_data.get("date_of_birth"),
        "email": email,
    }
    headers = {"Content-Type": "application/json", "X-Bot-Token": TELEGRAM_BOT_TOKEN}

    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{BACKEND_URL}/api/v1/auth/register-telegram",
                json=payload,
                headers=headers,
                timeout=10.0,
            )
        if r.status_code == 200:
            await update.message.reply_text(
                "Вы зарегистрированы.\n\n"
                "Теперь на сайте PingWin нажмите «Войти через Telegram» — вы войдёте автоматически."
            )
        else:
            err = r.json().get("detail", r.text)
            await update.message.reply_text(f"Ошибка регистрации: {err}")
    except Exception as e:
        logger.exception("register-telegram request failed")
        await update.message.reply_text("Сервис временно недоступен. Попробуйте позже.")
    finally:
        context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Регистрация отменена.")
    return ConversationHandler.END


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN environment variable")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    # Привязка по коду (6 цифр) — обрабатываем до регистрации, чтобы код с сайта сработал
    app.add_handler(
        MessageHandler(filters.Regex(r"^\d{6}$"), link_by_code),
    )
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            DOB: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_dob)],
            EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_email)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
