# features/test_form.py
"""
Test form integration feature.

Flow:
 - User -> /get_test
    -> server generates token, stores token,user_id,start_ts
    -> replies with button that opens FORM_PREFILL_URL with {token} and {start_ts} substituted
 - Admin -> /find_token <token>  (see token owner + status)
 - Admin -> /report <token> <score>
    -> marks completed, stores score, sends summary to admin and provides inline button
       "Send reward message" that when pressed sends configured reward text to the user.
"""

import logging
import os
import sqlite3
import time
import random
import string
from typing import Optional

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackContext, CommandHandler, CallbackQueryHandler

import admins

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "/data/data.db"))
FORM_PREFILL_URL = os.getenv("FORM_PREFILL_URL")  # required
REWARD_MESSAGE = os.getenv(
    "REWARD_MESSAGE",
    "Siz testa eng yuqori ballni qo'lga kiritdingiz! Yutuqni olish uchun @Ogabek1106 ga yozing!"
)
TOKEN_LENGTH = int(os.getenv("TOKEN_LENGTH", "8"))

# defensive: ensure DB folder exists
try:
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
except Exception:
    pass


def _connect():
    return sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)


def _ensure_table():
    conn = _connect()
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tests (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    start_ts INTEGER NOT NULL,
                    form_url TEXT,
                    completed INTEGER DEFAULT 0,
                    score TEXT,
                    submission_ts INTEGER,
                    rewarded INTEGER DEFAULT 0
                );
                """
            )
    except Exception as e:
        logger.exception("Failed to ensure tests table: %s", e)
    finally:
        conn.close()


def _is_admin(uid: int) -> bool:
    raw = getattr(admins, "ADMIN_IDS", None) or getattr(admins, "ADMINS", None) or []
    try:
        s = {int(x) for x in raw}
        return int(uid) in s
    except Exception:
        return False


def _gen_token(length: int = TOKEN_LENGTH) -> str:
    alphabet = string.ascii_uppercase + string.digits
    # ensure uniqueness by checking DB (retry a few times)
    for _ in range(10):
        t = "".join(random.choice(alphabet) for _ in range(length))
        if not _get_test_row(t):
            return t
    # fallback to time-based token
    return f"T{int(time.time())}"


def _get_test_row(token: str) -> Optional[dict]:
    conn = _connect()
    try:
        cur = conn.execute("SELECT token, user_id, start_ts, form_url, completed, score, submission_ts, rewarded FROM tests WHERE token = ?;", (token,))
        r = cur.fetchone()
        if not r:
            return None
        return {
            "token": r[0],
            "user_id": r[1],
            "start_ts": r[2],
            "form_url": r[3],
            "completed": bool(r[4]),
            "score": r[5],
            "submission_ts": r[6],
            "rewarded": bool(r[7]),
        }
    except Exception:
        logger.exception("Failed to read test row for %s", token)
        return None
    finally:
        conn.close()


def _insert_token(token: str, user_id: int, start_ts: int, form_url: str):
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO tests (token, user_id, start_ts, form_url) VALUES (?, ?, ?, ?);",
                (token, int(user_id), int(start_ts), form_url),
            )
    except Exception:
        logger.exception("Failed to insert token %s for user %s", token, user_id)
    finally:
        conn.close()


def _mark_completed(token: str, score: str):
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "UPDATE tests SET completed = 1, score = ?, submission_ts = ? WHERE token = ?;",
                (str(score), int(time.time()), token),
            )
    except Exception:
        logger.exception("Failed to mark completed for %s", token)
    finally:
        conn.close()


def _mark_rewarded(token: str):
    conn = _connect()
    try:
        with conn:
            conn.execute("UPDATE tests SET rewarded = 1 WHERE token = ?;", (token,))
    except Exception:
        logger.exception("Failed to mark rewarded for %s", token)
    finally:
        conn.close()


# --- handlers ---


def get_test_handler(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user:
        return

    _ensure_table()

    if not FORM_PREFILL_URL:
        update.message.reply_text("❌ Server not configured for forms. Contact admin.")
        logger.warning("FORM_PREFILL_URL not set")
        return

    token = _gen_token()
    start_ts = int(time.time())

    # populate prefill URL by replacing placeholders {token} and {start_ts} and optionally {user_id}
    try:
        form_url = FORM_PREFILL_URL.format(token=token, start_ts=start_ts, user_id=user.id)
    except Exception:
        # fallback: simple replace
        form_url = FORM_PREFILL_URL.replace("{token}", token).replace("{start_ts}", str(start_ts)).replace("{user_id}", str(user.id))

    # store
    _insert_token(token, user.id, start_ts, form_url)

    # reply with button
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Open test (prefilled)", url=form_url)]])
    update.message.reply_text(
        f"🔐 Your token: `{token}`\n"
        "Click the button below to open the test (token will be auto-filled in the form).",
        parse_mode="Markdown",
        reply_markup=kb,
    )


def find_token_handler(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        return

    args = context.args if getattr(context, "args", None) is not None else []
    if not args:
        update.message.reply_text("Usage: /find_token <TOKEN>")
        return
    token = args[0].strip()
    row = _get_test_row(token)
    if not row:
        update.message.reply_text(f"Token `{token}` not found.", parse_mode="Markdown")
        return

    start_h = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(row["start_ts"]))
    txt = (
        f"Token: `{row['token']}`\n"
        f"User id: `{row['user_id']}`\n"
        f"Start time: `{start_h}`\n"
        f"Completed: `{row['completed']}`\n"
        f"Score: `{row['score']}`\n"
        f"Rewarded: `{row['rewarded']}`\n"
        f"Form URL: {row['form_url'] or '(none)'}"
    )
    # admin inline option to send reward message
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✉️ Send reward message to user", callback_data=f"test_send:{token}")]])
    update.message.reply_text(txt, parse_mode="Markdown", reply_markup=kb)


def report_handler(update: Update, context: CallbackContext):
    """Admin command to mark token as completed and optionally send message to the user:
       /report <TOKEN> <SCORE>
    """
    user = update.effective_user
    if not user or not _is_admin(user.id):
        return

    args = context.args if getattr(context, "args", None) is not None else []
    if len(args) < 2:
        update.message.reply_text("Usage: /report <TOKEN> <SCORE>  (admin only)")
        return
    token = args[0].strip()
    score = " ".join(args[1:]).strip()

    row = _get_test_row(token)
    if not row:
        update.message.reply_text(f"Token `{token}` not found.", parse_mode="Markdown")
        return

    _mark_completed(token, score)
    row = _get_test_row(token)
    start_h = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(row["start_ts"]))
    report_text = (
        f"Report for `{token}`:\n"
        f"User id: `{row['user_id']}`\n"
        f"Start time: `{start_h}`\n"
        f"Score: `{score}`"
    )

    # send admin a message with button to send the reward
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✉️ Send reward message to user", callback_data=f"test_send:{token}")]])
    update.message.reply_text(report_text, parse_mode="Markdown", reply_markup=kb)


def callback_query_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    if not query:
        return
    user = query.from_user
    data = query.data or ""
    if not data.startswith("test_send:"):
        return
    token = data.split(":", 1)[1]
    if not _is_admin(user.id):
        query.answer("Unauthorized", show_alert=True)
        return

    row = _get_test_row(token)
    if not row:
        query.answer("Token not found", show_alert=True)
        return

    if row.get("rewarded"):
        query.answer("Already rewarded.", show_alert=True)
        return

    # try sending reward message
    try:
        context.bot.send_message(chat_id=row["user_id"], text=REWARD_MESSAGE)
        _mark_rewarded(token)
        query.answer("Reward message sent", show_alert=True)
        query.edit_message_text(f"Reward message sent to `{row['user_id']}` for token `{token}`.", parse_mode="Markdown")
    except Exception as e:
        logger.exception("Failed to send reward message to user %s for token %s", row["user_id"], token)
        query.answer("Failed to send message. Check logs.", show_alert=True)


def setup(dispatcher):
    _ensure_table()
    dispatcher.add_handler(CommandHandler("get_test", get_test_handler))
    dispatcher.add_handler(CommandHandler("find_token", find_token_handler))
    dispatcher.add_handler(CommandHandler("report", report_handler))
    dispatcher.add_handler(CallbackQueryHandler(callback_query_handler))
    logger.info("test_form feature loaded. FORM_PREFILL_URL set? %s", bool(FORM_PREFILL_URL))
