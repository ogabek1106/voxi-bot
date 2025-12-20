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

from database import get_active_test

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "/data/data.db"))
SQLITE_TIMEOUT = 5
MOSCOW_TZ = timezone(timedelta(hours=3))

EXTRA_GRACE_SECONDS = 15  # ✅ UI grace time


# ---------- helpers ----------

def _connect():
    return sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT, check_same_thread=False)


def _gen_token(length=7):
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def _moscow_time_str():
    return datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _save_attempt(token, user_id, active_test):
    test_id, name, level, q_count, time_limit, _ = active_test
    start_ts = int(time.time())

    conn = _connect()
    with conn:
        conn.execute(
            """
            INSERT INTO tests
            (token, user_id, start_ts, completed, test_id, name, level,
             question_count, time_limit, created_at, start_ts_human)
            VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                token,
                user_id,
                start_ts,
                test_id,
                name,
                level,
                q_count,
                time_limit,
                int(time.time()),
                _moscow_time_str(),
            ),
        )
    conn.close()

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
            chat_id=chat_id,
            message_id=data["timer_msg_id"],
            text=f"⏱ <b>Time left:</b> {_format_timer(left)}\n{bar}",
            parse_mode="HTML",
        )
    except Exception:
        pass


def _auto_finish_from_job(context: CallbackContext, data: dict):
    bot = context.bot
    chat_id = data["chat_id"]
    token = data["token"]

    try:
        bot.delete_message(chat_id, data["question_msg_id"])
    except Exception:
        pass

    try:
        bot.delete_message(chat_id, data["timer_msg_id"])
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

    context.user_data.clear()
    context.user_data.update({
        "token": token,
        "start_ts": start_ts,
        "limit_min": limit_min,
        "total_seconds": total_seconds,
        "questions": questions,
        "answers": {},                 # 🔧 QA FIX
        "skipped": set(),               # 🔧 QA FIX
        "skipped_msg_id": None,         # 🔧 QA FIX
        "index": 0,
        "finished": False,
        "token_msg_id": None,
        "timer_msg_id": None,
        "question_msg_id": None,
        "timer_job": None,
    })

    chat_id = query.message.chat_id
    bot = query.bot

    token_msg = bot.send_message(
        chat_id,
        f"🔑 <b>Your token:</b> <code>{token}</code>",
        parse_mode="HTML",
    )
    context.user_data["token_msg_id"] = token_msg.message_id

    initial_left = _time_left(start_ts, limit_min)
    bar = _time_progress_bar(initial_left, total_seconds)

    timer_msg = bot.send_message(
        chat_id,
        f"⏱ <b>Time left:</b> {_format_timer(initial_left)}\n{bar}",
        parse_mode="HTML",
    )
    context.user_data["timer_msg_id"] = timer_msg.message_id

    _render_question(update, context)

    job = context.job_queue.run_repeating(
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

    context.user_data["timer_job"] = job


# ---------- rendering ----------

def _render_question(update: Update, context: CallbackContext):
    if context.user_data.get("finished"):
        return

    bot = update.callback_query.bot
    chat_id = update.callback_query.message.chat_id

    idx = context.user_data["index"]
    questions = context.user_data["questions"]
    _, q_text, a, b, c, d = questions[idx]

    # 🔧 QA FIX: show selected answer if exists
    selected_text = ""
    if idx in context.user_data["answers"]:
        key = context.user_data["answers"][idx]
        selected_text = f"\n\n✅ <b>You selected:</b>\n{ {'a': a, 'b': b, 'c': c, 'd': d}[key] }"

    text = f"<b>Question {idx + 1}</b>\n\n{q_text}{selected_text}"

    buttons = [
        [InlineKeyboardButton(a, callback_data=f"ans|{idx}|a")],
        [InlineKeyboardButton(b, callback_data=f"ans|{idx}|b")],
        [InlineKeyboardButton(c, callback_data=f"ans|{idx}|c")],
        [InlineKeyboardButton(d, callback_data=f"ans|{idx}|d")],
        [
            InlineKeyboardButton("⬅️", callback_data="prev"),
            InlineKeyboardButton(f"{idx+1}/{len(questions)}", callback_data="noop"),
            InlineKeyboardButton("➡️", callback_data="next"),
        ],
        [InlineKeyboardButton("🏁 Finish", callback_data="finish")],
    ]

    if context.user_data["question_msg_id"] is None:
        msg = bot.send_message(
            chat_id,
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML",
        )
        context.user_data["question_msg_id"] = msg.message_id
    else:
        bot.edit_message_text(
            chat_id,
            context.user_data["question_msg_id"],
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML",
        )

    _update_skipped_message(update, context)  # 🔧 QA FIX


# ---------- skipped message ----------

def _update_skipped_message(update: Update, context: CallbackContext):
    bot = update.callback_query.bot
    chat_id = update.callback_query.message.chat_id

    skipped = sorted(context.user_data["skipped"])
    msg_id = context.user_data.get("skipped_msg_id")

    if not skipped:
        if msg_id:
            try:
                bot.delete_message(chat_id, msg_id)
            except Exception:
                pass
            context.user_data["skipped_msg_id"] = None
        return

    text = "⚠️ <b>Skipped questions:</b> " + ", ".join(str(i + 1) for i in skipped)

    if msg_id:
        try:
            bot.edit_message_text(chat_id, msg_id, text, parse_mode="HTML")
        except Exception:
            pass
    else:
        msg = bot.send_message(chat_id, text, parse_mode="HTML")
        context.user_data["skipped_msg_id"] = msg.message_id


# ---------- handlers ----------

def answer_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer("Noted ✅", show_alert=False)

    _, idx, choice = query.data.split("|")
    idx = int(idx)

    context.user_data["answers"][idx] = choice
    context.user_data["skipped"].discard(idx)

    if idx < len(context.user_data["questions"]) - 1:
        context.user_data["index"] = idx + 1

    _render_question(update, context)


def nav_handler(update: Update, context: CallbackContext, direction: int):
    query = update.callback_query
    query.answer()

    current = context.user_data["index"]

    if current not in context.user_data["answers"]:
        context.user_data["skipped"].add(current)

    context.user_data["index"] = max(
        0,
        min(current + direction, len(context.user_data["questions"]) - 1)
    )

    _render_question(update, context)


def finish_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    job = context.user_data.get("timer_job")
    if job:
        job.schedule_removal()

    _finish(update, context, manual=True)


# ---------- finish (UNCHANGED) ----------

def _finish(update: Update, context: CallbackContext, manual: bool):
    context.user_data["finished"] = True
    bot = update.callback_query.bot
    chat_id = update.callback_query.message.chat_id
    token = context.user_data["token"]

    try:
        bot.delete_message(chat_id, context.user_data["timer_msg_id"])
    except Exception:
        pass

    try:
        bot.delete_message(chat_id, context.user_data["question_msg_id"])
    except Exception:
        pass

    msg = (
        "⏰ Time reached!\nYour answers were auto-submitted.\n\n"
        f"🔑 Your token: {token}\n"
        f"To see your result, send:\n/result {token}"
        if not manual else
        "✅ Your answers were submitted!\n\n"
        f"🔑 Your token: {token}\n"
        f"To see your result, send:\n/result {token}"
    )

    bot.send_message(chat_id, msg)


# ---------- setup ----------

def setup(dispatcher, bot=None):
    dispatcher.add_handler(CallbackQueryHandler(start_test_entry, pattern="^start_test$"))
    dispatcher.add_handler(CallbackQueryHandler(answer_handler, pattern="^ans\\|"))
    dispatcher.add_handler(CallbackQueryHandler(lambda u, c: nav_handler(u, c, -1), pattern="^prev$"))
    dispatcher.add_handler(CallbackQueryHandler(lambda u, c: nav_handler(u, c, 1), pattern="^next$"))
    dispatcher.add_handler(CallbackQueryHandler(finish_handler, pattern="^finish$"))

    logger.info("Feature loaded: start_test")
