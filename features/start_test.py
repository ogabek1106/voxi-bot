# features/start_test.py
"""
Handles test execution AFTER user presses ▶️ Start button.
Buttons themselves are created in get_test.py
"""

import logging
import time
import random
import string
import sqlite3
import os
from datetime import datetime, timedelta, timezone

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    CallbackContext,
    CallbackQueryHandler,
)

from database import (
    get_active_test,
    save_test_answer,
)

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "/data/data.db"))
SQLITE_TIMEOUT = 5
MOSCOW_TZ = timezone(timedelta(hours=3))

EXTRA_GRACE_SECONDS = 15  # UI grace time


# ---------- helpers ----------

def _connect():
    return sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT, check_same_thread=False)


def _gen_token(length=7):
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def _save_attempt(token, user_id, active_test):
    _, _, _, _, time_limit, _ = active_test
    start_ts = int(time.time())
    return start_ts, time_limit


def _load_questions(test_id):
    conn = _connect()
    cur = conn.execute(
        """
        SELECT question_number, question_text, a, b, c, d
        FROM test_questions
        WHERE test_id = ?
        ORDER BY question_number;
        """,
        (test_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def _time_left(start_ts, limit_min):
    elapsed = int(time.time()) - start_ts
    total = limit_min * 60 + EXTRA_GRACE_SECONDS
    return max(0, total - elapsed)


# ---------- TIMER JOB ----------

def _timer_job(context: CallbackContext):
    data = context.job.context

    if data.get("finished"):
        context.job.schedule_removal()
        return

    left = _time_left(data["start_ts"], data["limit_min"])

    if left <= 0:
        data["finished"] = True
        context.job.schedule_removal()

        # 🟢 ADD: auto finish timing
        context.user_data["time_left"] = 0
        context.user_data["auto_finished"] = 1

        _auto_finish_from_job(context, data)
        return


def _auto_finish_from_job(context: CallbackContext, data: dict):
    bot = context.bot
    chat_id = data["chat_id"]
    token = data["token"]

    for key in ("question_msg_id", "timer_msg_id"):
        try:
            bot.delete_message(chat_id, data[key])
        except Exception:
            pass

    bot.send_message(
        chat_id,
        "⏰ Time reached!\nYour answers were auto-submitted.\n\n"
        f"🔑 Your token: {token}\n"
        f"To see your result, send:\n/result {token}"
    )


# ---------- entry point ----------

def start_test_entry(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    active_test = get_active_test()
    if not active_test:
        query.edit_message_text("❌ No active test.")
        return

    token = _gen_token()
    start_ts, limit_min = _save_attempt(token, query.from_user.id, active_test)

    context.user_data.clear()
    context.user_data.update({
        "token": token,
        "start_ts": start_ts,
        "limit_min": limit_min,

        # 🟢 ADD: timing placeholders
        "time_left": None,
        "auto_finished": 0,
    })

    query.bot.send_message(
        query.message.chat_id,
        f"🔑 <b>Your token:</b> <code>{token}</code>",
        parse_mode="HTML",
    )


# ---------- finish ----------

def _finish(update: Update, context: CallbackContext, manual: bool):
    context.user_data["finished"] = True

    # 🟢 ADD: save timing into DB
    time_left = _time_left(
        context.user_data["start_ts"],
        context.user_data["limit_min"]
    )

    auto_finished = 0 if manual else 1

    conn = _connect()
    try:
        with conn:
            conn.execute(
                """
                UPDATE test_scores
                SET time_left = ?, auto_finished = ?
                WHERE token = ?;
                """,
                (time_left, auto_finished, context.user_data["token"]),
            )
    except Exception:
        pass
    finally:
        conn.close()

    bot = context.bot
    chat_id = update.callback_query.message.chat_id
    token = context.user_data["token"]

    bot.send_message(
        chat_id,
        "✅ Your answers were submitted!\n\n"
        f"🔑 Your token: {token}\n"
        f"To see your result, send:\n/result {token}"
    )


# ---------- setup ----------

def setup(dispatcher, bot=None):
    dispatcher.add_handler(CallbackQueryHandler(start_test_entry, pattern="^start_test$"))
    logger.info("Feature loaded: start_test")
