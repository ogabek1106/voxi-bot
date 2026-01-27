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
from database import get_user_mode, set_user_mode, clear_user_mode
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    CallbackContext,
    CallbackQueryHandler,
    MessageHandler,
    Filters,
)

from database import (
    get_active_test,
    save_test_answer,
    save_test_score,
    get_user_name,
    set_user_name,
)

logger = logging.getLogger(__name__)
TEST_MODE = "in_test"
DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "/data/data.db"))
SQLITE_TIMEOUT = 5
MOSCOW_TZ = timezone(timedelta(hours=3))

EXTRA_GRACE_SECONDS = 3  # UI grace time


# ---------- helpers ----------

def _connect():
    return sqlite3.connect(
        DB_PATH,
        timeout=SQLITE_TIMEOUT,
        check_same_thread=False,
    )


def _gen_token(length=7):
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def _get_existing_token(user_id: int, test_id: int):
    conn = _connect()
    cur = conn.execute(
        """
        SELECT token, finished_at
        FROM test_scores
        WHERE user_id = ?
          AND test_id = ?
        ORDER BY finished_at DESC
        LIMIT 1;
        """,
        (user_id, test_id),
    )
    row = cur.fetchone()
    conn.close()

    if not row:
        return None, None

    token, finished_at = row
    return token, finished_at is not None


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


def _format_timer(seconds):
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"


def _time_progress_bar(left: int, total: int, width: int = 15) -> str:
    ratio = max(0, min(1, left / total))
    filled = int(ratio * width)
    empty = width - filled
    return f"[{'▓' * filled}{'-' * empty}]"


# ---------- CORE START LOGIC (USED BY BOTH ENTRY POINTS) ----------

def _start_test_core(update: Update, context: CallbackContext, user_id: int):
    try:
        active_test = get_active_test()
        if not active_test:
            update.effective_chat.send_message("❌ No active test.")
            return

        test_id = active_test[0]

        existing_token, is_finished = _get_existing_token(user_id, test_id)

        if existing_token and is_finished:
            update.effective_chat.send_message(
                "❌ You already passed this test.\n\n"
                f"🔑 Your token: <code>{existing_token}</code>\n"
                "📊 Send /result to see your result.",
                parse_mode="HTML",
            )
            return

        token = existing_token if existing_token else _gen_token()
        start_ts, limit_min = _save_attempt(token, user_id, active_test)
        total_seconds = limit_min * 60 + EXTRA_GRACE_SECONDS

        questions = _load_questions(test_id)
        if not questions:
            update.effective_chat.send_message("❌ Test has no questions.")
            return

        chat_id = update.effective_chat.id

        context.user_data.pop("awaiting_test_name", None)
        context.user_data.update({
            "chat_id": chat_id,
            "token": token,
            "start_ts": start_ts,
            "limit_min": limit_min,
            "context_test_id": test_id,
            "total_seconds": total_seconds,
            "questions": questions,
            "answers": {},
            "skipped": set(),
            "index": 0,
            "finished": False,
            "timer_msg_id": None,
            "question_msg_id": None,
            "time_left": None,
            "auto_finished": False,
        })

        bot = context.bot

        bot.send_message(chat_id, f"🔑 <b>Your token:</b> <code>{token}</code>", parse_mode="HTML")

        timer_msg = bot.send_message(
            chat_id,
            f"⏱ <b>Time left:</b> {_format_timer(_time_left(start_ts, limit_min))}",
            parse_mode="HTML",
        )
        context.user_data["timer_msg_id"] = timer_msg.message_id

        _render_question(context)

        context.job_queue.run_repeating(
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

    finally:
        if not context.user_data.get("questions"):
            clear_user_mode(user_id)


# ---------- ENTRY POINT (BUTTON) ----------

def start_test_entry(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    user_id = query.from_user.id

    if get_user_mode(user_id) is not None:
        return

    set_user_mode(user_id, TEST_MODE)

    if not get_user_name(user_id):
        context.user_data.pop("awaiting_test_name", None)
        context.user_data["awaiting_test_name"] = True

        query.edit_message_text(
            "👤 Before starting the test, please enter your *full name*.\n\n"
            "✍️ Just send your name as a message.",
            parse_mode="Markdown",
        )
        return

    _start_test_core(update, context, user_id)


# ---------- NAME CAPTURE (TEXT) ----------

def capture_test_name(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user:
        return

    if get_user_mode(user.id) != TEST_MODE:
        return

    if not context.user_data.get("awaiting_test_name"):
        update.message.reply_text(
            "⚠️ Test session is not ready.\nPlease start again with /get_test."
        )
        clear_user_mode(user.id)
        return

    name = update.message.text.strip()
    if len(name) < 3:
        update.message.reply_text("❗ Please enter a valid full name.")
        return

    set_user_name(user.id, name)

    context.user_data.pop("awaiting_test_name", None)

    update.message.reply_text(
        f"✅ Thank you, *{name}*.\n\nStarting your test now…",
        parse_mode="Markdown",
    )

    _start_test_core(update, context, user.id)


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
        context.user_data["time_left"] = 0
        context.user_data["auto_finished"] = True
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


# ---------- SETUP ----------

def setup(dispatcher, bot=None):
    dispatcher.add_handler(CallbackQueryHandler(start_test_entry, pattern="^start_test$"))
    dispatcher.add_handler(
        MessageHandler(Filters.text & ~Filters.command, capture_test_name),
        group=2,
    )
    dispatcher.add_handler(CallbackQueryHandler(answer_handler, pattern="^ans\\|"))
    dispatcher.add_handler(CallbackQueryHandler(lambda u, c: nav_handler(u, c, -1), pattern="^prev$"))
    dispatcher.add_handler(CallbackQueryHandler(lambda u, c: nav_handler(u, c, 1), pattern="^next$"))
    dispatcher.add_handler(CallbackQueryHandler(noop_handler, pattern="^noop$"))
    dispatcher.add_handler(CallbackQueryHandler(finish_handler, pattern="^finish$"))
    logger.info("Feature loaded: start_test")
