# features/unpublish.py
"""
Admin command to unpublish the currently active test.

Usage:
  /unpublish
"""

import logging
from typing import Optional

from telegram import Update
from telegram.ext import CommandHandler, CallbackContext
from database import get_checker_mode
import admins
from database import (
    has_active_test,      # 🔹 will be added
    clear_active_test,    # 🔹 will be added
)

logger = logging.getLogger(__name__)


# ---------- helpers ----------

def _is_admin(user_id: Optional[int]) -> bool:
    raw = getattr(admins, "ADMIN_IDS", []) or []
    return user_id is not None and int(user_id) in {int(x) for x in raw}


# ---------- command ----------

def unpublish(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        update.message.reply_text("⛔ Admins only.")
        return

    # 🚫 FREE STATE ONLY
    if get_checker_mode(user.id) is not None:
        update.message.reply_text(
            "⚠️ Finish current operation before using /unpublish."
        )
        return
      
    if not has_active_test():
        update.message.reply_text("ℹ️ No active test to unpublish.")
        return

    # 🔹 NEW: try to read active test info (optional, safe)
    active_test_info = None
    try:
        from database import get_active_test  # may be added later
        active_test_info = get_active_test()
    except Exception:
        pass  # safe fallback, do not break unpublish

    ok = clear_active_test()
    if not ok:
        update.message.reply_text("❌ Failed to unpublish test. See logs.")
        return

    # 🔹 NEW: richer feedback if info exists
    if active_test_info:
        test_id, name, level, question_count, time_limit, published_at = active_test_info
        update.message.reply_text(
            "🧹 Active test has been unpublished.\n\n"
            f"ID: {test_id}\n"
            f"Name: {name or '—'}\n"
            f"Level: {level or '—'}"
        )
    else:
        update.message.reply_text("🧹 Active test has been unpublished.")


# ---------- setup ----------

def setup(dispatcher, bot=None):
    dispatcher.add_handler(CommandHandler("unpublish", unpublish), group=-100)
    logger.info("Feature loaded: unpublish (ACTIVE TEST)")
