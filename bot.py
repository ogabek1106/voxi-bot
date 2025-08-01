# bot.py

import os
import logging
from telegram.ext import ApplicationBuilder
from config import BOT_TOKEN
from handlers import register_handlers

# Set your Railway domain here
WEBHOOK_URL = f"https://worker-production-78ca.up.railway.app/{BOT_TOKEN}"
PORT = int(os.environ.get("PORT", 8080))

# Enable logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    register_handlers(app)

    # Set webhook URL
    logger.info("🔗 Setting webhook...")
    await app.bot.set_webhook(WEBHOOK_URL)

    # Start webhook server
    logger.info("🚀 Starting bot with webhook...")
    await app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=WEBHOOK_URL
    )

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
