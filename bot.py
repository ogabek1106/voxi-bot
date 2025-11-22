# bot.py

import logging
from telegram.ext import ApplicationBuilder
from config import BOT_TOKEN
from handlers import register_handlers
from database import initialize_db 
from sheets_worker import sheets_worker
import asyncio

import os

# Recreate Google service account file from Railway environment variable
_sa = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
if _sa:
    with open("service_account.json", "w", encoding="utf-8") as f:
        f.write(_sa)

initialize_db()

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

    # Start Google Sheets worker in background
    asyncio.create_task(sheets_worker(app.bot))

    print("🚀 Launching app.run_polling()...")
    app.run_polling()

if __name__ == "__main__":
    main()
