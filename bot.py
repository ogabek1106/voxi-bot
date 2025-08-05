import os
import logging
from telegram.ext import ApplicationBuilder
from telegram.error import RetryAfter, TimedOut
from config import BOT_TOKEN, ADMIN_IDS
from handlers import register_handlers

PORT = int(os.environ.get("PORT", 8080))
WEBHOOK_URL = "https://worker-production-78ca.up.railway.app/webhook"

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🔔 Notify Admin
async def notify_admin(app, message: str):
    try:
        for admin_id in ADMIN_IDS:
            await app.bot.send_message(chat_id=admin_id, text=message)
    except Exception as e:
        print(f"❌ Failed to notify admin in chat: {e}")

# 🔁 Retry Webhook Setup
async def set_webhook_with_retry(app):
    print("🔗 Setting webhook (post_init)...")
    for attempt in range(3):
        try:
            await app.bot.set_webhook(WEBHOOK_URL)
            msg = "✅ Webhook set successfully!"
            print(msg)
            await notify_admin(app, msg)
            return
        except (RetryAfter, TimedOut) as e:
            msg = f"⚠️ Timeout setting webhook, retrying... ({attempt + 1}/3)"
            print(msg)
            await notify_admin(app, msg)
            await asyncio.sleep(3)
        except Exception as e:
            error_msg = f"❌ Failed to set webhook:\n{str(e)}"
            print(error_msg)
            await notify_admin(app, error_msg)
            break

# 🚀 Main
def main():
    print("🟢 bot.py starting...")

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    register_handlers(app)

    # ✅ Use post_init instead of asyncio.run()
    async def post_init(app):
        await set_webhook_with_retry(app)

    app.post_init = post_init

    print("🚀 Launching webhook app...")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=WEBHOOK_URL
    )

if __name__ == "__main__":
    main()
