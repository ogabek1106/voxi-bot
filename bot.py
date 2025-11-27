# bot.py — minimal, polling-only launcher for your Voxi bot (safe loop handling)
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

# Initialize DB (creates tables if needed)
initialize_db()

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------- Admin notifications ----------------
async def _notify_admins(bot, text: str):
    CHUNK = 3500
    for admin in ADMIN_IDS:
        try:
            for i in range(0, len(text), CHUNK):
                await bot.send_message(chat_id=admin, text=text[i : i + CHUNK], parse_mode=None)
        except Exception:
            logger.exception("Failed to notify admin %s", admin)


def _safe_schedule_coro(coro):
    """
    Try to schedule a coroutine on the running loop in a safe way.
    If scheduling is impossible (no loop or loop closed), fallback to printing.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("loop is closed")
        loop.call_soon_threadsafe(asyncio.create_task, coro)
        return True
    except Exception:
        # fallback: cannot schedule the coroutine, print the message instead
        try:
            # Attempt to extract text from the coro if it's _notify_admins(bot, text)
            # Not guaranteed; we just log that notification couldn't be scheduled
            logger.error("Could not schedule admin notification; loop closed or unavailable.")
        except Exception:
            pass
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
            # Schedule notification safely
            _safe_schedule_coro(_notify_admins(bot, text))
        except Exception:
            logger.exception("Error in loop exception handler")
    return _handler


def _install_sys_excepthook(bot):
    def excepthook(type_, value, tb):
        try:
            tb_text = "".join(traceback.format_exception(type_, value, tb))
            text = "⚠️ Uncaught exception\n\n```\n" + tb_text + "\n```"
            # Schedule notification safely
            _safe_schedule_coro(_notify_admins(bot, text))
        except Exception:
            logger.exception("Failed to report uncaught exception")
        # still call default hook for visibility
        try:
            sys.__excepthook__(type_, value, tb)
        except Exception:
            pass
    sys.excepthook = excepthook


class AdminLogHandler(logging.Handler):
    def __init__(self, bot):
        super().__init__(level=logging.ERROR)
        self.bot = bot

    def emit(self, record):
        try:
            msg = self.format(record)
            # Try to schedule sending the message to admins; if not possible, print it
            scheduled = _safe_schedule_coro(_notify_admins(self.bot, f"🛑 Log ERROR\n\n```\n{msg}\n```"))
            if not scheduled:
                # Best-effort fallback: log to stderr so it is visible in logs
                try:
                    print("AdminLogHandler fallback — Log ERROR:\n", msg, file=sys.stderr)
                except Exception:
                    pass
        except Exception:
            # Never allow logging errors to crash the app
            try:
                print("AdminLogHandler.emit failed for record:", record, file=sys.stderr)
            except Exception:
                pass


# ---------------- Application error handler ----------------
async def error_handler(update: Optional[Update], context: ContextTypes.DEFAULT_TYPE) -> None:
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
            # schedule safely
            _safe_schedule_coro(_notify_admins(bot, text))
    except Exception:
        logger.exception("Failed in application-level error handler")


def setup_admin_reporting(app):
    bot = app.bot
    # install loop exception handler if possible
    try:
        loop = asyncio.get_event_loop()
        if not loop.is_closed():
            loop.set_exception_handler(_make_loop_exception_handler(bot))
    except Exception:
        # ignore - environment might not have a loop yet
        pass

    _install_sys_excepthook(bot)
    admin_handler = AdminLogHandler(bot)
    admin_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(admin_handler)


# ---------------- Main ----------------
def main():
    print("🟢 bot.py is starting...")

    REQUEST = Request(
        connect_timeout=10.0,
        read_timeout=40.0,
        pool_timeout=10.0,
        con_pool_size=16,
        http_version="1.1",
    )

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .request(REQUEST)
        .build()
    )

    # global error handler
    app.add_error_handler(error_handler)

    print("📦 Registering handlers...")
    register_handlers(app)

    try:
        setup_admin_reporting(app)
        print("🟢 Admin reporting set up.")
    except Exception:
        logger.exception("setup_admin_reporting failed")

    print("🚀 Launching app.run_polling()...")
    app.run_polling(poll_interval=0.0)


if __name__ == "__main__":
    main()
