# features/get_test.py
"""
Unified test flow (Aiogram 3)

Merged from:
 - get_test.py (v13)
 - start_test.py (v13)

Router-based, async, FSM-safe.
"""

import asyncio
import logging
import time
import random
import string
import sqlite3
import os
from typing import Dict

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

import admins
from features.sub_check import require_subscription
from database import (
    get_active_test,
    save_test_answer,
    save_test_score,
    get_user_name,
    set_user_name,
    get_user_mode,
    set_user_mode,
    clear_user_mode,
)

logger = logging.getLogger(__name__)
router = Router()

TEST_MODE = "in_test"
EXTRA_GRACE_SECONDS = 0

DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "/data/data.db"))
SQLITE_TIMEOUT = 5


# ─────────────────────────────
# DB helpers
# ─────────────────────────────

def _connect():
    return sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT, check_same_thread=False)

def _load_questions(test_id: str):
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

def _load_correct_answers(test_id: str):
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

def _get_existing_token(user_id: int, test_id: str):
    conn = _connect()
    cur = conn.execute(
        """
        SELECT token, finished_at
        FROM test_scores
        WHERE user_id = ? AND test_id = ?
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

def _clear_previous_attempt(user_id: int, test_id: str):
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT token FROM test_scores WHERE user_id = ? AND test_id = ?;",
            (user_id, test_id),
        )
        row = cur.fetchone()
        if row:
            token = row[0]
            conn.execute("DELETE FROM test_answers WHERE token = ? AND test_id = ?;", (token, test_id))
            conn.execute("DELETE FROM test_scores WHERE user_id = ? AND test_id = ?;", (user_id, test_id))
            conn.commit()
    finally:
        conn.close()


# ─────────────────────────────
# Helpers
# ─────────────────────────────

def _gen_token(length=7):
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))

def _format_timer(seconds: int) -> str:
    m, s = divmod(max(0, seconds), 60)
    return f"{m:02d}:{s:02d}"

def _time_left(start_ts, limit_min):
    elapsed = int(time.time()) - start_ts
    total = limit_min * 60 + EXTRA_GRACE_SECONDS
    return max(0, total - elapsed)

def _time_progress_bar(left: int, total: int, width: int = 15) -> str:
    ratio = max(0, min(1, left / total))
    filled = int(ratio * width)
    empty = width - filled
    return f"[{'▓' * filled}{'-' * empty}]"

def _get_skipped_questions(data: Dict):
    skipped = data.get("skipped", set())
    answered = set(data.get("answers", {}).keys())
    return sorted(i for i in skipped if i not in answered)

async def _update_skip_warning(state: FSMContext, bot, data: Dict):
    skipped = _get_skipped_questions(data)

    msg_id = data.get("skip_warn_msg_id")
    chat_id = data["chat_id"]

    if not skipped:
        if msg_id:
            try:
                await bot.delete_message(chat_id, msg_id)
            except Exception:
                pass
            await state.update_data(skip_warn_msg_id=None)
        return

    numbers = ", ".join(str(i + 1) for i in skipped)
    text = f"⚠️ <b>You skipped questions:</b> {numbers}"

    if msg_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=text,
                parse_mode="HTML",
            )

        except Exception:
            pass
        return

    msg = await bot.send_message(chat_id, text, parse_mode="HTML")
    await state.update_data(skip_warn_msg_id=msg.message_id)


# ─────────────────────────────
# /get_test
# ─────────────────────────────

@router.message(Command("get_test"))
async def get_test(message: Message, state: FSMContext):
    user = message.from_user
    if not user:
        return

    await state.clear()
    clear_user_mode(user.id)

    if not await require_subscription(message, state):
        return

    active = get_active_test()
    if not active:
        await message.answer("❌ No active tests at the moment.")
        return

    test_id, name, level, question_count, time_limit, _ = active

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="▶️ Start", callback_data="start_test"),
        InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_test"),
    ]])

    await message.answer(
        "🧪 <b>Active Test</b>\n\n"
        f"📌 Name: {name or '—'}\n"
        f"📊 Level: {level or '—'}\n"
        f"❓ Questions: {question_count or '—'}\n"
        f"⏱ Time limit: {time_limit or '—'} min\n\n"
        "🟢 Test is available.",
        parse_mode="HTML",
        reply_markup=keyboard,
    )


@router.callback_query(F.data == "cancel_test")
async def cancel_test(query: CallbackQuery, state: FSMContext):
    clear_user_mode(query.from_user.id)
    await state.clear()
    await query.message.edit_text("❌ Test start cancelled.")
    await query.answer()


# ─────────────────────────────
# Start test
# ─────────────────────────────

@router.callback_query(F.data == "start_test")
async def start_test_entry(query: CallbackQuery, state: FSMContext):
    await query.answer()
    user_id = query.from_user.id

    if not await require_subscription(query.message, state):
        return

    if get_user_mode(user_id) is not None:
        return

    set_user_mode(user_id, TEST_MODE)

    is_admin = user_id in getattr(admins, "ADMIN_IDS", set())

    if is_admin:
        set_user_name(user_id, None)

    if is_admin or not get_user_name(user_id):
        await state.update_data(awaiting_name=True)
        await query.message.edit_text(
            "👤 Before starting the test, please enter your <b>full name</b>.\n\n"
            "✍️ Just send your name as a message.",
            parse_mode="HTML",
        )
        return

    await _start_test_core(query.message.chat.id, state, user_id, query.bot)


@router.message()
async def capture_name(message: Message, state: FSMContext):
    user = message.from_user
    if not user or get_user_mode(user.id) != TEST_MODE:
        return

    data = await state.get_data()
    if not data.get("awaiting_name"):
        return

    name = message.text.strip()
    if len(name) < 3 or len(name) > 64:
        await message.answer("❗ Please enter a valid full name.")
        return

    set_user_name(user.id, name)
    await state.update_data(awaiting_name=False)

    await message.answer(f"✅ Thank you, <b>{name}</b>. Starting your test now…", parse_mode="HTML")
    await _start_test_core(message.chat.id, state, user.id, message.bot)


# ─────────────────────────────
# CORE ENGINE
# ─────────────────────────────

async def _start_test_core(chat_id: int, state: FSMContext, user_id: int, bot):
    
    active_test = get_active_test()
    if not active_test:
        await bot.send_message(chat_id, "❌ No active test.")
        clear_user_mode(user_id)
        return

    test_id, _, _, _, time_limit, _ = active_test

    token, finished = _get_existing_token(user_id, test_id)

    if user_id in getattr(admins, "ADMIN_IDS", set()):
        _clear_previous_attempt(user_id, test_id)
        token, finished = None, False

    if token and finished and user_id not in getattr(admins, "ADMIN_IDS", set()):
        await bot.send_message(
            chat_id,
            f"❌ You already passed this test.\n\n🔑 Your token: <code>{token}</code>\n📊 Send /result to see your result.",
            parse_mode="HTML",
        )
        clear_user_mode(user_id)
        return

    token = token or _gen_token()
    start_ts = int(time.time())
    total_seconds = time_limit * 60 + EXTRA_GRACE_SECONDS

    questions = _load_questions(test_id)
    if not questions:
        await bot.send_message(chat_id, "❌ Test has no questions.")
        clear_user_mode(user_id)
        return

    await state.update_data(
        chat_id=chat_id,
        user_id=user_id,
        token=token,
        start_ts=start_ts,
        limit_min=time_limit,
        total_seconds=total_seconds,
        context_test_id=test_id,
        questions=questions,
        answers={},
        skipped=set(),
        index=0,
        finished=False,
        auto_finished=False,
        skip_warn_msg_id=None,
    )

    await bot.send_message(chat_id, f"🔑 <b>Your token:</b> <code>{token}</code>", parse_mode="HTML")

    timer_msg = await bot.send_message(chat_id, f"⏱ <b>Time left:</b> {_format_timer(_time_left(start_ts, time_limit))}", parse_mode="HTML")
    await state.update_data(timer_msg_id=timer_msg.message_id)

    asyncio.create_task(_timer_loop(state, bot))
    await _render_question(state, bot)


async def _timer_loop(state: FSMContext, bot):
    while True:
        data = await state.get_data()
        if not data or data.get("finished") or "start_ts" not in data:
            return
        left = _time_left(data["start_ts"], data["limit_min"])
        if left <= 0:
            await _auto_finish(state, bot)
            return

        try:
            await bot.edit_message_text(
                chat_id=data["chat_id"],
                message_id=data["timer_msg_id"],
                text=f"⏱ <b>Time left:</b> {_format_timer(left)}\n{_time_progress_bar(left, data['total_seconds'])}",
                parse_mode="HTML",
            )
        except Exception:
            pass

        await asyncio.sleep(15)


async def _render_question(state: FSMContext, bot):
    data = await state.get_data()
    idx = data["index"]

    _, q_text, a, b, c, d = data["questions"][idx]

    selected_text = ""
    if idx in data["answers"]:
        key = data["answers"][idx]
        selected_text = f"\n\n✅ <b>You selected:</b>\n{ {'a': a, 'b': b, 'c': c, 'd': d}[key] }"

    text = f"<b>Question {idx + 1}</b>\n\n{q_text}{selected_text}"

    buttons = []
    if idx not in data["answers"]:
        buttons.extend([
            [InlineKeyboardButton(text=a, callback_data=f"ans|{idx}|a")],
            [InlineKeyboardButton(text=b, callback_data=f"ans|{idx}|b")],
            [InlineKeyboardButton(text=c, callback_data=f"ans|{idx}|c")],
            [InlineKeyboardButton(text=d, callback_data=f"ans|{idx}|d")],
        ])

    buttons.append([
        InlineKeyboardButton(text="⬅️ Prev", callback_data=f"prev|{idx}"),
        InlineKeyboardButton(text=f"{idx + 1}/{len(data['questions'])}", callback_data="noop"),
        InlineKeyboardButton(text="Next ➡️", callback_data=f"next|{idx}"),
    ])
    buttons.append([InlineKeyboardButton(text="🏁 Finish", callback_data="finish")])

    if data.get("question_msg_id") is None:
        msg = await bot.send_message(data["chat_id"], text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
        await state.update_data(question_msg_id=msg.message_id)
    else:
        try:
            await bot.edit_message_text(
                chat_id=data["chat_id"],
                message_id=data["question_msg_id"],
                text=text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                parse_mode="HTML",
            )
        except Exception:
            msg = await bot.send_message(
                data["chat_id"],
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                parse_mode="HTML",
            )
            await state.update_data(question_msg_id=msg.message_id)

# ─────────────────────────────
# Callbacks
# ─────────────────────────────

@router.callback_query(F.data.startswith("ans|"))
async def answer_handler(query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if data.get("finished"):
        await query.answer("⏱ Test already finished")
        return

    await query.answer("Noted ✅")

    idx = (await state.get_data())["index"]
    _, _, choice = query.data.split("|")

    data["answers"][idx] = choice
    data["skipped"].discard(idx)
    await _update_skip_warning(state, query.bot, data)

    save_test_answer(data["token"], data["context_test_id"], idx + 1, choice)

    if idx < len(data["questions"]) - 1:
        data["index"] = idx + 1

    await state.update_data(**data)
    await _render_question(state, query.bot)

@router.callback_query(F.data.startswith("prev|"))
async def prev_handler(query: CallbackQuery, state: FSMContext):
    await query.answer()
    data = await state.get_data()
    if data.get("finished"):
        return

    if data["index"] > 0:
        if data["index"] not in data["answers"]:
            data["skipped"].add(data["index"])
        
        data["index"] -= 1
        await state.update_data(**data)
        await _update_skip_warning(state, query.bot, data)
        await _render_question(state, query.bot)


@router.callback_query(F.data.startswith("next|"))
async def next_handler(query: CallbackQuery, state: FSMContext):
    await query.answer()
    data = await state.get_data()
    if data.get("finished"):
        return

    if data["index"] < len(data["questions"]) - 1:
        if data["index"] not in data["answers"]:
            data["skipped"].add(data["index"])
        
        data["index"] += 1
        await state.update_data(**data)
        await _update_skip_warning(state, query.bot, data)
        await _render_question(state, query.bot)


@router.callback_query(F.data == "noop")
async def noop_handler(query: CallbackQuery):
    await query.answer()


@router.callback_query(F.data == "finish")
async def finish_handler(query: CallbackQuery, state: FSMContext):
    await query.answer()
    data = await state.get_data()

    total = len(data["questions"])
    answered = len(data["answers"])
    if answered < total:
        skipped = _get_skipped_questions(data)
        numbers = ", ".join(str(i + 1) for i in skipped)
        await query.message.edit_text(
            f"⚠️ You have unanswered questions.\n\nSkipped: {numbers}\n\nDo you really want to finish?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚠️ Finish anyway", callback_data="finish_anyway")],
                [InlineKeyboardButton(text="❌ Continue", callback_data="continue_test")],
            ]),
        )
        return

    await _finish(state, manual=True, bot=query.bot)


@router.callback_query(F.data == "finish_anyway")
async def finish_anyway_handler(query: CallbackQuery, state: FSMContext):
    await query.answer()
    await _finish(state, manual=True, bot=query.bot)


@router.callback_query(F.data == "continue_test")
async def continue_test_handler(query: CallbackQuery, state: FSMContext):
    await query.answer("Continue ✍️")
    await _render_question(state, query.bot)


# ─────────────────────────────
# Finish
# ─────────────────────────────

async def _auto_finish(state: FSMContext, bot):
    await _finish(state, manual=False, bot=bot)

async def _finish(state: FSMContext, manual: bool, bot):
    data = await state.get_data()
    if not data or data.get("finished"):
        return

    data["finished"] = True

    if manual:
        data["time_left"] = _time_left(data["start_ts"], data["limit_min"])
        data["auto_finished"] = False
    else:
        data["time_left"] = 0
        data["auto_finished"] = True

    total = len(data["questions"])
    correct_map = _load_correct_answers(data["context_test_id"])

    correct = sum(1 for idx, selected in data["answers"].items() if correct_map.get(idx) == selected)
    score = round((correct / total) * 100, 2)

    save_test_score(
        token=data["token"],
        test_id=data["context_test_id"],
        user_id=data["user_id"],
        total_questions=total,
        correct_answers=correct,
        score=score,
        max_score=100,
        time_left=data["time_left"],
        auto_finished=data["auto_finished"],
    )

    
    for key in ("timer_msg_id", "question_msg_id"):
        try:
            await bot.delete_message(data["chat_id"], data[key])
        except Exception:
            pass

    await bot.send_message(
        data["chat_id"],
        "✅ Your answers were submitted!\n\n"
        f"🔑 Your token: {data['token']}\n"
        f"To see your result, send:\n/result {data['token']}",
    )

    clear_user_mode(data["user_id"])
    await state.clear()
