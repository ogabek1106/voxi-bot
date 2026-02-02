# features/all_books.py
"""
Feature: /all_books

Shows all available books to any user.
Read-only, safe, paginated by message length.
"""

import logging

from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from database import log_command_use
from admins import ADMIN_IDS

from books import BOOKS
from features.sub_check import require_subscription

logger = logging.getLogger(__name__)

router = Router()

TG_MESSAGE_LIMIT = 3900  # safe margin under 4096


# ─────────────────────────────
# Utils
# ─────────────────────────────

def _chunk_text(text: str, limit: int = TG_MESSAGE_LIMIT):
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut == -1:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip()
    if text:
        chunks.append(text)
    return chunks


def _sort_key(item):
    code = item[0]
    try:
        return int(code)
    except Exception:
        return code


# ─────────────────────────────
# /all_books
# ─────────────────────────────

@router.message(Command("all_books"))
async def all_books_handler(message: Message, state: FSMContext):
    # 🔐 FREE-STATE gate (FSM-safe)
    if not await require_subscription(message, state):
        return

    # ✅ COUNT /all_books (NON-ADMIN ONLY)
    if message.from_user.id not in ADMIN_IDS:
        log_command_use("all_books")

    if not BOOKS:
        await message.answer("📚 No books are available yet.")
        return

    lines = ["📚 *Available Books*\n"]

    for code, data in sorted(BOOKS.items(), key=_sort_key):
        title = data.get("filename") or data.get("title") or "Untitled"
        lines.append(f"{code} — {title}")

    text = "\n".join(lines)

    for part in _chunk_text(text):
        await message.answer(
            part,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )

    logger.info(
        "/all_books shown to user %s (%d books)",
        message.from_user.id if message.from_user else None,
        len(BOOKS),
    )
