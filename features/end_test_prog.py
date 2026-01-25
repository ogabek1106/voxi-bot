# features/end_test_prog.py
"""
Admin command to end the test program.

Purpose:
- Unlock FULL test result details for users
- Writes global flag into test_program_state table

Usage:
  /end_test_prog   (admin only)
"""

import logging
from typing import Optional

from telegram import Update
from telegram.ext import CommandHandler, CallbackContext

import admins
from database import end_test_program

logger = logging.getLogger(__name__)


# ---------- helpers ----------

def _is_admin(user_id: Optional[int]) -> bool:
    raw = getattr(admins, "ADMIN_IDS", []) or []
    return user_id is not None and int(user_id) in {int(x) for x in raw}


# ---------- command ----------

def end_test_prog(update: Update, context: CallbackContext):
    message = update.message
    user = update.effective_user

    if not user or not _is_admin(user.id):
        message.reply_text("⛔ Admins only.")
        return

    ok = end_test_program()
    if not ok:
        message.reply_text("❌ Failed to end test program. See logs.")
        return

    message.reply_text(
        "🔓 Test program ended.\n\n"
        "📊 Detailed test results are now available to users."
    )


# ---------- setup ----------

def setup(dispatcher, bot=None):
    dispatcher.add_handler(CommandHandler("end_test_prog", end_test_prog))
    logger.info("Feature loaded: end_test_prog")
