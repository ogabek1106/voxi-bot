import os
import logging
from telegram.ext import ApplicationBuilder
from config import BOT_TOKEN, ADMIN_IDS
from handlers import register_handlers

# 🌍 Webhook settings
WEBHOOK_PATH = f"/{BOT_TOKEN}"
WEBHOOK_URL = f"https://worker-production-78ca.up.railway.app{WEBHOOK_PATH}"
PORT = int(os.environ.get("PORT", 8080))

# 🧾 Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🚀 Main
def main():
    print("🟢 bot.py is starting...")

    # Build the bot
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    print("📦 Registering handlers...")
    register_handlers(app)

    # Set webhook and notify admin
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

    print("🚀 Launching app.run_webhook...")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=WEBHOOK_URL,
        webhook_path=WEBHOOK_PATH,  # ✅ MUST be set!
        stop_signals=None
    )

if __name__ == "__main__":
    main()
