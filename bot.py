# bot.py

import os
import sys
import traceback
import asyncio
import logging

from telegram.ext import ApplicationBuilder

from config import BOT_TOKEN, ADMIN_IDS
from handlers import register_handlers
from database import initialize_db
# Guarded import for sheets worker (so Google/Sheets problems won't crash startup)
try:
    from sheets_worker import sheets_worker
except Exception as _e:
    print("⚠️ sheets_worker import failed (will skip starting it):", _e)
    sheets_worker = None

# Recreate Google service account file from Railway environment variable (if present)
_sa = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
if _sa:
    try:
        with open("service_account.json", "w", encoding="utf-8") as f:
            f.write(_sa)
    except Exception as e:
        print("⚠️ Failed to write service_account.json:", e)

# Initialize DB
initialize_db()

# 🧾 Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ===== Admin error reporting (moved OUTSIDE of main) =====
# Helper: send text to all admins (async)
async def _notify_admins(bot, text: str):
    CHUNK = 3500
    for admin in ADMIN_IDS:
        try:
            for i in range(0, len(text), CHUNK):
                await bot.send_message(chat_id=admin, text=text[i : i + CHUNK])
        except Exception as e:
            logging.exception("Failed to notify admin %s: %s", admin, e)


# Create an asyncio exception handler that forwards message to admins
def _make_loop_exception_handler(bot):
    def _handler(loop, context):
        try:
            exc = context.get("exception")
            header = "⚠️ *Unhandled exception in asyncio task*"
            if exc:
                tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            else:
                tb = context.get("message", str(context))
            text = f"{header}\n\n```\n{tb}\n```"
            loop.call_soon_threadsafe(asyncio.create_task, _notify_admins(bot, text))
        except Exception:
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
            loop.call_soon_threadsafe(
                asyncio.create_task,
                _notify_admins(self.bot, f"🛑 *Log ERROR*\n\n```\n{msg}\n```"),
            )
        except Exception:
            logging.exception("Failed to emit admin log")


# Call this helper after building app and registering handlers
def setup_admin_reporting(app):
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

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        # .post_init(on_startup)  # optional startup hook if you prefer
        .build()
    )

    print("📦 Registering handlers...")
    register_handlers(app)

    # Start sheets worker only if it imported successfully
    if sheets_worker:
        try:
            # schedule the worker in PTB's event loop
            app.create_task(sheets_worker(app.bot))
            print("🟢 Sheets worker scheduled (in-app task).")
        except Exception as e:
            print("⚠️ Failed to schedule sheets_worker:", e)

    # Setup admin reporting now that app is built and handlers are registered
    try:
        setup_admin_reporting(app)
        print("🟢 Admin reporting set up.")
    except Exception as e:
        print("⚠️ Failed to set up admin reporting:", e)
        logger.exception("setup_admin_reporting failed: %s", e)

    print("🚀 Launching app.run_polling()...")
    app.run_polling()


if __name__ == "__main__":
    main()
