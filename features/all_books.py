# features/all_books.py
"""
Feature: /all_books

Shows all available books to any user.
Read-only, safe, paginated by message length.
"""

import logging
from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

from books import BOOKS

logger = logging.getLogger(__name__)

TG_MESSAGE_LIMIT = 3900  # safe margin under 4096


def _chunk_text(text: str, limit: int = TG_MESSAGE_LIMIT):
    """Split long text into Telegram-safe chunks."""
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


def cmd_all_books(update: Update, context: CallbackContext):
    if not BOOKS:
        update.message.reply_text("📚 No books are available yet.")
        return

    lines = []
    lines.append("📚 *Available Books*\n")

    # sort by numeric code if possible
    def _sort_key(item):
        code = item[0]
        try:
            return int(code)
        except Exception:
            return code

    for code, data in sorted(BOOKS.items(), key=_sort_key):
        title = data.get("filename") or data.get("title") or "Untitled"
        lines.append(f"{code} — {title}")

    text = "\n".join(lines)

    chunks = _chunk_text(text)
    for part in chunks:
        update.message.reply_text(
            part,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )

    logger.info(
        "/all_books shown to user %s (%d books)",
        update.effective_user.id if update.effective_user else None,
        len(BOOKS),
    )


def setup(dispatcher):
    dispatcher.add_handler(CommandHandler("all_books", cmd_all_books))
    logger.info("all_books feature loaded")
