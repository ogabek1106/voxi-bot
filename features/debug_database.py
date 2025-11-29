# features/debug_database.py
"""
Temporary debug feature to inspect the SQLite users table.
Admin-only. Remove when finished.

Usage:
 /debug   - admin only, returns DB path, counts, sample ids and sample rows.
"""

import logging
from typing import Set
from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

import admins
import database

logger = logging.getLogger(__name__)


def _get_admin_ids() -> Set[int]:
    ids = set()
    try:
        raw = getattr(admins, "ADMIN_IDS", None) or getattr(admins, "ADMINS", None) or []
        for v in raw:
            try:
                ids.add(int(v))
            except Exception:
                logger.warning("Ignoring non-int admin id: %r", v)
    except Exception as e:
        logger.exception("Failed to read admin ids: %s", e)
    return ids


def debug_handler(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user:
        return

    admin_ids = _get_admin_ids()
    if user.id not in admin_ids:
        # keep silent for non-admins
        logger.info("Non-admin %s tried /debug", user.id)
        return

    try:
        DB_PATH = getattr(database, "DB_PATH", None)
        exists = "yes" if DB_PATH and __import__("os").path.exists(DB_PATH) else "no"

        total = 0
        try:
            total = database.get_user_count()
        except Exception as e:
            logger.exception("get_user_count failed: %s", e)

        all_users = []
        try:
            all_users = database.get_all_users(as_rows=False)
        except Exception as e:
            logger.exception("get_all_users failed: %s", e)
            all_users = []

        sample_rows = []
        try:
            sample_rows = database.sample_users(limit=10)
        except Exception as e:
            logger.exception("sample_users failed: %s", e)
            sample_rows = []

        # build reply text
        parts = []
        parts.append(f"🗄️ DB path: `{DB_PATH}`")
        parts.append(f"✅ DB file exists: {exists}")
        parts.append(f"👥 user_count() -> {total}")
        parts.append(f"🔢 get_all_users() returned {len(all_users)} rows")
        if all_users:
            # show up to first 20 ids
            first_ids = all_users[:20]
            parts.append("IDs (first up to 20):")
            # show in groups
            parts.append("`" + " ".join(str(int(x)) for x in first_ids) + "`")
        else:
            parts.append("IDs: (none)")

        if sample_rows:
            parts.append("📋 sample rows (user_id, first_name, username, added_at):")
            for r in sample_rows:
                # sample_rows rows come from database.sample_users: (user_id, first_name, username, added_at_str)
                parts.append(f"`{r[0]}`  •  {r[1] or '-'}  •  @{r[2] or '-'}  •  {r[3]}")
        else:
            parts.append("📋 sample rows: (none)")

        text = "\n\n".join(parts)
        # send as monospaced/code style for DB path/IDs clarity
        update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.exception("Unexpected error in /debug: %s", e)
        try:
            update.message.reply_text("An error occurred while running debug. Check logs.")
        except Exception:
            pass


def setup(dispatcher):
    dispatcher.add_handler(CommandHandler("debug", debug_handler))
    logger.info("debug_database feature loaded. Admins=%r DB=%r", _get_admin_ids(), getattr(database, "DB_PATH", None))
