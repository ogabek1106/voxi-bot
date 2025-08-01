# bot.py

import os
import logging
import asyncio
from telegram.ext import ApplicationBuilder
from config import BOT_TOKEN
from handlers import register_handlers

# 🌐 Railway Webhook URL
WEBHOOK_URL = f"https://worker-production-78ca.up.railway.app/{BOT_TOKEN}"
PORT = int(os.environ.get("PORT", 8080))

# 🧾 Logger setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🛠️ Main async setup
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    register_handlers(app)

    logger.info("🔗 Setting webhook...")
    await app.bot.set_webhook(WEBHOOK_URL)

    logger.info("🚀 Starting bot with webhook...")
    await app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=WEBHOOK_URL,
    )

# 🔃 Start without asyncio.run (fixes Railway error)
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(main())
    loop.run_forever()
