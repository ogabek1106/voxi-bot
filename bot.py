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


# ===== Admin error reporting (moved OUTSIDE of main) =====
import sys
import traceback
import asyncio
import logging
from config import ADMIN_IDS

# Helper: send text to all admins (async)
async def _notify_admins(bot, text: str):
    # chunk long text into smaller messages if needed
    CHUNK = 3500
    for admin in ADMIN_IDS:
        try:
            # split if too long
            for i in range(0, len(text), CHUNK):
                await bot.send_message(chat_id=admin, text=text[i:i+CHUNK])
        except Exception as e:
            # avoid infinite loops if send_message fails
            logging.exception("Failed to notify admin %s: %s", admin, e)

# Create an asyncio exception handler that forwards message to admins
def _make_loop_exception_handler(bot):
    def _handler(loop, context):
        try:
            # context may contain 'exception' or just message
            exc = context.get("exception")
            header = "⚠️ *Unhandled exception in asyncio task*"
            if exc:
                tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            else:
                tb = context.get("message", str(context))
            text = f"{header}\n\n```\n{tb}\n```"
            # schedule coroutine safely
            loop.call_soon_threadsafe(asyncio.create_task, _notify_admins(bot, text))
        except Exception:
            # last-resort log
            logging.exception("Error in loop exception handler")
    return _handler

# Install sys.excepthook to catch uncaught exceptions (threads, startup etc.)
def _install_sys_excepthook(bot):
    def excepthook(type_, value, tb):
        try:
            tb_text = "".join(traceback.format_exception(type_, value, tb))
            text = "⚠️ *Uncaught exception*\n\n```\n" + tb_text + "\n```"
            loop = asyncio.get_event_loop()
            loop.call_soon_threadsafe(asyncio.create_task, _notify_admins(bot, text))
        except Exception:
            logging.exception("Failed to report uncaught exception")
        # still print to stderr for local debugging
        sys.__excepthook__(type_, value, tb)
    sys.excepthook = excepthook

# Logging handler — forwards ERROR/CRITICAL log records to admins
class AdminLogHandler(logging.Handler):
    def __init__(self, bot):
        super().__init__(level=logging.ERROR)
        self.bot = bot

    def emit(self, record):
        try:
            msg = self.format(record)
            loop = asyncio.get_event_loop()
            loop.call_soon_threadsafe(asyncio.create_task, _notify_admins(self.bot, f"🛑 *Log ERROR*\n\n```\n{msg}\n```"))
        except Exception:
            # if logging to admins fails, fallback to stderr
            logging.exception("Failed to emit admin log")

# Call this helper after building app and registering handlers
def setup_admin_reporting(app):
    # app.bot exists after build()
    bot = app.bot

    # 1) install asyncio loop exception handler
    loop = asyncio.get_event_loop()
    loop.set_exception_handler(_make_loop_exception_handler(bot))

    # 2) install sys.excepthook
    _install_sys_excepthook(bot)

    # 3) attach logging handler for ERRORs
    admin_handler = AdminLogHandler(bot)
    admin_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(admin_handler)

# ---------------- end of admin reporting block ----------------


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

    # Setup admin reporting now that app is built and handlers are registered
    setup_admin_reporting(app)

    print("🚀 Launching app.run_polling()...")
    app.run_polling()


if __name__ == "__main__":
    main()

