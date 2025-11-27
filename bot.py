# bot.py — minimal, polling-only launcher for your Voxi bot
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
            loop.call_soon_threadsafe(asyncio.create_task, _notify_admins(bot, text))
        except Exception:
            logger.exception("Error in loop exception handler")
    return _handler


def _install_sys_excepthook(bot):
    def excepthook(type_, value, tb):
        try:
            tb_text = "".join(traceback.format_exception(type_, value, tb))
            text = "⚠️ Uncaught exception\n\n```\n" + tb_text + "\n```"
            loop = asyncio.get_event_loop()
            loop.call_soon_threadsafe(asyncio.create_task, _notify_admins(bot, text))
        except Exception:
            logger.exception("Failed to report uncaught exception")
        sys.__excepthook__(type_, value, tb)
    sys.excepthook = excepthook


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
                _notify_admins(self.bot, f"🛑 Log ERROR\n\n```\n{msg}\n```"),
            )
        except Exception:
            logger.exception("Failed to emit admin log")


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
            await _notify_admins(bot, text)
    except Exception:
        logger.exception("Failed in application-level error handler")


def setup_admin_reporting(app):
    bot = app.bot
    loop = asyncio.get_event_loop()
    loop.set_exception_handler(_make_loop_exception_handler(bot))
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
