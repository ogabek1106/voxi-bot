# features/wat.py
"""
Admin debug command: /wat
Shows FULL SQLite state:
- all tables
- schema of each table
- row count
- last rows

READ-ONLY. TEMPORARY. SAFE.
"""

import os
import sqlite3
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

import admins
from database import get_checker_mode

logger = logging.getLogger(__name__)
router = Router()

DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "/data/data.db"))
SQLITE_TIMEOUT = 5
MAX_ROWS_PER_TABLE = 5
MAX_TELEGRAM_LEN = 4000


# ─────────────────────────────
# Helpers
# ─────────────────────────────

def _is_admin(user_id: int) -> bool:
    raw = getattr(admins, "ADMIN_IDS", []) or []
    return user_id is not None and int(user_id) in {int(x) for x in raw}


def _split_text_for_telegram(text: str, limit: int = MAX_TELEGRAM_LEN):
    chunks = []
    current = []
    size = 0

    for line in text.split("\n"):
        ln = len(line) + 1
        if size + ln > limit:
            chunks.append("\n".join(current))
            current = [line]
            size = ln
        else:
            current.append(line)
            size += ln

    if current:
        chunks.append("\n".join(current))

    return chunks


# ─────────────────────────────
# /wat (admin)
# ─────────────────────────────

@router.message(Command("wat"))
async def wat_handler(message: Message, state: FSMContext):
    user = message.from_user
    if not user or not _is_admin(user.id):
        await message.answer("⛔ Admins only.")
        return

    # 🚫 FREE STATE ONLY (VERY IMPORTANT)
    if get_checker_mode(user.id) is not None:
        await message.answer("⚠️ Finish current operation before using /wat.")
        return

    if not os.path.exists(DB_PATH):
        await message.answer("❌ Database file not found.")
        return

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT, check_same_thread=False)
        cur = conn.cursor()

        # 1️⃣ Get ALL tables
        cur.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name;
        """)
        tables = [r[0] for r in cur.fetchall()]

        if not tables:
            await message.answer("❌ No tables found in database.")
            return

        lines = []
        lines.append("🧠 <b>SQLite FULL DEBUG</b>\n")
        lines.append(f"📄 DB path: <code>{DB_PATH}</code>")
        lines.append(f"📦 Tables found: <b>{len(tables)}</b>\n")

        # 2️⃣ For EACH table → schema + count + sample rows
        for table in tables:
            lines.append("━━━━━━━━━━━━━━")
            lines.append(f"📋 <b>Table:</b> <code>{table}</code>")

            # Schema
            cur.execute(f"PRAGMA table_info({table});")
            cols = cur.fetchall()
            lines.append("📐 Columns:")
            for cid, name, col_type, notnull, default, pk in cols:
                flags = []
                if pk:
                    flags.append("PK")
                if notnull:
                    flags.append("NOT NULL")
                flag_text = f" ({', '.join(flags)})" if flags else ""
                lines.append(f"• <code>{name}</code> {col_type}{flag_text}")

            # Row count
            cur.execute(f"SELECT COUNT(*) FROM {table};")
            count = cur.fetchone()[0]
            lines.append(f"📊 Rows: <b>{count}</b>")

            # Sample rows
            cur.execute(f"SELECT * FROM {table} LIMIT {MAX_ROWS_PER_TABLE};")
            rows = cur.fetchall()

            if rows:
                lines.append(f"📦 Sample rows (up to {MAX_ROWS_PER_TABLE}):")
                for i, row in enumerate(rows, 1):
                    lines.append(f"{i}) <code>{row}</code>")
            else:
                lines.append("📦 No rows")

            lines.append("")

        text = "\n".join(lines)

        parts = _split_text_for_telegram(text)
        for i, part in enumerate(parts, start=1):
            header = f"<b>🧠 SQLite Debug (part {i}/{len(parts)})</b>\n\n" if len(parts) > 1 else ""
            await message.answer(header + part, parse_mode="HTML")

    except Exception as e:
        logger.exception("wat failed")
        await message.answer(f"❌ Error:\n<code>{e}</code>", parse_mode="HTML")
    finally:
        if conn:
            conn.close()
