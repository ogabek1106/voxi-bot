# features/start_deeplink.py
"""
Feature: Lightweight deep-link (/start <payload>) handler.

Behavior:
 - If /start is called WITHOUT a payload, this handler does NOTHING
   (so your core start handler continues to handle plain /start).
 - If /start <payload> is called, this handler will try to handle it:
    * If a books.py with BOOKS mapping exists and payload matches a key,
      it will send a short message about the book (customize as needed).
    * Otherwise it replies: "Bu kod bo‘yicha kitob topilmadi."
 - Register using CommandHandler("start", start_handler, pass_args=True)
   to ensure context.args is available (python-telegram-bot v13).
"""

import logging
from typing import Optional

from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

logger = logging.getLogger(__name__)


def _read_payload(update: Update, context: CallbackContext) -> Optional[str]:
    """
    Robustly obtain the /start payload.
    Returns None if no payload present.
    """
    # 1) try context.args (works with CommandHandler(..., pass_args=True) on PTB v13)
    try:
        args = getattr(context, "args", None)
        if args:
            payload = " ".join(args).strip()
            if payload:
                return payload
    except Exception:
        logger.debug("start_deeplink: context.args read failed", exc_info=True)

    # 2) fallback: parse raw text "/start payload"
    try:
        text = update.message.text or ""
        parts = text.split(maxsplit=1)
        if len(parts) > 1:
            payload = parts[1].strip()
            if payload:
                return payload
    except Exception:
        logger.debug("start_deeplink: fallback raw text parse failed", exc_info=True)

    return None


def _handle_book_code(payload: str, update: Update, context: CallbackContext) -> bool:
    """
    Try to handle payload as a book code using books.py -> BOOKS mapping.
    Returns True if handled (reply was sent), False otherwise.
    """
    try:
        # attempt to import BOOKS if present in repo
        import books  # type: ignore
    except Exception:
        # books.py not available — nothing to do here
        return False

    BOOKS = getattr(books, "BOOKS", None)
    if not isinstance(BOOKS, dict):
        return False

    # payload could be provided with extra slashes or params, normalize
    code = payload.strip()

    book = BOOKS.get(code)
    if not book:
        # try case-insensitive keys if you want
        lower_map = {k.lower(): v for k, v in BOOKS.items()}
        book = lower_map.get(code.lower())

    if not book:
        return False

    # Customize this reply to match your BOOKS structure.
    # Here we send a short confirmation that the code was found and show title / brief info.
    title = book.get("title") if isinstance(book, dict) else None
    caption = f"Kitob topildi: `{code}`"
    if title:
        caption += f"\nTitle: {title}"
    try:
        update.message.reply_text(caption, parse_mode="Markdown")
    except Exception:
        try:
            update.message.reply_text(caption)
        except Exception:
            logger.exception("start_deeplink: failed to notify admin about found book")
    return True


def start_handler(update: Update, context: CallbackContext):
    """
    Intercept /start <payload>. If payload absent -> return (do nothing),
    if payload present -> try to handle (book lookup), else reply 'not found'.
    """
    payload = _read_payload(update, context)
    logger.info("start_deeplink: invoked by user=%s payload=%r", getattr(update.effective_user, "id", None), payload)

    # if no payload - we don't touch plain /start (let core handle it)
    if not payload:
        logger.debug("start_deeplink: no payload, skipping to core start handler")
        return

    # try to handle as book code
    try:
        handled = _handle_book_code(payload, update, context)
    except Exception:
        logger.exception("start_deeplink: error while handling book code")
        handled = False

    if handled:
        return

    # fallback: unknown payload -> user message (same text you reported)
    try:
        update.message.reply_text("Bu kod bo‘yicha kitob topilmadi.")
    except Exception:
        try:
            update.message.reply_text("Bu kod bo‘yicha kitob topilmadi.")
        except Exception:
            logger.exception("start_deeplink: failed to send fallback 'not found' reply")


def setup(dispatcher):
    # Register handler for /start. We only respond when payload exists.
    # Use pass_args=True (v13) so context.args is populated.
    dispatcher.add_handler(CommandHandler("start", start_handler, pass_args=True))
    logger.info("start_deeplink feature loaded")
