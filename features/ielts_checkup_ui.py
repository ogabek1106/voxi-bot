# features/ielts_checkup_ui.py
"""
IELTS Check Up UI (Aiogram 3, UI ONLY)

Rules:
- UI has NO business logic
- UI does NOT start checkers
- UI only routes to real command handlers (/ielts_writing, /ielts_listening, etc.)
- FSM is used only for access control (mode locking)
"""

import logging
from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from features.sub_check import require_subscription

from database import get_user_mode, set_user_mode, clear_user_mode

logger = logging.getLogger(__name__)
router = Router()

IELTS_MODE = "ielts_check_up"

# ─────────────────────────────
# UI Keyboards
# ─────────────────────────────

def main_user_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🧠 IELTS Check Up")]],
        resize_keyboard=True
    )

def ielts_skills_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✍️ Writing"), KeyboardButton(text="🗣️ Speaking")],
            [KeyboardButton(text="🎧 Listening"), KeyboardButton(text="📖 Reading")],
            [KeyboardButton(text="⬅️ Back to main menu")],
        ],
        resize_keyboard=True
    )

def writing_submenu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Writing Task 1")],
            [KeyboardButton(text="🧠 Writing Task 2")],
            [KeyboardButton(text="⬅️ Back")],
        ],
        resize_keyboard=True
    )

def speaking_submenu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🗣️ Part 1 – Introduction")],
            [KeyboardButton(text="🗣️ Part 2 – Cue Card")],
            [KeyboardButton(text="🗣️ Part 3 – Discussion")],
            [KeyboardButton(text="⬅️ Back")],
        ],
        resize_keyboard=True
    )

# ─────────────────────────────
# Guards
# ─────────────────────────────

def ui_allowed(user_id: int) -> bool:
    mode = get_user_mode(user_id)
    logger.warning("IELTS UI blocked, user %s mode=%s", user_id, mode)
    return mode in (None, IELTS_MODE)
def ui_owner(user_id: int) -> bool:
    return get_user_mode(user_id) == IELTS_MODE

# ─────────────────────────────
# Entry
# ─────────────────────────────

@router.message(F.text == "🧠 IELTS Check Up")
async def open_ielts_checkup(message: Message, state: FSMContext):
    logger.critical("🔥 IELTS UI DEBUG BUTTON FIRED 🔥")
    uid = message.from_user.id

    #if not ui_allowed(uid):
    #    return

    set_user_mode(uid, IELTS_MODE)

    await message.answer(
        "🎓 IELTS Check Up\nChoose the skill you want to check:",
        reply_markup=ielts_skills_reply_keyboard()
    )

# ─────────────────────────────
# Navigation
# ─────────────────────────────

@router.message(F.text == "⬅️ Back to main menu")
async def back_to_main_menu(message: Message, state: FSMContext):
    uid = message.from_user.id

    if not ui_owner(uid):
        return

    clear_user_mode(uid)

    await message.answer(
        "⬅️ Back to main menu.",
        reply_markup=main_user_keyboard()
    )

@router.message(F.text == "⬅️ Back")
async def back_to_skills(message: Message, state: FSMContext):
    uid = message.from_user.id

    if not ui_owner(uid):
        return

    await message.answer(
        "🎓 IELTS Check Up\nChoose the skill you want to check:",
        reply_markup=ielts_skills_reply_keyboard()
    )

# ─────────────────────────────
# Skill Menus (UI only)
# ─────────────────────────────

@router.message(F.text == "✍️ Writing")
async def writing_menu(message: Message, state: FSMContext):
    uid = message.from_user.id
    if not ui_owner(uid):
        return

    # 🔒 SUB CHECK — ONLY HERE
    if not await require_subscription(message, state):
        return

    await message.answer(
        "✍️ Writing section:",
        reply_markup=writing_submenu_keyboard()
    )

@router.message(F.text == "🗣️ Speaking")
async def speaking_menu(message: Message):
    uid = message.from_user.id
    if not ui_owner(uid):
        return

    await message.answer(
        "🗣️ Speaking section:",
        reply_markup=speaking_submenu_keyboard()
    )

@router.message(F.text.in_({"🎧 Listening", "📖 Reading"}))
async def coming_soon(message: Message):
    uid = message.from_user.id
    if not ui_owner(uid):
        return

    await message.answer("🚧 Coming soon!")

# ─────────────────────────────
# Task Routing (UI → REAL COMMANDS)
# ─────────────────────────────

@router.message(F.text == "📝 Writing Task 1")
async def route_writing_task1(message: Message, state: FSMContext):
    uid = message.from_user.id
    if not ui_owner(uid):
        return

    from features.ai.writing_task1 import start_check
    await start_check(message, state)
    
@router.message(F.text == "🧠 Writing Task 2")
async def route_writing_task2(message: Message, state: FSMContext):
    uid = message.from_user.id
    if not ui_owner(uid):
        return

    from features.ai.writing_task2 import start_check
    await start_check(message, state)

@router.message(F.text.in_({
    "🗣️ Part 1 – Introduction",
    "🗣️ Part 2 – Cue Card",
    "🗣️ Part 3 – Discussion"
}))
async def route_speaking_parts(message: Message):
    uid = message.from_user.id
    if not ui_owner(uid):
        return

    await message.answer("/ielts_speaking")









