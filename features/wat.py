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
from telegram import Update
from telegram.ext import CallbackContext, CommandHandler
from database import get_checker_mode

import admins

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "/data/data.db"))
SQLITE_TIMEOUT = 5
MAX_ROWS_PER_TABLE = 5  # keep output safe


def _is_admin(user_id):
    raw = getattr(admins, "ADMIN_IDS", []) or []
    return user_id is not None and int(user_id) in {int(x) for x in raw}


def wat(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        update.message.reply_text("⛔ Admins only.")
        return

    # 🚫 FREE STATE ONLY (VERY IMPORTANT)
    if get_checker_mode(user.id) is not None:
        update.message.reply_text(
            "⚠️ Finish current operation before using /wat."
        )
        return

    if not os.path.exists(DB_PATH):
        update.message.reply_text("❌ Database file not found.")
        return

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT)
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
            update.message.reply_text("❌ No tables found in database.")
            return

        lines = []
        lines.append("🧠 *SQLite FULL DEBUG*\n")
        lines.append(f"📄 DB path: `{DB_PATH}`")
        lines.append(f"📦 Tables found: `{len(tables)}`\n")

        # 2️⃣ For EACH table → schema + count + sample rows
        for table in tables:
            lines.append(f"━━━━━━━━━━━━━━")
            lines.append(f"📋 *Table:* `{table}`")

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
                lines.append(f"• `{name}` {col_type}{flag_text}")

            # Row count
            cur.execute(f"SELECT COUNT(*) FROM {table};")
            count = cur.fetchone()[0]
            lines.append(f"📊 Rows: `{count}`")

            # Sample rows
            cur.execute(f"SELECT * FROM {table} LIMIT {MAX_ROWS_PER_TABLE};")
            rows = cur.fetchall()

            if rows:
                lines.append(f"📦 Sample rows (up to {MAX_ROWS_PER_TABLE}):")
                for i, row in enumerate(rows, 1):
                    lines.append(f"{i}) `{row}`")
            else:
                lines.append("📦 No rows")

            lines.append("")

        # Telegram message limit safety
        message = "\n".join(lines)
        if len(message) > 3900:
            message = message[:3900] + "\n\n⚠️ Output truncated."

        update.message.reply_text(message, parse_mode="Markdown")

    except Exception as e:
        logger.exception("wat failed")
        update.message.reply_text(f"❌ Error:\n`{e}`", parse_mode="Markdown")
    finally:
        if conn:
            conn.close()


def setup(dispatcher, bot=None):
    dispatcher.add_handler(CommandHandler("wat", wat), group=-100)
    logger.info("Feature loaded: wat (FULL SQLite inspector)")
