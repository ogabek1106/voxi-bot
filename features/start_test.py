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
    save_test_answer,   # ✅ correct table
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
    ⚠️ CORRECTED:
    This function NO LONGER touches ANY database table.
    It only prepares timing values for runtime usage.
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


# ---------- TIMER JOB ----------

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

        # ✅ ADD (store auto finish timing in memory)
        context.user_data["time_left"] = 0
        context.user_data["auto_finished"] = 1

        _auto_finish_from_job(context, data)
        return

    bar = _time_progress_bar(left, data["total_seconds"])

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

        # ✅ ADD (timing placeholders)
        "time_left": None,
        "auto_finished": 0,
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


# ---------- finish ----------

def _finish(update: Update, context: CallbackContext, manual: bool):
    context.user_data["finished"] = True

    # ✅ ADD (manual finish timing)
    if manual:
        context.user_data["time_left"] = _time_left(
            context.user_data["start_ts"],
            context.user_data["limit_min"]
        )
        context.user_data["auto_finished"] = 0

    # ✅ ADD (persist timing into DB)
    try:
        conn = _connect()
        with conn:
            conn.execute(
                """
                UPDATE test_scores
                SET time_left = ?, auto_finished = ?
                WHERE token = ?;
                """,
                (
                    context.user_data.get("time_left"),
                    context.user_data.get("auto_finished"),
                    context.user_data["token"],
                ),
            )
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass

    bot = context.bot
    chat_id = context.user_data["chat_id"]
    token = context.user_data["token"]

    for key in ("timer_msg_id", "question_msg_id"):
        try:
            bot.delete_message(chat_id=chat_id, message_id=context.user_data[key])
        except Exception:
            pass

    bot.send_message(
        chat_id,
        (
            "✅ Your answers were submitted!\n\n"
            if manual else
            "⏰ Time reached!\nYour answers were auto-submitted.\n\n"
        ) +
        f"🔑 Your token: {token}\n"
        f"To see your result, send:\n/result {token}"
    )


# ---------- setup ----------

def setup(dispatcher, bot=None):
    dispatcher.add_handler(CallbackQueryHandler(start_test_entry, pattern="^start_test$"))
    dispatcher.add_handler(CallbackQueryHandler(answer_handler, pattern="^ans\\|"))
    dispatcher.add_handler(CallbackQueryHandler(lambda u, c: nav_handler(u, c, -1), pattern="^prev$"))
    dispatcher.add_handler(CallbackQueryHandler(lambda u, c: nav_handler(u, c, 1), pattern="^next$"))
    dispatcher.add_handler(CallbackQueryHandler(finish_handler, pattern="^finish$"))

    logger.info("Feature loaded: start_test")
