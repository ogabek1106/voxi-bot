# features/debug_user_tests.py
"""
Admin-only debug helpers for user tracking.

Commands (admin-only):
 - /checkme        -> reply whether the caller's id exists in DB
 - /sample_users   -> show up to N recent users (default 10)
 - /inject_test    -> insert a synthetic test user id and show new count (useful to verify DB writes)
 - /remove_test    -> remove a synthetic test user id (cleanup)

Notes:
 - Uses database.py API (add_user_if_new, user_exists, sample_users, get_user_count, delete_user).
 - Only admins listed in admins.ADMIN_IDS can call these commands.
 - Intended for short-term debugging and removal later.
"""

import logging
import time
import random
import os

from typing import Optional

from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

import admins
from database import add_user_if_new, user_exists, sample_users, get_user_count, delete_user

logger = logging.getLogger(__name__)

def _is_admin(user_id: int) -> bool:
    try:
        raw = getattr(admins, "ADMIN_IDS", None) or getattr(admins, "ADMINS", None) or []
        return int(user_id) in {int(x) for x in raw}
    except Exception:
        return False


def checkme_handler(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        return
    uid = int(user.id)
    exists = user_exists(uid)
    count = get_user_count()
    text = f"Your id: {uid}\nRecorded in DB: {'YES' if exists else 'NO'}\nTotal users in DB: {count}"
    update.message.reply_text(text)


def sample_handler(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        return
    # optional arg specifying how many
    try:
        n = int(context.args[0]) if context.args else 10
    except Exception:
        n = 10
    rows = sample_users(limit=n)
    if not rows:
        update.message.reply_text("No rows returned (DB empty or error).")
        return
    # Build readable output (limit length to avoid huge messages)
    lines = []
    for r in rows:
        # rows may be tuples of different shapes depending on DB schema
        lines.append(" | ".join("" if v is None else str(v) for v in r))
    text = "Sample users (most recent):\n\n" + "\n".join(lines)
    update.message.reply_text(text)


def inject_test_handler(update: Update, context: CallbackContext):
    """
    Create a synthetic test user id and insert into DB to verify add_user_if_new works.
    We pick a high random id (>= 9e9) to avoid colliding with real ids. Returns the new total.
    """
    user = update.effective_user
    if not user or not _is_admin(user.id):
        return

    # optional provided id: /inject_test 99999999999
    provided = None
    if context.args:
        try:
            provided = int(context.args[0])
        except Exception:
            provided = None

    if provided:
        test_uid = int(provided)
    else:
        # generate synthetic id that is unlikely to exist
        test_uid = int(time.time()) + random.randint(9_000_000_000, 9_999_999_999)

    added = add_user_if_new(test_uid, first_name="TEST_USER", username=f"test_{test_uid}")
    total = get_user_count()
    update.message.reply_text(f"Injected test id: {test_uid}\nInserted: {'YES' if added else 'ALREADY_PRESENT'}\nTotal now: {total}")


def remove_test_handler(update: Update, context: CallbackContext):
    """
    Remove a test id: /remove_test 99999999999
    If no arg provided, nothing is removed.
    """
    user = update.effective_user
    if not user or not _is_admin(user.id):
        return
    if not context.args:
        update.message.reply_text("Use: /remove_test <id>")
        return
    try:
        tid = int(context.args[0])
    except Exception:
        update.message.reply_text("Invalid id.")
        return
    ok = delete_user(tid)
    total = get_user_count()
    update.message.reply_text(f"Removed {tid}: {'YES' if ok else 'NOT_FOUND'}\nTotal now: {total}")


def setup(dispatcher, bot=None):
    dispatcher.add_handler(CommandHandler("checkme", checkme_handler))
    dispatcher.add_handler(CommandHandler("sample_users", sample_handler))
    dispatcher.add_handler(CommandHandler("inject_test", inject_test_handler))
    dispatcher.add_handler(CommandHandler("remove_test", remove_test_handler))
    logger.info("debug_user_tests feature loaded. Admins=%r", getattr(admins, "ADMIN_IDS", None))
