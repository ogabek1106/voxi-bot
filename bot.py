# bot.py

import os
import logging
from telegram.ext import ApplicationBuilder
from config import BOT_TOKEN
from handlers import register_handlers

# Set Railway domain
WEBHOOK_URL = f"https://worker-production-78ca.up.railway.app/{BOT_TOKEN}"
PORT = int(os.environ.get("PORT", 8080))

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def setup_webhook(app):
    logger.info("🔗 Setting webhook...")
    await app.bot.set_webhook(WEBHOOK_URL)

# Main execution
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    register_handlers(app)

    # Run webhook after setting it manually
    async def run():
        await setup_webhook(app)
        logger.info("🚀 Starting bot with webhook...")
        await app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=WEBHOOK_URL,
        )

    import asyncio
    asyncio.run(run())
