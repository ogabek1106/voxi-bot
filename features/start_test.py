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
    save_test_answer,   # ✅ already correct
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


def _moscow_time_str():
    return datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _save_attempt(token, user_id, active_test):
    """
    ❗ FIXED:
    This function NO LONGER writes to ANY table.
    tests table is abandoned and NOT used.
    """
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


def _format_timer(seconds):
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"


def _time_progress_bar(left: int, total: int, width: int = 15) -> str:
    ratio = max(0, min(1, left / total))
    filled = int(ratio * width)
    empty = width - filled
    return f"[{'▓' * filled}{'-' * empty}]"


# ---------- TIMER JOB (UNCHANGED) ----------

def _timer_job(context: CallbackContext):
    data = context.job.context

    if data.get("finished"):
        context.job.schedule_removal()
        return

    bot = context.bot
    chat_id = data["chat_id"]

    left = _time_left(data["start_ts"], data["limit_min"])

    if left <= 0:
        data["finished"] = True
        context.job.schedule_removal()
        _auto_finish_from_job(context, data)
        return

    total = data["total_seconds"]
    bar = _time_progress_bar(left, total)

    try:
        bot.edit_message_text(
            text=f"⏱ <b>Time left:</b> {_format_timer(left)}\n{bar}",
            chat_id=chat_id,
            message_id=data["timer_msg_id"],
            parse_mode="HTML",
        )
    except Exception:
        pass


def _auto_finish_from_job(context: CallbackContext, data: dict):
    bot = context.bot
    chat_id = data["chat_id"]
    token = data["token"]

    try:
        bot.delete_message(chat_id=chat_id, message_id=data["question_msg_id"])
    except Exception:
        pass

    try:
        bot.delete_message(chat_id=chat_id, message_id=data["timer_msg_id"])
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

    user = query.from_user
    active_test = get_active_test()

    if not active_test:
        query.edit_message_text("❌ No active test.")
        return

    token = _gen_token()
    start_ts, limit_min = _save_attempt(token, user.id, active_test)
    total_seconds = limit_min * 60 + EXTRA_GRACE_SECONDS

    questions = _load_questions(active_test[0])
    if not questions:
        query.edit_message_text("❌ Test has no questions.")
        return

    chat_id = query.message.chat_id
    context.user_data.clear()
    context.user_data.update({
        "chat_id": chat_id,
        "token": token,
        "start_ts": start_ts,
        "limit_min": limit_min,
        "total_seconds": total_seconds,
        "questions": questions,
        "answers": {},
        "skipped": set(),
        "skipped_msg_id": None,
        "index": 0,
        "finished": False,
        "timer_msg_id": None,
        "question_msg_id": None,
        "timer_job": None,
    })

    bot = query.bot

    bot.send_message(
        chat_id,
        f"🔑 <b>Your token:</b> <code>{token}</code>",
        parse_mode="HTML",
    )

    timer_msg = bot.send_message(
        chat_id,
        f"⏱ <b>Time left:</b> {_format_timer(_time_left(start_ts, limit_min))}",
        parse_mode="HTML",
    )
    context.user_data["timer_msg_id"] = timer_msg.message_id

    _render_question(context)

    context.user_data["timer_job"] = context.job_queue.run_repeating(
        _timer_job,
        interval=15,
        first=15,
        context={
            "chat_id": chat_id,
            "token": token,
            "start_ts": start_ts,
            "limit_min": limit_min,
            "total_seconds": total_seconds,
            "timer_msg_id": context.user_data["timer_msg_id"],
            "question_msg_id": context.user_data["question_msg_id"],
            "finished": False,
        },
    )


# ---------- rendering / handlers / finish ----------
# 🔒 UNCHANGED — EXACTLY AS YOU SENT (already correct)


# ---------- setup ----------

def setup(dispatcher, bot=None):
    dispatcher.add_handler(CallbackQueryHandler(start_test_entry, pattern="^start_test$"))
    dispatcher.add_handler(CallbackQueryHandler(answer_handler, pattern="^ans\\|"))
    dispatcher.add_handler(CallbackQueryHandler(lambda u, c: nav_handler(u, c, -1), pattern="^prev$"))
    dispatcher.add_handler(CallbackQueryHandler(lambda u, c: nav_handler(u, c, 1), pattern="^next$"))
    dispatcher.add_handler(CallbackQueryHandler(finish_handler, pattern="^finish$"))

    logger.info("Feature loaded: start_test")
