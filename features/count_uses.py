# features/count_uses.py
"""
/count_uses

Admin-only command.

Shows:
- command usage (last 24h / lifetime)
- book requests (last 24h / lifetime)
- TOTAL usage (today / lifetime)

Counts ONLY non-admin users.
"""

import logging
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

from admins import ADMIN_IDS
from database import (
    get_command_usage_stats,
    get_total_book_request_stats,
)

logger = logging.getLogger(__name__)
router = Router()

# ─────────────────────────────
# CONFIG
# ─────────────────────────────

COUNTED_COMMANDS = {
    "start",
    "all_books",
    # add more commands explicitly if needed
}


# ─────────────────────────────
# Utils
# ─────────────────────────────

def is_admin(user_id: int | None) -> bool:
    return user_id is not None and int(user_id) in set(map(int, ADMIN_IDS))


# ─────────────────────────────
# /count_uses
# ─────────────────────────────

@router.message(Command("count_uses"))
async def count_uses_handler(message: Message):
    user_id = message.from_user.id if message.from_user else None

    # admin only
    if not is_admin(user_id):
        await message.answer("⛔ Bu buyruq faqat adminlar uchun.")
        return

    lines: list[str] = []
    lines.append("📊 *Usage statistics*\n")

    # ───────── Commands ─────────
    stats = get_command_usage_stats()

    today_commands_total = 0
    lifetime_commands_total = 0

    lines.append("🔹 *Commands:*")

    if stats:
        for command, last_24h, total in stats:
            if command not in COUNTED_COMMANDS:
                continue

            lines.append(f"/{command} — {last_24h} / {total}")
            today_commands_total += int(last_24h or 0)
            lifetime_commands_total += int(total or 0)
    else:
        lines.append("yo‘q")

    # ───────── Books ─────────
    book_24h, book_total = get_total_book_request_stats()

    lines.append("\n📚 *Book requests:*")
    lines.append(f"{book_24h} / {book_total}")

    # ───────── TOTAL ─────────
    today_total = today_commands_total + book_24h
    lifetime_total = lifetime_commands_total + book_total

    lines.append("\n📈 *TOTAL:*")
    lines.append(f"{today_total} / {lifetime_total}")

    await message.answer(
        "\n".join(lines),
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )
