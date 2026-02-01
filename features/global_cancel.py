# global_cancel.py
import logging
from typing import Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from database import clear_all_user_modes
from global_cleaner import clean_user
import admins

logger = logging.getLogger(__name__)

router = Router()


# ─────────────────────────────
# Helpers
# ─────────────────────────────

def _is_admin(user_id: Optional[int]) -> bool:
    raw = getattr(admins, "ADMIN_IDS", []) or []
    return user_id is not None and int(user_id) in {int(x) for x in raw}


# ─────────────────────────────
# /cancel — ANY USER, HARD RESET
# ─────────────────────────────

@router.message(Command("cancel"))
async def global_cancel(message: Message, state: FSMContext):
    user = message.from_user
    if not user:
        return

    # 🔥 HARD RESET USER (DB + runtime)
    clean_user(user.id, reason="global_cancel")

    # Clear FSM state completely
    await state.clear()

    await message.answer(
        "❌ Cancelled.\n"
        "Your current action was stopped and state reset."
    )

    logger.info("GLOBAL CANCEL | user_id=%s", user.id)


# ─────────────────────────────
# /cancel_all — ADMIN ONLY
# ─────────────────────────────

@router.message(Command("cancel_all"))
async def global_cancel_all(message: Message, state: FSMContext):
    user = message.from_user
    if not user:
        return

    if not _is_admin(user.id):
        await message.answer("⛔ Admins only.")
        return

    removed = clear_all_user_modes()

    # Clear admin FSM state as well
    await state.clear()

    await message.answer(
        "🚨 GLOBAL RESET\n\n"
        "All user states were cleared.\n"
        f"Rows removed: {removed}"
    )

    logger.critical(
        "GLOBAL CANCEL ALL | admin_id=%s | rows_removed=%s",
        user.id,
        removed,
    )
