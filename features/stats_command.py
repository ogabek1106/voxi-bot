# stats_command.py
"""
Feature: /stats admin-only command.

- Reads unique user count from SQLite users table.
- Only replies when the sender's user ID is listed in admins.ADMIN_IDS.
- Does not modify core files; provides `setup(dispatcher, bot)` for dynamic loader.
"""

import os
import sqlite3
import logging
from typing import Set
from database import get_checker_mode

from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

# Import admins.py (you placed it in repo root)
import admins

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "/data/data.db"))


def _get_admin_ids() -> Set[int]:
    """Return set of admin ids from admins.ADMIN_IDS. Defensive: ensures ints."""
    ids = set()
    try:
        raw = getattr(admins, "ADMIN_IDS", None)
        if raw:
            for v in raw:
                try:
                    ids.add(int(v))
                except Exception:
                    logger.warning("Ignoring non-int admin id: %r", v)
    except Exception as e:
        logger.exception("Failed to read admins.ADMIN_IDS: %s", e)
    return ids


def _count_users() -> int:
    """Return total unique users from users table. Returns 0 if DB/table missing or on error."""
    if not os.path.exists(DB_PATH):
        return 0
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cur = conn.execute("SELECT COUNT(*) FROM users;")
        row = cur.fetchone()
        conn.close()
        return int(row[0]) if row and row[0] is not None else 0
    except sqlite3.OperationalError as e:
        # Table might not exist
        logger.debug("SQLite operational error while counting users: %s", e)
        return 0
    except Exception as e:
        logger.exception("Failed to count users from DB %s: %s", DB_PATH, e)
        return 0


def stats_handler(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user:
        return

    # 🚫 FREE STATE ONLY
    if get_checker_mode(user.id) is not None:
        return

    admin_ids = _get_admin_ids()
    if user.id not in admin_ids:
        logger.info("Non-admin %s tried /stats", user.id)
        return

    count = _count_users()
    text = f"👥 Unique users (total): {count}"
    try:
        update.message.reply_text(text)
    except Exception as e:
        logger.exception("Failed to send /stats reply to %s: %s", user.id, e)


def setup(dispatcher, bot=None):
    """Register /stats command with the dispatcher."""
    dispatcher.add_handler(CommandHandler("stats", stats_handler))
    logger.info("stats_command feature loaded. Admins=%r DB=%s", _get_admin_ids(), DB_PATH)
