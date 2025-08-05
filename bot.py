import os
import logging
from telegram.ext import ApplicationBuilder
from config import BOT_TOKEN
from handlers import register_handlers

PORT = int(os.environ.get("PORT", 8080))
WEBHOOK_URL = "https://worker-production-78ca.up.railway.app/webhook"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    print("🟢 Minimal bot.py starting...")

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    register_handlers(app)

    async def set_hook():
        print("🔗 Setting webhook (before run)...")
        await app.bot.set_webhook(WEBHOOK_URL)

    import asyncio
    asyncio.run(set_hook())  # Set webhook BEFORE running

    print("🚀 Launching minimal webhook app...")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=WEBHOOK_URL
    )

if __name__ == "__main__":
    main()
