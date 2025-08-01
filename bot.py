# bot.py

import os
import logging
from telegram.ext import ApplicationBuilder
from config import BOT_TOKEN
from handlers import register_handlers

# 🌍 Railway Webhook URL and Port
WEBHOOK_URL = f"https://worker-production-78ca.up.railway.app/{BOT_TOKEN}"
PORT = int(os.environ.get("PORT", 8080))

# 🧾 Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🚀 Main function (Railway-friendly, no asyncio.run)
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    register_handlers(app)

    async def setup(app):
        logger.info("🔗 Setting webhook...")
        await app.bot.set_webhook(WEBHOOK_URL)

    app.post_init = setup

    logger.info("🚀 Starting bot with webhook...")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=WEBHOOK_URL,
        stop_signals=None
    )

if __name__ == "__main__":
    main()
