# features/get_test.py
"""
User command to get the currently active test.

Behavior:
- If NO active test -> friendly message
- If active test exists -> show test info + Start / Cancel buttons

Test execution logic is handled in start_test.py
"""

import logging
import os
import sqlite3

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    CommandHandler,
    CallbackContext,
    CallbackQueryHandler,
)

from features.sub_check import require_subscription

# >>> ADDITIVE IMPORTS (DO NOT REMOVE ANYTHING)
from global_checker import allow
from global_cleaner import clean_user
from database import set_user_mode
# <<< ADDITIVE IMPORTS

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "/data/data.db"))
SQLITE_TIMEOUT = 5

# >>> ADDITIVE CONSTANT
MODE_NAME = "get_test"
# <<< ADDITIVE CONSTANT


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
    user = update.effective_user

    # >>> ADDITIVE FREE-STATE GUARD
    if not user or not allow(user.id, mode=None, allow_free=False):
        return
    # <<< ADDITIVE FREE-STATE GUARD

    # 🔒 subscription gate
    if not require_subscription(update, context):
        return
        
    active = _get_active_test()

    if not active:
        update.message.reply_text(
            "❌ No active tests at the moment.\n"
            "Please check back later."
        )
        return

    test_id, name, level, question_count, time_limit, published_at = active

    # >>> ADDITIVE MODE SET
    set_user_mode(user.id, MODE_NAME)
    # <<< ADDITIVE MODE SET

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("▶️ Start", callback_data="start_test"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_test"),
            ]
        ]
    )

    update.message.reply_text(
        "🧪 *Active Test*\n\n"
        f"📌 Name: {name or '—'}\n"
        f"📊 Level: {level or '—'}\n"
        f"❓ Questions: {question_count or '—'}\n"
        f"⏱ Time limit: {time_limit or '—'} min\n\n"
        "🟢 Test is available.",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


# ---------- cancel handler ----------

def cancel_test(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    user = query.from_user if query else None

    # >>> ADDITIVE MODE OWNERSHIP CHECK
    if not user or not allow(user.id, mode=MODE_NAME):
        return
    # <<< ADDITIVE MODE OWNERSHIP CHECK

    # >>> ADDITIVE CLEANUP
    clean_user(user.id, reason="get_test cancelled")
    # <<< ADDITIVE CLEANUP

    query.edit_message_text("❌ Test start cancelled.")


# ---------- setup ----------

def setup(dispatcher, bot=None):
    dispatcher.add_handler(CommandHandler("get_test", get_test), group=0)
    dispatcher.add_handler(CallbackQueryHandler(cancel_test, pattern="^cancel_test$"), group=0)
    logger.info("Feature loaded: get_test (ACTIVE TEST ONLY)")
