# features/tests_list.py
"""
Admin-only command: /tests_list

Shows all created tests in a readable list.
Read-only. No FSM. No mode locking.
Safe in Aiogram 3.
"""

import time
import logging
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

import admins
from database import get_all_test_definitions

logger = logging.getLogger(__name__)
router = Router()


def is_admin(user_id: int) -> bool:
    return user_id in {int(x) for x in getattr(admins, "ADMIN_IDS", [])}


def fmt_ts(ts: int) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ts)))
    except Exception:
        return "—"


@router.message(Command("tests_list"))
async def tests_list(message: Message):
    uid = message.from_user.id

    if not is_admin(uid):
        await message.answer("⛔ Admins only.")
        return

    tests = get_all_test_definitions()
    if not tests:
        await message.answer("🧪 No tests created yet.")
        return

    lines = ["🧪 **Tests list:**\n"]

    for idx, t in enumerate(tests, start=1):
        test_id, name, level, q_count, time_limit, created_at = t

        lines.append(
            f"{idx}. `{test_id}`\n"
            f"• Name: {name or '—'}\n"
            f"• Level: {level or '—'}\n"
            f"• Questions: {q_count or '—'}\n"
            f"• Time: {time_limit or '—'} min\n"
            f"• Created: {fmt_ts(created_at)}\n"
        )

    await message.answer(
        "\n".join(lines),
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )
