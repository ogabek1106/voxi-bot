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
    return max(0, limit_min * 60 - elapsed)


def _format_timer(seconds):
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"


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

    questions = _load_questions(active_test[0])
    if not questions:
        query.edit_message_text("❌ Test has no questions.")
        return

    # reset state
    context.user_data.clear()
    context.user_data.update({
        "token": token,
        "start_ts": start_ts,
        "limit_min": limit_min,
        "questions": questions,
        "answers": {},
        "index": 0,
        "finished": False,
        "token_msg_id": None,
        "timer_msg_id": None,
        "question_msg_id": None,
    })

    chat_id = query.message.chat_id
    bot = query.bot

    # 1️⃣ TOKEN MESSAGE (static)
    token_msg = bot.send_message(
        chat_id=chat_id,
        text=f"🔑 Your token: {token}"
    )
    context.user_data["token_msg_id"] = token_msg.message_id

    # 2️⃣ TIMER MESSAGE (editable)
    timer_msg = bot.send_message(
        chat_id=chat_id,
        text="⏱ Time left: calculating..."
    )
    context.user_data["timer_msg_id"] = timer_msg.message_id

    # 3️⃣ QUESTION MESSAGE
    _render_question(update, context)


# ---------- rendering ----------

def _render_question(update: Update, context: CallbackContext):
    if context.user_data.get("finished"):
        return

    bot = update.callback_query.bot
    chat_id = update.callback_query.message.chat_id

    idx = context.user_data["index"]
    questions = context.user_data["questions"]
    _, q_text, a, b, c, d = questions[idx]

    # update timer
    left = _time_left(context.user_data["start_ts"], context.user_data["limit_min"])
    if left <= 0:
        _auto_finish(update, context)
        return

    bot.edit_message_text(
        chat_id=chat_id,
        message_id=context.user_data["timer_msg_id"],
        text=f"⏱ Time left: {_format_timer(left)}",
    )

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
            chat_id=chat_id,
            text=q_text,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        context.user_data["question_msg_id"] = msg.message_id
    else:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=context.user_data["question_msg_id"],
            text=q_text,
            reply_markup=InlineKeyboardMarkup(buttons),
        )


# ---------- handlers ----------

def answer_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    _, idx, choice = query.data.split("|")
    context.user_data["answers"][int(idx)] = choice

    _render_question(update, context)


def nav_handler(update: Update, context: CallbackContext, direction: int):
    query = update.callback_query
    query.answer()

    context.user_data["index"] += direction
    context.user_data["index"] = max(
        0,
        min(context.user_data["index"], len(context.user_data["questions"]) - 1)
    )

    _render_question(update, context)


def finish_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    _finish(update, context, manual=True)


# ---------- finish ----------

def _auto_finish(update: Update, context: CallbackContext):
    _finish(update, context, manual=False)


def _finish(update: Update, context: CallbackContext, manual: bool):
    context.user_data["finished"] = True
    bot = update.callback_query.bot
    chat_id = update.callback_query.message.chat_id
    token = context.user_data["token"]

    # delete timer & question
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
