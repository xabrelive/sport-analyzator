"""
Telegram bot: приветствие, привязка по ссылке (start=link_XXX) и по коду (6 цифр), уведомления.
"""
import logging
import os

try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
except ImportError:
    Update = None
    Application = None

try:
    import httpx
except ImportError:
    httpx = None

logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
BACKEND_URL = (os.environ.get("BACKEND_URL") or "http://localhost:12000").rstrip("/")


async def _link_by_token(update: Update, token: str) -> None:
    """Привязка по ссылке t.me/bot?start=link_XXX."""
    user = update.effective_user
    if not user or not update.message:
        return
    if not httpx:
        await update.message.reply_text("Сервис привязки недоступен.")
        return
    headers = {"Content-Type": "application/json", "X-Bot-Token": BOT_TOKEN}
    payload = {"token": token, "telegram_id": user.id, "username": user.username}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{BACKEND_URL}/api/v1/auth/link-telegram",
                json=payload,
                headers=headers,
                timeout=10.0,
            )
        if r.status_code == 200:
            await update.message.reply_text(
                "Telegram привязан к вашему аккаунту. Уведомления о прогнозах будут приходить в этот чат."
            )
        else:
            err = r.json().get("detail", r.text) if r.headers.get("content-type", "").startswith("application/json") else r.text
            await update.message.reply_text(f"Не удалось привязать: {err}\n\nЗапросите новую ссылку в личном кабинете на сайте.")
    except Exception as e:
        logger.exception("link-telegram request failed: %s", e)
        await update.message.reply_text("Сервис временно недоступен. Попробуйте позже.")


async def _link_by_code(update: Update, code: str) -> None:
    """Привязка по 6-значному коду с сайта."""
    user = update.effective_user
    if not user or not update.message:
        return
    if not httpx:
        await update.message.reply_text("Сервис привязки недоступен.")
        return
    headers = {"Content-Type": "application/json", "X-Bot-Token": BOT_TOKEN}
    payload = {"code": code.strip(), "telegram_id": user.id, "username": user.username}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{BACKEND_URL}/api/v1/auth/link-telegram-by-code",
                json=payload,
                headers=headers,
                timeout=10.0,
            )
        if r.status_code == 200:
            await update.message.reply_text(
                "Telegram привязан к вашему аккаунту. Уведомления о прогнозах будут приходить в этот чат."
            )
        else:
            err = r.json().get("detail", r.text) if r.headers.get("content-type", "").startswith("application/json") else r.text
            await update.message.reply_text(f"Не удалось привязать: {err}\n\nЗапросите новый код в личном кабинете на сайте.")
    except Exception as e:
        logger.exception("link-telegram-by-code request failed: %s", e)
        await update.message.reply_text("Сервис временно недоступен. Попробуйте позже.")


def main() -> None:
    if not BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN not set; bot will not start.")
        return
    if Application is None:
        print("Install python-telegram-bot to run the bot.")
        return
    if httpx is None:
        print("Install httpx for link-by-code/link-by-token.")
        return

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        # Привязка по ссылке из личного кабинета: t.me/bot?start=link_ТОКЕН
        if context.args and len(context.args) >= 1 and context.args[0].startswith("link_"):
            token = context.args[0][5:]  # после "link_"
            if token:
                await _link_by_token(update, token)
                return
        base_url = (
            os.environ.get("FRONTEND_PUBLIC_URL") or os.environ.get("FRONTEND_URL") or "https://pingwin.pro"
        ).rstrip("/")
        text = (
            "Этот бот — для уведомлений по аналитике (прогнозы, сигналы).\n\n"
            "Подключить уведомления в бота можно в личном кабинете на сайте:\n"
            f"{base_url}/me"
        )
        await update.message.reply_text(text)

    async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        base_url = (
            os.environ.get("FRONTEND_PUBLIC_URL") or os.environ.get("FRONTEND_URL") or "https://pingwin.pro"
        ).rstrip("/")
        await update.message.reply_text(
            "/start — приветствие и ссылка на сайт\n"
            "/help — эта справка\n\n"
            f"Подключить уведомления: {base_url}/me"
        )

    # Обработка 6-значного кода (привязка с сайта)
    async def on_six_digits(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message and update.message.text:
            await _link_by_code(update, update.message.text)

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.Regex(r"^\d{6}$"), on_six_digits))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
