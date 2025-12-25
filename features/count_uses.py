"""
/count_uses

Admin-only command.
Shows:
 - command usage (last 24h / lifetime)
 - total book requests (last 24h / lifetime)
"""

import logging
from typing import Optional

from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

import admins
from database import (
    get_command_usage_stats,
    get_total_book_request_stats,
)

logger = logging.getLogger(__name__)


# ---------- helpers ----------

def _is_admin(user_id: Optional[int]) -> bool:
    raw = getattr(admins, "ADMIN_IDS", []) or []
    return user_id is not None and int(user_id) in {int(x) for x in raw}


# ---------- handler ----------

def count_uses_handler(update: Update, context: CallbackContext):
    user = update.effective_user
    user_id = user.id if user else None

    if not _is_admin(user_id):
        update.message.reply_text("⛔ Bu buyruq faqat adminlar uchun.")
        return

    lines = []
    lines.append("📊 *Usage statistics*\n")

    # -------- Commands --------
    stats = get_command_usage_stats()

    if stats:
        lines.append("🔹 *Commands:*")
        for command, last_24h, total in stats:
            lines.append(f"{command} — {last_24h} / {total}")
    else:
        lines.append("🔹 *Commands:* yo‘q")

    # -------- Books --------
    book_24h, book_total = get_total_book_request_stats()

    lines.append("\n📚 *Book requests:*")
    lines.append(f"{book_24h} / {book_total}")

    text = "\n".join(lines)

    update.message.reply_text(
        text,
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


# ---------- registration ----------

def setup(dispatcher):
    dispatcher.add_handler(CommandHandler("count_uses", count_uses_handler))
