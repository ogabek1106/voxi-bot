# features/publish.py
"""
Admin command to publish ONE test.

Flow:
- Reads draft tests from test_defs
- Allows publishing ONLY if no active test exists
- Publishes by saving test_id into active_test table (via DB helper)

Usage:
  /publish <number>
"""

import logging
from typing import Optional

from telegram import Update
from telegram.ext import CommandHandler, CallbackContext

import admins
from database import (
    get_all_test_definitions,
    get_test_definition,
    has_active_test,        # 🔹 will be added
    set_active_test,        # 🔹 will be added
)

logger = logging.getLogger(__name__)


# ---------- helpers ----------

def _is_admin(user_id: Optional[int]) -> bool:
    raw = getattr(admins, "ADMIN_IDS", []) or []
    return user_id is not None and int(user_id) in {int(x) for x in raw}


# ---------- command ----------

def publish(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        update.message.reply_text("⛔ Admins only.")
        return

    if not context.args:
        update.message.reply_text("❗ Usage: /publish <test_number>")
        return

    try:
        index = int(context.args[0])
        if index <= 0:
            raise ValueError
    except ValueError:
        update.message.reply_text("❗ Test number must be a positive integer.")
        return

    if has_active_test():
        update.message.reply_text(
            "⚠️ There is already an active test.\n"
            "Use /unpublish first."
        )
        return

    tests = get_all_test_definitions()
    if not tests:
        update.message.reply_text("❌ No test definitions found.")
        return

    if index > len(tests):
        update.message.reply_text(
            f"❌ Invalid test number.\n"
            f"Available: 1 – {len(tests)}"
        )
        return

    test = tests[index - 1]
    test_id, name, level, question_count, time_limit, created_at = test

    meta = get_test_definition(test_id)
    if not meta:
        update.message.reply_text("❌ Test definition not found in database.")
        return

    ok = set_active_test(
        test_id=test_id,
        name=name,
        level=level,
        question_count=question_count,
        time_limit=time_limit,
    )

    if not ok:
        update.message.reply_text("❌ Failed to publish test. See logs.")
        return

    update.message.reply_text(
        "✅ Test published successfully!\n\n"
        f"ID: {test_id}\n"
        f"Name: {name}\n"
        f"Level: {level}\n"
        f"Questions: {question_count}\n"
        f"Time limit: {time_limit} min"
    )


# ---------- setup ----------

def setup(dispatcher, bot=None):
    dispatcher.add_handler(CommandHandler("publish", publish), group=-100)
    logger.info("Feature loaded: publish (ACTIVE TEST)")
