# features/admin_feedback.py
import os
from datetime import datetime
import logging

from aiogram import Bot

logger = logging.getLogger(__name__)

# ---------- Storage channels ----------
FEEDBACKS_STORAGE = int(os.getenv("FEEDBACKS_STORAGE"))
WRITING_STORAGE = int(os.getenv("WRITING_STORAGE"))


# ---------- FEEDBACK STORAGE (ALL SKILLS) ----------

async def send_admin_card(bot: Bot, user_id: int, title: str, content: str):
    """
    Sends AI feedback (Listening / Reading / Writing / Speaking)
    to the FEEDBACKS_STORAGE channel.
    """

    if not FEEDBACKS_STORAGE:
        logger.error("FEEDBACKS_STORAGE env var is not set")
        return

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    text = (
        f"📥 {title}\n"
        f"👤 User ID: {user_id}\n"
        f"🕒 {timestamp}\n\n"
        f"{content}"
    )

    try:
        await bot.send_message(
            chat_id=FEEDBACKS_STORAGE,
            text=text,
            parse_mode="Markdown"
        )
    except Exception:
        logger.exception("Failed to send admin feedback card")


# ---------- WRITING ESSAY STORAGE (TASK 1 & 2 ONLY) ----------

async def store_writing_essay(bot: Bot, text: str, tag: str):
    try:
        if not text or not text.strip():
            return

        if not WRITING_STORAGE:
            logger.error("WRITING_STORAGE env var is not set")
            return

        message = f"{text.strip()}\n\n{tag}"

        await bot.send_message(
            chat_id=WRITING_STORAGE,
            text=message
        )

    except Exception:
        logger.exception("Writing storage failed (ignored)")
