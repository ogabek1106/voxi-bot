# bot.py

import os
import logging
import asyncio
from telegram.ext import ApplicationBuilder
from config import BOT_TOKEN
from handlers import register_handlers

# 🌍 Railway Webhook URL and Port
WEBHOOK_URL = f"https://worker-production-78ca.up.railway.app/{BOT_TOKEN}"
PORT = int(os.environ.get("PORT", 8080))

# 🧾 Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🚀 Async app launcher
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    register_handlers(app)

    logger.info("🔗 Setting webhook...")
    await app.bot.set_webhook(WEBHOOK_URL)

    logger.info("🚀 Starting bot with webhook...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()  # Needed to trigger updates in webhook mode
    await app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=WEBHOOK_URL,
        stop_signals=None  # Prevents Railway from messing with signals
    )

if __name__ == "__main__":
    asyncio.run(main())
