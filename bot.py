# bot.py

import logging
from telegram.ext import ApplicationBuilder
from config import BOT_TOKEN
from handlers import register_handlers
from database import initialize_db
from sheets_worker import sheets_worker
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


# This runs inside PTB's event loop when the app starts
# async def on_startup(app):
   # print("🟢 Launching Google Sheets worker...")
    # Use app.create_task so the worker runs in the same loop as PTB
    # app.create_task(sheets_worker(app.bot))


# 🚀 Main
def main():
    print("🟢 bot.py is starting...")

    # Build app and register a startup hook that will start the worker
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        #.post_init(on_startup)
        .build()
    )

    print("📦 Registering handlers...")
    register_handlers(app)

    print("🚀 Launching app.run_polling()...")
    app.run_polling()


if __name__ == "__main__":
    main()
