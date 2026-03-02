"""
Telegram bot: receives signals from backend (Redis or HTTP) and forwards to chats.
Run as separate process. For MVP, can be triggered by Celery task that calls Telegram API directly;
this service is for interactive commands and optional queue consumption.
"""
import asyncio
import os

# Optional: run bot with python-telegram-bot for /start, /help, subscribe
try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler, ContextTypes
except ImportError:
    Update = None
    Application = None


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN not set; bot will not start.")
        return
    if Application is None:
        print("Install python-telegram-bot to run the bot.")
        return

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "Sport Analyzator — сигналы value по настольному теннису. "
            "Подпишите бота на канал/чат для получения сигналов."
        )

    async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "/start — приветствие\n"
            "/help — эта справка"
        )

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
