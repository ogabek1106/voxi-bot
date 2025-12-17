# features/get_test.py
"""
User command to get the currently active test.

Behavior:
- If NO active test -> friendly message
- If active test exists -> show test info

No test start logic yet.
No tokens yet.
"""

import logging
import os
import sqlite3

from telegram import Update
from telegram.ext import CommandHandler, CallbackContext

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "/data/data.db"))
SQLITE_TIMEOUT = 5


# ---------- helpers ----------

def _get_active_test():
    """
    Return active test row or None.
    """
    if not os.path.exists(DB_PATH):
        return None

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT, check_same_thread=False)
        cur = conn.execute(
            """
            SELECT test_id, name, level, question_count, time_limit, published_at
            FROM active_test
            LIMIT 1;
            """
        )
        return cur.fetchone()
    except Exception as e:
        logger.exception("get_active_test failed: %s", e)
        return None
    finally:
        if conn:
            conn.close()


# ---------- command ----------

def get_test(update: Update, context: CallbackContext):
    active = _get_active_test()

    if not active:
        update.message.reply_text(
            "❌ No active tests at the moment.\n"
            "Please check back later."
        )
        return

    test_id, name, level, question_count, time_limit, published_at = active

    update.message.reply_text(
        "🧪 *Active Test*\n\n"
        f"📌 Name: {name or '—'}\n"
        f"📊 Level: {level or '—'}\n"
        f"❓ Questions: {question_count or '—'}\n"
        f"⏱ Time limit: {time_limit or '—'} min\n\n"
        "🟢 Test is available.",
        parse_mode="Markdown"
    )


# ---------- setup ----------

def setup(dispatcher, bot=None):
    dispatcher.add_handler(CommandHandler("get_test", get_test), group=0)
    logger.info("Feature loaded: get_test (ACTIVE TEST ONLY)")
