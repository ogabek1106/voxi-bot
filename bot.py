# bot.py (fixed full file) — replace your existing bot.py with this
import os
import sys
import traceback
import asyncio
import logging
from typing import Optional

from telegram.request import Request
from telegram.ext import ApplicationBuilder
from telegram import Update
from telegram.ext import ContextTypes

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
                await bot.send_message(chat_id=admin, text=text[i : i + CHUNK], parse_mode=None)
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


# This runs inside PTB's event loop when the app starts
async def on_startup(app):
    """Run once when Application starts — schedule background tasks here."""
    # schedule the sheets worker inside the running loop (if available)
    if sheets_worker:
        try:
            # call sheets_worker(app.bot) as a long-running task
            app.create_task(sheets_worker(app.bot))
            print("🟢 Sheets worker scheduled (on_startup).")
        except Exception as e:
            print("⚠️ Failed to schedule sheets_worker in on_startup:", e)


# PTB application-wide error handler (so "No error handlers are registered" disappears)
async def error_handler(update: Optional[Update], context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler for the Application."""
    try:
        logger.exception("Application caught an exception: %s", context.error)
        # Notify admins with traceback (truncate to safe length)
        tb = "".join(traceback.format_exception(type(context.error), context.error, context.error.__traceback__)) if context.error else str(context)
        text = f"⚠️ *Application error*\n\n```\n{tb[:7000]}\n```"
        # use context.bot if available; otherwise nothing we can do
        bot = getattr(context, "bot", None)
        if bot:
            await _notify_admins(bot, text)
    except Exception:
        logger.exception("Failed in application-level error handler")


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

    # Build a more tolerant Request wrapper for httpx (used by PTB internally)
    # These values are intentionally generous to reduce ReadError on flaky networks.
    REQUEST = Request(
        connect_timeout=10.0,
        read_timeout=40.0,
        pool_timeout=10.0,
        con_pool_size=16,
        # Force HTTP/1.1 if your host has flaky HTTP/2 support (prevents some httpcore issues)
        http_version="1.1",
    )

    # Build Application with custom Request so polling uses our tuned httpx client
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .request(REQUEST)
        .post_init(on_startup)
        .build()
    )

    # Register a global error handler so exceptions are handled by our error_handler
    app.add_error_handler(error_handler)

    print("📦 Registering handlers...")
    register_handlers(app)

    # Setup admin reporting now that app is built and handlers are registered
    try:
        setup_admin_reporting(app)
        print("🟢 Admin reporting set up.")
    except Exception as e:
        print("⚠️ Failed to set up admin reporting:", e)
        logger.exception("setup_admin_reporting failed: %s", e)

    print("🚀 Launching app.run_polling()...")

    # run polling — this will use the Request configured above
    app.run_polling(poll_interval=0.0)


if __name__ == "__main__":
    main()
