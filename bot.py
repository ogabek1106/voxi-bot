# bot.py — resilient, minimal polling launcher for Voxi bot (ready to drop in)
import os
import sys
import traceback
import asyncio
import logging
from typing import Optional

from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes

from config import BOT_TOKEN, ADMIN_IDS

# Database init: try multiple common names for compatibility across your copies
# Also perform a lightweight migration to ensure countdowns has message_id column
try:
    # preferred name used in many of your earlier files
    from database import initialize_db as _init_db
    from database import DB_PATH as _DB_PATH  # use DB_PATH for migrations if available
except Exception:
    try:
        from database import init_db as _init_db
        from database import DB_PATH as _DB_PATH
    except Exception:
        _init_db = None
        _DB_PATH = os.getenv("DB_PATH", "data.db")

# Run DB init if available (best-effort)
if _init_db:
    try:
        _init_db()
    except Exception:
        # ensure startup continues even if DB init has issues (we log below)
        pass

# Lightweight migration: ensure countdowns table has message_id column
# This is safe: if column exists, we skip; if countdowns doesn't exist, skip.
try:
    import sqlite3

    conn = sqlite3.connect(_DB_PATH)
    c = conn.cursor()
    # Check if countdowns table exists
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='countdowns'")
    if c.fetchone():
        # Check columns
        c.execute("PRAGMA table_info(countdowns)")
        cols = [r[1] for r in c.fetchall()]  # name is index 1
        if "message_id" not in cols:
            try:
                c.execute("ALTER TABLE countdowns ADD COLUMN message_id INTEGER")
                conn.commit()
                logging.getLogger(__name__).info("DB migration: added message_id to countdowns")
            except Exception:
                # Some SQLite older versions or locked DBs may fail; continue silently
                logging.getLogger(__name__).exception("DB migration attempt to add message_id failed")
    conn.close()
except Exception:
    logging.getLogger(__name__).exception("Failed to run DB migration check")

# ---------------- Logging (DEBUG to capture detailed logs) ----------------
# Use DEBUG so handlers' debug logs are visible in Railway logs.
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Make httpx and telegram verbose too (helps diagnose Network/Read errors)
logging.getLogger("httpx").setLevel(logging.DEBUG)
logging.getLogger("telegram").setLevel(logging.DEBUG)
# keep urllib3 less noisy by default
logging.getLogger("urllib3").setLevel(logging.INFO)


# Try to import Request (may be unavailable in some environments / package versions)
try:
    from telegram.request import Request  # type: ignore
except Exception:
    Request = None  # fallback to default Request inside PTB


# ---------------- Admin notifications ----------------
async def _notify_admins(bot, text: str):
    """Send a long text to every admin (chunked)."""
    CHUNK = 3500
    for admin in ADMIN_IDS:
        try:
            for i in range(0, len(text), CHUNK):
                await bot.send_message(chat_id=admin, text=text[i : i + CHUNK], parse_mode=None)
        except Exception:
            logger.exception("Failed to notify admin %s", admin)


def _safe_schedule_coro(coro):
    """
    Try to schedule a coroutine on the running loop.
    If scheduling is impossible (no loop or loop closed), log and return False.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("loop is closed")
        loop.call_soon_threadsafe(asyncio.create_task, coro)
        return True
    except Exception:
        logger.debug("Could not schedule coroutine; loop closed or unavailable.")
        return False


def _make_loop_exception_handler(bot):
    def _handler(loop, context):
        try:
            exc = context.get("exception")
            header = "⚠️ Unhandled exception in asyncio task"
            if exc:
                tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            else:
                tb = str(context)
            text = f"{header}\n\n```\n{tb}\n```"
            _safe_schedule_coro(_notify_admins(bot, text))
        except Exception:
            logger.exception("Error in loop exception handler")

    return _handler


def _install_sys_excepthook(bot):
    def excepthook(type_, value, tb):
        try:
            tb_text = "".join(traceback.format_exception(type_, value, tb))
            text = "⚠️ Uncaught exception\n\n```\n" + tb_text + "\n```"
            _safe_schedule_coro(_notify_admins(bot, text))
        except Exception:
            logger.exception("Failed to report uncaught exception")
        # call original hook for visibility in logs
        try:
            sys.__excepthook__(type_, value, tb)
        except Exception:
            pass

    sys.excepthook = excepthook


class AdminLogHandler(logging.Handler):
    """Logging handler that notifies admins on errors, but is safe if loop is closed."""

    def __init__(self, bot):
        super().__init__(level=logging.ERROR)
        self.bot = bot

    def emit(self, record):
        try:
            msg = self.format(record)
            scheduled = _safe_schedule_coro(_notify_admins(self.bot, f"🛑 Log ERROR\n\n```\n{msg}\n```"))
            if not scheduled:
                # fallback: print to stderr so Railway logs include it
                try:
                    print("AdminLogHandler fallback — Log ERROR:\n", msg, file=sys.stderr)
                except Exception:
                    pass
        except Exception:
            try:
                print("AdminLogHandler.emit failed for record:", record, file=sys.stderr)
            except Exception:
                pass


# ---------------- Application error handler ----------------
async def error_handler(update: Optional[Update], context: ContextTypes.DEFAULT_TYPE) -> None:
    """Application-wide error handler — attempt to notify admins (best-effort)."""
    try:
        logger.exception("Application caught an exception: %s", context.error)
        tb = ""
        if getattr(context, "error", None):
            tb = "".join(traceback.format_exception(type(context.error), context.error, context.error.__traceback__))
        else:
            tb = str(context)
        text = f"⚠️ Application error\n\n```\n{tb[:7000]}\n```"
        bot = getattr(context, "bot", None)
        if bot:
            _safe_schedule_coro(_notify_admins(bot, text))
    except Exception:
        logger.exception("Failed in application-level error handler")


def setup_admin_reporting(app):
    """Install admin reporting: loop handler, sys.excepthook, and log handler."""
    bot = app.bot
    # install loop exception handler if possible
    try:
        loop = asyncio.get_event_loop()
        if not loop.is_closed():
            loop.set_exception_handler(_make_loop_exception_handler(bot))
    except Exception:
        logger.debug("Could not set loop exception handler (no loop yet)")

    _install_sys_excepthook(bot)

    admin_handler = AdminLogHandler(bot)
    admin_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(admin_handler)


# ---------------- Main ----------------
def main():
    logger.info("🟢 bot.py is starting...")

    # Build optional tuned Request (if available)
    REQUEST = None
    if Request is not None:
        try:
            REQUEST = Request(
                connect_timeout=10.0,
                read_timeout=40.0,
                pool_timeout=10.0,
                con_pool_size=16,
                http_version="1.1",
            )
            logger.info("Using custom Request with tuned timeouts.")
        except Exception:
            REQUEST = None
            logger.warning("Failed to create custom Request; falling back to defaults.")

    # Build Application (include .request(...) only if REQUEST is set)
    builder = ApplicationBuilder().token(BOT_TOKEN)
    if REQUEST is not None:
        try:
            builder = builder.request(REQUEST)
        except Exception:
            logger.warning("Builder.request(...) failed; continuing without custom Request.")
    app = builder.build()

    # Import handlers here (after app built so handlers can reference app if needed)
    try:
        from handlers import register_handlers  # local import to avoid circular issues
    except Exception:
        logger.exception("Failed to import handlers — make sure handlers.py exists and is valid")
        raise

    # global error handler
    app.add_error_handler(error_handler)

    logger.info("📦 Registering handlers...")
    register_handlers(app)

    # --- Ensure background worker from handlers is scheduled robustly ---
    # Import the worker and schedule it once (idempotent).
    try:
        from handlers import _countdown_worker
        # avoid double-scheduling: check a flag stored on the app instance
        if not getattr(app, "_countdown_worker_scheduled", False):
            try:
                app.create_task(_countdown_worker(app))
                app._countdown_worker_scheduled = True
                logger.info("Scheduled countdown worker (explicit from bot.py).")
            except Exception:
                logger.exception("Failed to schedule countdown worker via app.create_task().")
        else:
            logger.debug("Countdown worker already scheduled on app; skipping duplicate schedule.")
    except Exception:
        logger.exception("Could not import countdown worker from handlers — worker not scheduled.")

    try:
        setup_admin_reporting(app)
        logger.info("🟢 Admin reporting set up.")
    except Exception:
        logger.exception("setup_admin_reporting failed")

    logger.info("🚀 Launching app.run_polling()...")
    app.run_polling(poll_interval=0.0)


if __name__ == "__main__":
    main()
