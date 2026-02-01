# features/rem_fr_db.py
"""
Feature: /rem_fr_db <user_id>

Admin-only command.
Removes a user from the database so they can be re-recorded
by user_tracker middleware on next interaction.
"""

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

import admins
from database import remove_user_by_id  # you must already have or add this

logger = logging.getLogger(__name__)

router = Router()


# ─────────────────────────────
# Helpers
# ─────────────────────────────

def _is_admin(user_id: int | None) -> bool:
    if user_id is None:
        return False
    raw = getattr(admins, "ADMIN_IDS", []) or []
    return int(user_id) in {int(x) for x in raw}


# ─────────────────────────────
# /rem_fr_db <user_id>
# ─────────────────────────────

@router.message(Command("rem_fr_db"))
async def remove_from_db(message: Message, state: FSMContext):
    user = message.from_user
    if not user:
        return

    if not _is_admin(user.id):
        await message.answer("⛔ Admins only.")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer(
            "❗ Usage:\n"
            "/rem_fr_db <user_id>"
        )
        return

    target_id = int(parts[1])

    try:
        removed = remove_user_by_id(target_id)
    except Exception as e:
        logger.exception("Failed to remove user %s: %s", target_id, e)
        await message.answer("❌ Database error.")
        return

    if removed:
        await message.answer(
            f"✅ User `{target_id}` removed from database.\n"
            "They will be recorded again on next interaction.",
            parse_mode="Markdown",
        )
        logger.info("Admin %s removed user %s from DB", user.id, target_id)
    else:
        await message.answer(
            f"ℹ️ User `{target_id}` was not found in database.",
            parse_mode="Markdown",
        )
