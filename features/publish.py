# features/publish.py
"""
Admin command to publish ONE test.

Usage:
  /publish test_<id>
  /unpublish test_<id>
"""

import logging
from typing import Optional

from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

import admins
from database import (
    get_test_definition,
    has_active_test,
    set_active_test,
    clear_active_test,
    get_active_test,
    clear_test_program_state,
)

logger = logging.getLogger(__name__)
router = Router()


# ─────────────────────────────
# Helpers
# ─────────────────────────────

def _is_admin(user_id: Optional[int]) -> bool:
    raw = getattr(admins, "ADMIN_IDS", []) or []
    return user_id is not None and int(user_id) in {int(x) for x in raw}


def _parse_test_id(text: str) -> Optional[str]:
    parts = text.split(maxsplit=1)
    if len(parts) != 2:
        return None
    tid = parts[1].strip()
    if not tid.startswith("test_"):
        return None
    return tid


# ─────────────────────────────
# /publish test_<id>
# ─────────────────────────────

@router.message(Command("publish"))
async def publish(message: Message):
    user = message.from_user
    if not user or not _is_admin(user.id):
        await message.answer("⛔ Admins only.")
        return

    test_id = _parse_test_id(message.text)
    if not test_id:
        await message.answer("❗ Usage: /publish test_<id>")
        return

    if has_active_test():
        await message.answer("⚠️ There is already an active test.\nUse /unpublish <test_id> first.")
        return

    meta = get_test_definition(test_id)
    if not meta:
        await message.answer("❌ Test ID not found in drafts.")
        return

    test_id, name, level, question_count, time_limit, _ = meta

    ok = set_active_test(
        test_id=test_id,
        name=name,
        level=level,
        question_count=question_count,
        time_limit=time_limit,
    )

    if not ok:
        await message.answer("❌ Failed to publish test. See logs.")
        return

    clear_test_program_state()

    await message.answer(
        "✅ Test published successfully!\n\n"
        f"ID: {test_id}\n"
        f"Name: {name}\n"
        f"Level: {level}\n"
        f"Questions: {question_count}\n"
        f"Time limit: {time_limit} min"
    )

    logger.info("TEST PUBLISHED | admin_id=%s | test_id=%s", user.id, test_id)


# ─────────────────────────────
# /unpublish test_<id>
# ─────────────────────────────

@router.message(Command("unpublish"))
async def unpublish(message: Message):
    user = message.from_user
    if not user or not _is_admin(user.id):
        await message.answer("⛔ Admins only.")
        return

    test_id = _parse_test_id(message.text)
    if not test_id:
        await message.answer("❗ Usage: /unpublish test_<id>")
        return

    active = get_active_test()
    if not active:
        await message.answer("ℹ️ No active test to unpublish.")
        return

    active_test_id = active[0]
    if test_id != active_test_id:
        await message.answer(
            f"❌ This test is not active.\n"
            f"Active test: {active_test_id}"
        )
        return

    clear_active_test()
    clear_test_program_state()

    await message.answer(f"🛑 Test {test_id} unpublished. No test is active now.")

    logger.warning("TEST UNPUBLISHED | admin_id=%s | test_id=%s", user.id, test_id)
