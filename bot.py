import logging
from telegram.ext import ApplicationBuilder
from config import BOT_TOKEN
from handlers import register_handlers

# 🧾 Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🚀 Main
def main():
    print("🟢 bot.py is starting...")

    # Build app
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    print("📦 Registering handlers...")
    register_handlers(app)

    print("🚀 Launching app.run_polling()...")
    app.run_polling()

if __name__ == "__main__":
    main()
