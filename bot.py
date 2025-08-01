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

# Create application
app = ApplicationBuilder().token(BOT_TOKEN).build()
register_handlers(app)

# Set webhook and run app
async def setup():
    logger.info("🔗 Setting webhook...")
    await app.bot.set_webhook(WEBHOOK_URL)

logger.info("🚀 Starting bot with webhook...")

app.run_webhook(
    listen="0.0.0.0",
    port=PORT,
    webhook_url=WEBHOOK_URL,
    on_startup=setup
)
