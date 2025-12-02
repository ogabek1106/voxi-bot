# features/remove_token.py
"""
Admin feature to remove test tokens stored in the `tests` table.

Usage:
 - Admin sends /remove_token
 - Bot asks: send a user id or ALL
 - Reply "ALL" -> deletes all rows in tests (clears tokens)
 - Reply "<user_id>" -> deletes tokens for that user_id
"""
import logging
import os
import sqlite3
from typing import Optional

from telegram import Update
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    Filters,
    ConversationHandler,
    CallbackContext,
    Dispatcher,
)

import admins

logger = logging.getLogger(__name__)

# Conversation state
ASK_USER_OR_ALL = 1

# Use same DB path as other features
DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "/data/data.db"))
SQLITE_TIMEOUT = 5


def _connect():
    """
    Minimal sqlite3 connect helper. Caller must close.
    Matches pattern used in other feature files.
    """
    try:
        return sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT, check_same_thread=False)
    except Exception:
        logger.exception("Failed to connect to sqlite DB at %s", DB_PATH)
        raise


def _is_admin(uid: Optional[int]) -> bool:
    if uid is None:
        return False
    raw = getattr(admins, "ADMIN_IDS", None) or getattr(admins, "ADMINS", None) or []
    try:
        s = {int(x) for x in raw}
        return int(uid) in s
    except Exception:
        return False


# Entry point
def remove_token_start(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        update.message.reply_text("⛔ Bu buyruq faqat adminlar uchun.")
        return ConversationHandler.END

    update.message.reply_text(
        "🧹 Tokenlarni o‘chirish — yuboring *ALL* yoki aniq *user_id*.\n\n"
        "• ALL — barcha tokenlar o‘chiriladi\n"
        "• 12345678 — shu user_id uchun token/lar o‘chiriladi\n\n"
        "Bekor qilish uchun /cancel yuboring.",
        parse_mode="Markdown",
    )
    return ASK_USER_OR_ALL


def _delete_all_tests() -> int:
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM tests;")
        deleted = cur.rowcount  # sqlite3 rowcount may be -1 for some implementations; we'll compute via changes()
        conn.commit()
        # get number of changes in this connection
        try:
            cur.execute("SELECT changes();")
            r = cur.fetchone()
            if r:
                return int(r[0])
        except Exception:
            pass
        return deleted if deleted is not None else 0
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _delete_tests_for_user(user_id: int) -> int:
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM tests WHERE user_id = ?;", (int(user_id),))
        conn.commit()
        try:
            cur.execute("SELECT changes();")
            r = cur.fetchone()
            if r:
                return int(r[0])
        except Exception:
            pass
        return cur.rowcount if cur.rowcount is not None else 0
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def remove_token_process(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        update.message.reply_text("⛔ Ruxsat yo'q.")
        return ConversationHandler.END

    text = (update.message.text or "").strip()
    if not text:
        update.message.reply_text("❗ Iltimos, 'ALL' yoki foydalanuvchi ID yuboring.")
        return ASK_USER_OR_ALL

    if text.upper() == "ALL":
        try:
            deleted = _delete_all_tests()
            update.message.reply_text(f"✅ Barcha tokenlar o‘chirildi. O‘chirildi: {deleted} qator(lar).")
        except Exception as e:
            logger.exception("Failed to delete all tests: %s", e)
            update.message.reply_text("❌ Tokenlarni o‘chirishda xatolik yuz berdi. Logga qarang.")
        return ConversationHandler.END

    # Try numeric user id
    if text.isdigit():
        target_id = int(text)
        try:
            deleted = _delete_tests_for_user(target_id)
            if deleted > 0:
                update.message.reply_text(f"✅ Foydalanuvchi {target_id} uchun {deleted} token o‘chirildi.")
            else:
                update.message.reply_text(f"ℹ️ Foydalanuvchi {target_id} uchun token topilmadi.")
        except Exception as e:
            logger.exception("Failed to delete tests for user %s: %s", target_id, e)
            update.message.reply_text("❌ Tokenni o‘chirishda xatolik yuz berdi. Logga qarang.")
        return ConversationHandler.END

    update.message.reply_text("❗ Notog'ri format. Iltimos 'ALL' yoki raqamli user_id yuboring.")
    return ASK_USER_OR_ALL


def cancel(update: Update, context: CallbackContext):
    update.message.reply_text("Bekor qilindi.")
    return ConversationHandler.END


def setup(dispatcher: Dispatcher):
    """
    Register handlers.
    This uses a ConversationHandler so admin can input user id or ALL.
    """
    conv = ConversationHandler(
        entry_points=[CommandHandler("remove_token", remove_token_start)],
        states={
            ASK_USER_OR_ALL: [MessageHandler(Filters.text & ~Filters.command, remove_token_process)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=False,
        name="remove_token_conv",
    )
    dispatcher.add_handler(conv)
    logger.info("Feature loaded: remove_token")
