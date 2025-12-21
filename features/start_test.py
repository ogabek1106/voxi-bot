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
    save_test_score,
)

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "/data/data.db"))
SQLITE_TIMEOUT = 5
MOSCOW_TZ = timezone(timedelta(hours=3))

EXTRA_GRACE_SECONDS = 15  # UI grace time

def _get_existing_token(user_id: int, test_id: int):
    """
    Returns:
    - (token, finished_bool) if attempt exists
    - (None, None) if no attempt
    """
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


# ---------- helpers ----------

def _connect():
    return sqlite3.connect(
        DB_PATH,
        timeout=SQLITE_TIMEOUT,
        check_same_thread=False,
    )


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
        (
            "⏰ Time reached!\n"
            "Your answers were auto-submitted.\n\n"
            f"🔑 Your token: {token}\n"
            "To see your result, send:\n"
            f"/result {token}"
        ),
    )


# ---------- entry point ----------

def start_test_entry(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    active_test = get_active_test()
    if not active_test:
        query.edit_message_text("❌ No active test.")
        return


    user_id = query.from_user.id
    test_id = active_test[0]

    existing_token, is_finished = _get_existing_token(user_id, test_id)

    if existing_token and is_finished:
        query.edit_message_text(
            "❌ You already passed this test.\n\n"
            f"🔑 Your token: <code>{existing_token}</code>\n"
            "📊 Send /result to see your result.",
            parse_mode="HTML",
        )
        return

    if existing_token and not is_finished:
        token = existing_token
    else:
        token = _gen_token()

    start_ts, limit_min = _save_attempt(token, user_id, active_test)

    
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
        "time_left": None,
        "auto_finished": False,
    })

    bot = query.bot

    bot.send_message(chat_id, f"🔑 <b>Your token:</b> <code>{token}</code>", parse_mode="HTML")

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


# ---------- rendering ----------

def _render_question(context: CallbackContext):
    if context.user_data.get("finished"):
        return

    bot = context.bot
    chat_id = context.user_data["chat_id"]
    idx = context.user_data["index"]

    _, q_text, a, b, c, d = context.user_data["questions"][idx]

    selected_text = ""
    if idx in context.user_data["answers"]:
        key = context.user_data["answers"][idx]
        selected_text = f"\n\n✅ <b>You selected:</b>\n{ {'a': a, 'b': b, 'c': c, 'd': d}[key] }"

    text = f"<b>Question {idx + 1}</b>\n\n{q_text}{selected_text}"

    buttons = []

    # ⛔ Answer buttons ONLY if question NOT answered yet
    if idx not in context.user_data["answers"]:
        buttons.extend([
            [InlineKeyboardButton(a, callback_data=f"ans|{idx}|a")],
            [InlineKeyboardButton(b, callback_data=f"ans|{idx}|b")],
            [InlineKeyboardButton(c, callback_data=f"ans|{idx}|c")],
            [InlineKeyboardButton(d, callback_data=f"ans|{idx}|d")],
        ])

    # ✅ Navigation buttons ALWAYS
    buttons.append([
        InlineKeyboardButton("⬅️", callback_data="prev"),
        InlineKeyboardButton(f"{idx + 1}/{len(context.user_data['questions'])}", callback_data="noop"),
        InlineKeyboardButton("➡️", callback_data="next"),
    ])

    # ✅ Finish ALWAYS
    buttons.append([InlineKeyboardButton("🏁 Finish", callback_data="finish")])


    if context.user_data["question_msg_id"] is None:
        msg = bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")
        context.user_data["question_msg_id"] = msg.message_id
    else:
        bot.edit_message_text(
            text=text,
            chat_id=chat_id,
            message_id=context.user_data["question_msg_id"],
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML",
        )

    _update_skipped_message(context)


def _update_skipped_message(context: CallbackContext):
    bot = context.bot
    chat_id = context.user_data["chat_id"]
    skipped = sorted(context.user_data["skipped"])
    msg_id = context.user_data["skipped_msg_id"]

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
        bot.edit_message_text(text, chat_id, msg_id, parse_mode="HTML")
    else:
        msg = bot.send_message(chat_id, text, parse_mode="HTML")
        context.user_data["skipped_msg_id"] = msg.message_id


# ---------- handlers ----------

def answer_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer("Noted ✅")

    _, idx, choice = query.data.split("|")
    idx = int(idx)

    context.user_data["answers"][idx] = choice
    context.user_data["skipped"].discard(idx)

    save_test_answer(context.user_data["token"], idx + 1, choice)

    if idx < len(context.user_data["questions"]) - 1:
        context.user_data["index"] = idx + 1

    _render_question(context)


def nav_handler(update: Update, context: CallbackContext, direction: int):
    query = update.callback_query
    query.answer()

    cur = context.user_data["index"]

    if cur not in context.user_data["answers"]:
        context.user_data["skipped"].add(cur)

    context.user_data["index"] = max(
        0,
        min(cur + direction, len(context.user_data["questions"]) - 1)
    )

    _render_question(context)


def noop_handler(update: Update, context: CallbackContext):
    update.callback_query.answer()


def finish_handler(update: Update, context: CallbackContext):
    query = update.callback_query

    if context.user_data["skipped"]:
        query.answer(
            "⚠️ Skipped questions: "
            + ", ".join(str(i + 1) for i in sorted(context.user_data["skipped"])),
            show_alert=True,
        )
        return

    query.answer()

    job = context.user_data.get("timer_job")
    if job:
        job.schedule_removal()

    _finish(update, context, manual=True)


# ---------- finish ----------

def _finish(update: Update, context: CallbackContext, manual: bool):
    context.user_data["finished"] = True

    if manual:
        context.user_data["time_left"] = _time_left(
            context.user_data["start_ts"],
            context.user_data["limit_min"],
        )
        context.user_data["auto_finished"] = False

    total = len(context.user_data["questions"])
    correct = len(context.user_data["answers"])
    score = round((correct / total) * 100, 2)

    save_test_score(
        token=context.user_data["token"],
        test_id=get_active_test()[0],
        user_id=context.user_data["chat_id"],
        total_questions=total,
        correct_answers=correct,
        score=score,
        max_score=100,
        time_left=context.user_data["time_left"],
        auto_finished=context.user_data["auto_finished"],
    )

    bot = context.bot
    chat_id = context.user_data["chat_id"]
    token = context.user_data["token"]

    for key in ("timer_msg_id", "question_msg_id"):
        try:
            bot.delete_message(chat_id, context.user_data[key])
        except Exception:
            pass

    bot.send_message(
        chat_id,
        "✅ Your answers were submitted!\n\n"
        f"🔑 Your token: {token}\n"
        "To see your result, send:\n"
        f"/result {token}"
    )


# ---------- setup ----------

def setup(dispatcher, bot=None):
    dispatcher.add_handler(CallbackQueryHandler(start_test_entry, pattern="^start_test$"))
    dispatcher.add_handler(CallbackQueryHandler(answer_handler, pattern="^ans\\|"))
    dispatcher.add_handler(CallbackQueryHandler(lambda u, c: nav_handler(u, c, -1), pattern="^prev$"))
    dispatcher.add_handler(CallbackQueryHandler(lambda u, c: nav_handler(u, c, 1), pattern="^next$"))
    dispatcher.add_handler(CallbackQueryHandler(noop_handler, pattern="^noop$"))
    dispatcher.add_handler(CallbackQueryHandler(finish_handler, pattern="^finish$"))
    logger.info("Feature loaded: start_test")
