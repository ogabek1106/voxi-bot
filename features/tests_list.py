# tests_list.py

"""
Admin-only command: /tests_list

Shows all created tests stored in SQLite (tests table).
"""

import logging
import time
from typing import Optional

from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

import admins
from database import get_all_tests

logger = logging.getLogger(__name__)

MAX_LEN = 3800  # keep margin under Telegram limit


# ---------- helpers ----------

def _is_admin(user_id: Optional[int]) -> bool:
    raw = getattr(admins, "ADMIN_IDS", []) or []
    return user_id is not None and int(user_id) in {int(x) for x in raw}


def _fmt_ts(ts: Optional[int]) -> str:
    if not ts:
        return "—"
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ts)))
    except Exception:
        return "—"


def _send_long_message(bot, chat_id, text: str):
    chunk = ""
    for line in text.split("\n"):
        if len(chunk) + len(line) + 1 > MAX_LEN:
            bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
            chunk = ""
        chunk += line + "\n"

    if chunk.strip():
        bot.send_message(
            chat_id=chat_id,
            text=chunk,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )


# ---------- command ----------

def tests_list(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        update.message.reply_text("⛔ Admins only.")
        return

    tests = get_all_tests()
    if not tests:
        update.message.reply_text("🧪 No tests found yet.")
        return

    lines = ["🧪 *Tests list:*\n"]

    for i, t in enumerate(tests, start=1):
        # (test_id, name, level, question_count, time_limit, created_at)
        test_id, name, level, q_count, time_limit, created_at = t

        lines.append(
            f"*{i}. {test_id}*\n"
            f"• Name: {name or '—'}\n"
            f"• Level: {level or '—'}\n"
            f"• Questions: {q_count or '—'}\n"
            f"• Time: {time_limit or '—'} min\n"
            f"• Created: {_fmt_ts(created_at)}\n"
        )

    text = "\n".join(lines)
    _send_long_message(context.bot, update.effective_chat.id, text)


# ---------- setup ----------

def setup(dispatcher, bot=None):
    dispatcher.add_handler(
        CommandHandler("tests_list", tests_list),
        group=-10,  # admin utilities priority
    )
    logger.info("tests_list feature loaded (admin-only)")
