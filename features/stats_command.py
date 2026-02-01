# stats_command.py
"""
Feature: /stats admin-only command (Aiogram 3).

- Reads unique user count from SQLite users table.
- Only accessible to admins listed in admins.ADMIN_IDS.
- Router-based, loader-friendly.
"""

import os
import sqlite3
import logging
from typing import Set

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

import admins

logger = logging.getLogger(__name__)

router = Router()

DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "/data/data.db"))


# ─────────────────────────────
# Helpers
# ─────────────────────────────

def _get_admin_ids() -> Set[int]:
    ids: Set[int] = set()
    raw = getattr(admins, "ADMIN_IDS", []) or []
    for v in raw:
        try:
            ids.add(int(v))
        except Exception:
            logger.warning("Ignoring non-int admin id: %r", v)
    return ids


def _count_users() -> int:
    if not os.path.exists(DB_PATH):
        return 0

    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cur = conn.execute("SELECT COUNT(*) FROM users;")
        row = cur.fetchone()
        conn.close()
        return int(row[0]) if row and row[0] is not None else 0
    except sqlite3.OperationalError as e:
        logger.debug("SQLite operational error while counting users: %s", e)
        return 0
    except Exception as e:
        logger.exception("Failed to count users from DB %s: %s", DB_PATH, e)
        return 0


# ─────────────────────────────
# /stats — ADMIN ONLY
# ─────────────────────────────

@router.message(Command("stats"))
async def stats_handler(message: Message, state: FSMContext):
    user = message.from_user
    if not user:
        return

    admin_ids = _get_admin_ids()
    if user.id not in admin_ids:
        logger.info("Non-admin %s tried /stats", user.id)
        return

    count = _count_users()
    await message.answer(f"👥 Unique users (total): {count}")
