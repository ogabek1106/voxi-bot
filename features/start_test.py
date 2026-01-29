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
from admins import ADMIN_IDS
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

EXTRA_GRACE_SECONDS = 0  # UI grace time


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

def _clear_previous_attempt(user_id: int, test_id: int):
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT token
            FROM test_scores
            WHERE user_id = ? AND test_id = ?
            """,
            (user_id, test_id),
        )
        row = cur.fetchone()

        if row:
            token = row[0]
            conn.execute(
                "DELETE FROM test_answers WHERE token = ? AND test_id = ?;",
                (token, test_id),
            )
            conn.execute(
                "DELETE FROM test_scores WHERE user_id = ? AND test_id = ?;",
                (user_id, test_id),
            )

        conn.commit()
    finally:
        conn.close()


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

def _get_skipped_questions(context):
    skipped = context.user_data.get("skipped", set())
    answered = set(context.user_data["answers"].keys())
    return sorted(i for i in skipped if i not in answered)

def _update_skip_warning(context):
    bot = context.bot
    chat_id = context.user_data["chat_id"]

    skipped = _get_skipped_questions(context)
    msg_id = context.user_data.get("skip_warning_msg_id")

    if not skipped:
        if msg_id:
            try:
                bot.delete_message(chat_id, msg_id)
            except Exception:
                pass
            context.user_data.pop("skip_warning_msg_id", None)
        return

    numbers = ", ".join(str(i + 1) for i in skipped)
    text = f"⚠️ You skipped questions: {numbers}"

    if msg_id:
        try:
            bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=msg_id,
            )
        except Exception:
            pass
    else:
        msg = bot.send_message(chat_id, text)
        context.user_data["skip_warning_msg_id"] = msg.message_id




# ---------- CORE START LOGIC (USED BY BOTH ENTRY POINTS) ----------

def _start_test_core(update: Update, context: CallbackContext, user_id: int):
    active_test = get_active_test()
    if not active_test:
        update.effective_chat.send_message("❌ No active test.")
        return

    test_id = active_test[0]

    existing_token, is_finished = _get_existing_token(user_id, test_id)
    
    # 🔓 Admins: reset previous attempt completely
    if user_id in ADMIN_IDS:
        _clear_previous_attempt(user_id, test_id)
        existing_token = None
        is_finished = False


    if existing_token and is_finished and user_id not in ADMIN_IDS:
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
        "context_user_id": user_id,   # ✅ ADD
        "token": token,
        "start_ts": start_ts,
        "limit_min": limit_min,
        "context_test_id": test_id,
        "total_seconds": total_seconds,
        "questions": questions,
        "context_user_id": user_id,
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

    job = context.job_queue.run_repeating(
        _timer_job,
        interval=1,
        first=1,
        context={
            "chat_id": chat_id,
            "context_user_id": user_id,  # 🔥 REQUIRED
            "token": token,
            "start_ts": start_ts,
            "limit_min": limit_min,
            "total_seconds": total_seconds,
            "timer_msg_id": context.user_data["timer_msg_id"],
            "question_msg_id": context.user_data["question_msg_id"],
            "finished": False,
            "last_ui_update": 0,
        },
    )
    context.user_data["timer_job"] = job

# ---------- ENTRY POINT (BUTTON) ----------

def start_test_entry(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    user_id = query.from_user.id

    if get_user_mode(user_id) is not None:
        query.answer("⏳ You already have an active session.", show_alert=True)
        return

    set_user_mode(user_id, TEST_MODE)

    if user_id in ADMIN_IDS or not get_user_name(user_id):

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

    # ⏰ AUTO-FINISH CHECK (EVERY SECOND)
    if left <= 0:
        data["finished"] = True
        context.job.schedule_removal()

        chat_id = data["chat_id"]

        context.job_queue.run_once(
            lambda ctx: _auto_finish_via_dispatcher(ctx, chat_id),
            when=0,
        )
        return

    # 🖥 UI UPDATE THROTTLE (EVERY 15 SECONDS)
    now = int(time.time())
    last_ui = data.get("last_ui_update", 0)

    if now - last_ui < 15:
        return

    data["last_ui_update"] = now

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

# ---------- RENDERING & HANDLERS ----------

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

    if idx not in context.user_data["answers"]:
        buttons.extend([
            [InlineKeyboardButton(a, callback_data=f"ans|{idx}|a")],
            [InlineKeyboardButton(b, callback_data=f"ans|{idx}|b")],
            [InlineKeyboardButton(c, callback_data=f"ans|{idx}|c")],
            [InlineKeyboardButton(d, callback_data=f"ans|{idx}|d")],
        ])

    buttons.append([
        InlineKeyboardButton("⬅️", callback_data="prev"),
        InlineKeyboardButton(f"{idx + 1}/{len(context.user_data['questions'])}", callback_data="noop"),
        InlineKeyboardButton("➡️", callback_data="next"),
    ])

    buttons.append([InlineKeyboardButton("🏁 Finish", callback_data="finish")])

    if context.user_data.get("question_msg_id") is None:
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


def answer_handler(update: Update, context: CallbackContext):
    if context.user_data.get("finished"):
        update.callback_query.answer("⏰ Test already finished", show_alert=True)
        return
    query = update.callback_query
    query.answer("Noted ✅")

    _, idx, choice = query.data.split("|")
    idx = int(idx)

    context.user_data["answers"][idx] = choice
    context.user_data["skipped"].discard(idx)

    save_test_answer(
        context.user_data["token"],
        context.user_data["context_test_id"],
        idx + 1,
        choice,
    )

    if idx < len(context.user_data["questions"]) - 1:
        context.user_data["index"] = idx + 1

    _render_question(context)
    _update_skip_warning(context)

def nav_handler(update: Update, context: CallbackContext, direction: int):
    if context.user_data.get("finished"):
        update.callback_query.answer("⏰ Test already finished", show_alert=True)
        return
    query = update.callback_query
    query.answer()

    current = context.user_data["index"]
    total = len(context.user_data["questions"])

    new_index = max(0, min(current + direction, total - 1))

    # 🚫 If index does not change, do nothing
    if new_index == current:
        return

    # ✅ Ensure skipped set exists
    skipped = context.user_data.setdefault("skipped", set())

    # 🔴 Mark skip ONLY when leaving an unanswered question
    if current not in context.user_data["answers"]:
        skipped.add(current)

    # ✅ Now move
    context.user_data["index"] = new_index

    _render_question(context)
    _update_skip_warning(context)

def noop_handler(update: Update, context: CallbackContext):
    update.callback_query.answer()


def finish_handler(update: Update, context: CallbackContext):
    if context.user_data.get("finished"):
        update.callback_query.answer("⏰ Test already finished", show_alert=True)
        return
    # ⏰ If test already auto-finished, ignore manual finish
    if context.user_data.get("auto_finished"):
        return
    query = update.callback_query
    query.answer()

    total = len(context.user_data["questions"])
    answered = len(context.user_data["answers"])

    # ❌ NOT ALL ANSWERED → WARN
    if answered < total:
        skipped = _get_skipped_questions(context)

        if skipped:
            numbers = ", ".join(str(i + 1) for i in skipped)
            text = (
                f"⚠️ You have unanswered questions.\n\n"
                f"Skipped questions: {numbers}\n\n"
                "Do you really want to finish?"
            )
        else:
            text = (
                "⚠️ You have unanswered questions.\n\n"
                "Do you really want to finish?"
            )    

        query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("⚠️ Finish anyway", callback_data="finish_anyway"),
                    InlineKeyboardButton("❌ Continue test", callback_data="continue_test"),
                ]
            ]),
        )
        return


    job = context.user_data.get("timer_job")
    if job:
        job.schedule_removal()

    _finish(context, context.user_data, manual=True)
    
def finish_anyway_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    job = context.user_data.get("timer_job")
    if job:
        job.schedule_removal()

    _finish(context, context.user_data, manual=True)


def continue_test_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer("Continue answering ✍️")

    _render_question(context)


def _load_correct_answers(test_id):
    conn = _connect()
    cur = conn.execute(
        """
        SELECT question_number, correct_answer
        FROM test_questions
        WHERE test_id = ?;
        """,
        (test_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return {qn - 1: ans for qn, ans in rows}

def _auto_finish_via_dispatcher(context: CallbackContext, chat_id: int):
    context_user_id = context.job.context["context_user_id"]
    user_data = context.dispatcher.user_data.get(context_user_id)
    if not user_data:
        return

    # mark auto-finish flags
    user_data["auto_finished"] = True
    user_data["finished"] = True
    user_data["time_left"] = 0

    # call normal finish WITHOUT warnings
    fake_update = Update(update_id=0)
    fake_update._effective_user = None
    fake_update._effective_chat = None

    _finish(context, user_data, manual=False)


def _finish(context: CallbackContext, user_data: dict, manual: bool):
    user_data["finished"] = True

    if manual:
        user_data["time_left"] = _time_left(
            user_data["start_ts"],
            user_data["limit_min"],
        )
        user_data["auto_finished"] = False

    total = len(user_data["questions"])
    correct_map = _load_correct_answers(user_data["context_test_id"])

    correct = sum(
        1 for idx, selected in user_data["answers"].items()
        if correct_map.get(idx) == selected
    )

    score = round((correct / total) * 100, 2)

    save_test_score(
        token=user_data["token"],
        test_id=user_data["context_test_id"],
        user_id=user_data["context_user_id"],
        total_questions=total,
        correct_answers=correct,
        score=score,
        max_score=100,
        time_left=user_data.get("time_left", 0),
        auto_finished=user_data["auto_finished"],
    )

    bot = context.bot
    chat_id = user_data["chat_id"]
    token = user_data["token"]

    for key in ("timer_msg_id", "question_msg_id"):
        try:
            bot.delete_message(chat_id, user_data[key])
        except Exception:
            pass

    # delete skipped warning if exists
    skip_msg_id = user_data.get("skip_warning_msg_id")
    if skip_msg_id:
        try:
            bot.delete_message(chat_id, skip_msg_id)
        except Exception:
            pass
        user_data.pop("skip_warning_msg_id", None)

    bot.send_message(
        chat_id,
        "✅ Your answers were submitted!\n\n"
        f"🔑 Your token: {token}\n"
        "To see your result, send:\n"
        f"/result {token}"
    )
    clear_user_mode(user_data["context_user_id"])

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
    dispatcher.add_handler(CallbackQueryHandler(finish_anyway_handler, pattern="^finish_anyway$"))
    dispatcher.add_handler(CallbackQueryHandler(continue_test_handler, pattern="^continue_test$"))
    dispatcher.add_handler(CallbackQueryHandler(noop_handler, pattern="^noop$"))
    dispatcher.add_handler(CallbackQueryHandler(finish_handler, pattern="^finish$"))
    logger.info("Feature loaded: start_test")
