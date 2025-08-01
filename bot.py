import os
import logging
from telegram.ext import ApplicationBuilder
from config import BOT_TOKEN, ADMIN_IDS
from handlers import register_handlers

# 🌍 Railway Webhook URL and Port
WEBHOOK_URL = f"https://worker-production-78ca.up.railway.app/{BOT_TOKEN}"
PORT = int(os.environ.get("PORT", 8080))

# 🧾 Logger setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🚀 Main function
def main():
    print("🟢 bot.py is starting...")

    # 1. Build app
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # 2. Register handlers
    print("📦 Registering handlers...")
    register_handlers(app)

    # 3. Setup webhook and notify admin
    async def setup(app):
        print("🔗 Setting webhook...")
        await app.bot.set_webhook(WEBHOOK_URL)

        try:
            await app.bot.send_message(
                chat_id=list(ADMIN_IDS)[0],
                text="✅ Voxi bot deployed and webhook set!"
            )
            print("📩 Admin notified")
        except Exception as e:
            print(f"⚠️ Failed to notify admin: {e}")

    app.post_init = setup

    # 4. Run webhook server
    print("🚀 Launching app.run_webhook...")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=WEBHOOK_URL,
        stop_signals=None
    )

if __name__ == "__main__":
    main()
