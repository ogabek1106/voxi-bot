# features/create_test.py
"""
Unified TEST CREATION & EDITING feature (Aiogram 3)

Flow:
 /create_test
   → ask meta (name, level, time, question_count)
   → create test definition
   → immediately start questions
   → finish after N questions

 Commands available ANY TIME inside FSM:
   /edit_q <n>  – edit specific question
   /edit_t <id> – load existing test (finished or unfinished)
   /cancel      – exit safely

DB is the single source of truth.
FSM = control, not storage.
"""

import time
import logging
from typing import Optional

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import admins
from database import (
    save_test_definition,
    get_test_definition,
    get_all_test_definitions,
    save_test_question,
    ensure_test_questions_table,
)

logger = logging.getLogger(__name__)
router = Router()

MODE = "create_test"


# ─────────────────────────────
# FSM STATES
# ─────────────────────────────

class CreateTest(StatesGroup):
    name = State()
    level = State()
    time = State()
    count = State()
    question = State()
    answers = State()
    correct = State()


# ─────────────────────────────
# HELPERS
# ─────────────────────────────

def is_admin(uid: int) -> bool:
    return uid in {int(x) for x in getattr(admins, "ADMIN_IDS", [])}


def gen_test_id() -> str:
    return f"test_{int(time.time())}"


def parse_answers(text: str) -> Optional[dict]:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) != 4:
        return None

    out = {}
    for l in lines:
        if "-" not in l:
            return None
        k, v = l.split("-", 1)
        k = k.strip().lower()
        if k not in ("a", "b", "c", "d"):
            return None
        out[k] = v.strip()

    return out if len(out) == 4 else None


async def abort(uid: int, state: FSMContext, reason: str):
    logger.info("Create test aborted: %s (uid=%s)", reason, uid)
    await state.clear()


async def ensure_free_or_same(state: FSMContext) -> bool:
    current = await state.get_state()
    return current is None


# ─────────────────────────────
# ENTRY
# ─────────────────────────────

@router.message(Command("create_test"))
async def start(message: Message, state: FSMContext):
    uid = message.from_user.id

    if not is_admin(uid):
        await message.answer("⛔ Admins only.")
        return

    if not await ensure_free_or_same(state):
        await message.answer("⏳ Finish current process first.")
        return

    await state.clear()

    await state.update_data(
        test_id=gen_test_id(),
        q_current=1,
        edit_return=None,
    )

    await state.set_state(CreateTest.name)
    await message.answer(
        "🧪 Creating new test\n\n"
        "Send test NAME\n"
        "/cancel — exit"
    )


# ─────────────────────────────
# META
# ─────────────────────────────

@router.message(CreateTest.name, ~F.text.startswith("/"))
async def name_step(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(CreateTest.level)
    await message.answer("Send LEVEL (A2 / B1 / B2 / C1)")


@router.message(CreateTest.level, ~F.text.startswith("/"))
async def level_step(message: Message, state: FSMContext):
    await state.update_data(level=message.text.strip())
    await state.set_state(CreateTest.time)
    await message.answer("Send TIME LIMIT (minutes)")


@router.message(CreateTest.time, ~F.text.startswith("/"))
async def time_step(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❗ Send a number.")
        return

    await state.update_data(time_limit=int(message.text))
    await state.set_state(CreateTest.count)
    await message.answer("Send NUMBER OF QUESTIONS")


@router.message(CreateTest.count, ~F.text.startswith("/"))
async def count_step(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❗ Send a number.")
        return

    data = await state.get_data()
    q_count = int(message.text)

    save_test_definition(
        test_id=data["test_id"],
        name=data["name"],
        level=data["level"],
        question_count=q_count,
        time_limit=data["time_limit"],
    )

    await state.update_data(question_count=q_count)
    await state.set_state(CreateTest.question)

    await message.answer(
        f"✅ Test created.\n\n"
        f"🆔 {data['test_id']}\n"
        f"✍️ Question 1 / {q_count}"
    )


# ─────────────────────────────
# QUESTIONS
# ─────────────────────────────

@router.message(CreateTest.question, ~F.text.startswith("/"))
async def question_step(message: Message, state: FSMContext):
    await state.update_data(question_text=message.text.strip())
    await state.set_state(CreateTest.answers)

    await message.answer(
        "Send answers:\n"
        "a - ...\n"
        "b - ...\n"
        "c - ...\n"
        "d - ..."
    )


@router.message(CreateTest.answers, ~F.text.startswith("/"))
async def answers_step(message: Message, state: FSMContext):
    parsed = parse_answers(message.text)
    if not parsed:
        await message.answer("❗ Invalid format.")
        return

    await state.update_data(answers=parsed)
    await state.set_state(CreateTest.correct)
    await message.answer("Send CORRECT answer (a/b/c/d)")


@router.message(CreateTest.correct, ~F.text.startswith("/"))
async def correct_step(message: Message, state: FSMContext):
    correct = message.text.lower().strip()
    if correct not in ("a", "b", "c", "d"):
        await message.answer("❗ Must be a/b/c/d.")
        return

    data = await state.get_data()
    qn = data["q_current"]

    save_test_question(
        test_id=data["test_id"],
        question_number=qn,
        question_text=data["question_text"],
        answers=data["answers"],
        correct_answer=correct,
    )

    total = data["question_count"]
    next_q = qn + 1

    if next_q > total:
        await abort(message.from_user.id, state, "test finished")
        await message.answer("🎉 All questions created. Test is READY.")
        return

    await state.update_data(q_current=next_q)
    await state.set_state(CreateTest.question)
    await message.answer(f"✍️ Question {next_q} / {total}")


# ─────────────────────────────
# EDIT QUESTION
# ─────────────────────────────

@router.message(Command("edit_q"))
async def edit_question(message: Message, state: FSMContext):
    data = await state.get_data()

    if await state.get_state() is None:
        await message.answer("❗ You are not editing a test.")
        return

    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /edit_q <number>")
        return

    qn = int(parts[1])
    total = data.get("question_count")

    if not total or not (1 <= qn <= total):
        await message.answer("❌ Invalid question number.")
        return

    await state.update_data(
        edit_return=data["q_current"],
        q_current=qn,
    )
    await state.set_state(CreateTest.question)
    await message.answer(f"✍️ Editing question {qn} / {total}")


# ─────────────────────────────
# EDIT TEST (LOAD)
# ─────────────────────────────

@router.message(Command("edit_t"))
async def edit_test(message: Message, state: FSMContext):
    uid = message.from_user.id
    if not is_admin(uid):
        await message.answer("⛔ Admins only.")
        return

    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Usage: /edit_t <test_id>")
        return

    test = get_test_definition(parts[1])
    if not test:
        await message.answer("❌ Test not found.")
        return

    test_id, name, level, q_count, time_limit, _ = test

    await state.clear()
    await state.update_data(
        test_id=test_id,
        name=name,
        level=level,
        question_count=q_count,
        time_limit=time_limit,
        q_current=1,
        edit_return=None,
    )
    await state.set_state(CreateTest.question)
    await message.answer(f"✍️ Editing test {test_id}\nQuestion 1 / {q_count}")


# ─────────────────────────────
# CANCEL
# ─────────────────────────────

@router.message(Command("cancel"))
@router.message(Command("cancel_all"))
async def cancel(message: Message, state: FSMContext):
    if await state.get_state() is None:
        await message.answer("ℹ️ No active process to cancel.")
        return

    await abort(message.from_user.id, state, "create_test cancelled")
    await message.answer("🛑 Test creation cancelled.")

