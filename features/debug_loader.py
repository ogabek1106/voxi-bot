# features/debug_loader.py
import logging
import os
import sqlite3
from telegram.ext import CommandHandler
import admins

logger = logging.getLogger(__name__)
DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "sqlite.db"))

def debug_stats(update, context):
    user = update.effective_user
    admin_ids = getattr(admins, "ADMIN_IDS", set())
    is_admin = user.id in admin_ids if user else False
    db_exists = os.path.exists(DB_PATH)
    count = "N/A"
    if db_exists:
        try:
            conn = sqlite3.connect(DB_PATH, timeout=10)
            cur = conn.execute("SELECT COUNT(*) FROM users;")
            count = cur.fetchone()[0]
            conn.close()
        except Exception as e:
            count = f"err:{e}"
    text = (
        f"your_id: {user.id}\n"
        f"is_admin: {is_admin}\n"
        f"admins: {list(admin_ids)}\n"
        f"DB_PATH: {DB_PATH}\n"
        f"db_exists: {db_exists}\n"
        f"users_count: {count}"
    )
    update.message.reply_text(text)

def setup(dispatcher):
    dispatcher.add_handler(CommandHandler("debugme", debug_stats))
    logger.info("debug_loader loaded")
