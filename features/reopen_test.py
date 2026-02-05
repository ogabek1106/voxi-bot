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

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

import admins
from database import get_active_test, get_checker_mode

logger = logging.getLogger(__name__)
router = Router()

DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "/data/data.db"))
SQLITE_TIMEOUT = 5


# ─────────────────────────────
# Helpers
# ─────────────────────────────

def _connect():
    return sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT, check_same_thread=False)


def _is_admin(user_id: int) -> bool:
    raw = getattr(admins, "ADMIN_IDS", []) or []
    return int(user_id) in {int(x) for x in raw}


# ─────────────────────────────
# /reopen_test (admin)
# ─────────────────────────────

@router.message(Command("reopen_test"))
async def reopen_test_handler(message: Message, state: FSMContext):
    admin_id = message.from_user.id

    # 🔒 ADMIN ONLY
    if not _is_admin(admin_id):
        await message.answer("⛔ This command is for admins only.")
        return

    # 🔒 FREE MODE ONLY
    if get_checker_mode(admin_id) is not None:
        await message.answer("⚠️ Finish current operation before using /reopen_test.")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❗ Usage:\n/reopen_test <user_id | token>")
        return

    identifier = parts[1].strip()

    active = get_active_test()
    if not active:
        await message.answer("❌ No active test.")
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
        token = identifier.strip()
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
        await message.answer("ℹ️ No attempt found for this user/token in the active test.")
        return

    # ---------- DELETE ATTEMPT ----------
    try:
        cur.execute(
            "DELETE FROM test_answers WHERE token = ? AND test_id = ?;",
            (token, test_id),
        )
        cur.execute(
            "DELETE FROM test_scores WHERE user_id = ? AND test_id = ?;",
            (user_id, test_id),
        )
        conn.commit()
    except Exception as e:
        logger.exception("Failed to reopen test for user_id=%s token=%s", user_id, token)
        await message.answer("❌ Failed to reopen test attempt due to DB error.")
        conn.close()
        return
    finally:
        conn.close()

    await message.answer(
        "✅ Test access reopened.\n\n"
        f"👤 User ID: <code>{user_id}</code>\n"
        f"🔑 Token: <code>{token}</code>\n"
        f"📝 Test ID: <code>{test_id}</code>\n\n"
        "The user can now start the test again.",
        parse_mode="HTML",
    )
