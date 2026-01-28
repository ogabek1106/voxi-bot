# features/reopen_test.py
"""
Admin-only command: /reopen_test <user_id | token>

Reopens access to the ACTIVE test for a specific user
by deleting their previous attempt (score + answers).

Rules:
- Admin only
- FREE state only
- Works with user_id OR token
- Active test only
"""

import logging
import os
import sqlite3
from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

import admins
from database import get_active_test, get_checker_mode

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "/data/data.db"))
SQLITE_TIMEOUT = 5


# ---------- helpers ----------

def _connect():
    return sqlite3.connect(
        DB_PATH,
        timeout=SQLITE_TIMEOUT,
        check_same_thread=False,
    )


def _is_admin(user_id: int) -> bool:
    raw = getattr(admins, "ADMIN_IDS", []) or []
    return int(user_id) in {int(x) for x in raw}


# ---------- command ----------

def reopen_test_command(update: Update, context: CallbackContext):
    message = update.message
    admin_id = message.from_user.id

    # 🔒 ADMIN ONLY
    if not _is_admin(admin_id):
        message.reply_text("⛔ This command is for admins only.")
        return

    # 🔒 FREE MODE ONLY
    if get_checker_mode(admin_id) is not None:
        return

    if not context.args:
        message.reply_text("❗ Usage:\n/reopen_test <user_id | token>")
        return

    identifier = context.args[0].strip()

    active = get_active_test()
    if not active:
        message.reply_text("❌ No active test.")
        return

    test_id = active[0]

    conn = _connect()
    cur = conn.cursor()

    # ---------- RESOLVE USER ----------
    user_id = None
    token = None

    if identifier.isdigit():
        # case 1: user_id provided
        user_id = int(identifier)
        cur.execute(
            """
            SELECT token
            FROM test_scores
            WHERE user_id = ? AND test_id = ?;
            """,
            (user_id, test_id),
        )
        row = cur.fetchone()
        if row:
            token = row[0]

    else:
        # case 2: token provided
        token = identifier
        cur.execute(
            """
            SELECT user_id
            FROM test_scores
            WHERE token = ? AND test_id = ?;
            """,
            (token, test_id),
        )
        row = cur.fetchone()
        if row:
            user_id = row[0]

    if not user_id or not token:
        conn.close()
        message.reply_text("ℹ️ No attempt found for this user/token in the active test.")
        return

    # ---------- DELETE ATTEMPT ----------
    cur.execute(
        "DELETE FROM test_answers WHERE token = ? AND test_id = ?;",
        (token, test_id),
    )

    cur.execute(
        "DELETE FROM test_scores WHERE user_id = ? AND test_id = ?;",
        (user_id, test_id),
    )

    conn.commit()
    conn.close()

    message.reply_text(
        "✅ Test access reopened.\n\n"
        f"👤 User ID: <code>{user_id}</code>\n"
        f"🔑 Token: <code>{token}</code>\n"
        f"📝 Test ID: <code>{test_id}</code>\n\n"
        "The user can now start the test again.",
        parse_mode="HTML",
    )


# ---------- setup ----------

def setup(dispatcher, bot=None):
    dispatcher.add_handler(CommandHandler("reopen_test", reopen_test_command))
    logger.info("Feature loaded: reopen_test")
