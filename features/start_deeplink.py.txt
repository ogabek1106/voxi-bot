# features/start_deeplink.py
"""
Start deeplink handler.

Behavior:
 - plain /start -> do nothing (core handler handles it)
 - /start start  -> send the friendly casual start reply (so deep link ?start=start looks like plain /start)
 - /start <other> -> try to find book by code in books.py and send it; otherwise reply "Bu kod bo‘yicha kitob topilmadi."
"""

import logging
import time
from typing import Optional

from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

logger = logging.getLogger(__name__)


def _read_payload(update: Update, context: CallbackContext) -> Optional[str]:
    # Try context.args first (PTB v13 pass_args=True)
    try:
        args = getattr(context, "args", None)
        if args:
            payload = " ".join(args).strip()
            if payload:
                return payload
    except Exception:
        logger.debug("start_deeplink: context.args read failed", exc_info=True)

    # Fallback to parsing raw text "/start payload"
    try:
        text = (update.message.text or "").strip()
        if text:
            parts = text.split(maxsplit=1)
            if len(parts) > 1:
                payload = parts[1].strip()
                if payload:
                    return payload
    except Exception:
        logger.debug("start_deeplink: fallback parse failed", exc_info=True)

    return None


def _send_book_to_user(payload: str, update: Update, context: CallbackContext) -> bool:
    """
    Try to locate BOOKS[payload] in books.py and send/forward the book.
    Return True if we handled (sent something), otherwise False.
    """
    try:
        import books  # your repo's books.py
    except Exception:
        logger.debug("books.py not available", exc_info=True)
        return False

    BOOKS = getattr(books, "BOOKS", None)
    if not isinstance(BOOKS, dict):
        logger.debug("BOOKS not found or not dict in books.py")
        return False

    code = payload.strip()
    book = BOOKS.get(code)
    if book is None:
        # try case-insensitive fallback
        lower_map = {k.lower(): v for k, v in BOOKS.items()}
        book = lower_map.get(code.lower())
        if book is None:
            return False

    chat_id = update.effective_chat.id
    bot = context.bot

    # If book is a simple string, just reply with it
    if isinstance(book, str):
        try:
            bot.send_message(chat_id=chat_id, text=book)
            return True
        except Exception:
            logger.exception("Failed to send simple string book reply")
            return False

    # If dict, prefer forwarding from storage channel (if provided)
    if isinstance(book, dict):
        storage_chat = book.get("storage_chat_id") or book.get("storage_chat") or book.get("storage_channel")
        storage_mid = book.get("storage_message_id") or book.get("storage_mid") or book.get("message_id")
        if storage_chat and storage_mid:
            try:
                bot.forward_message(chat_id=chat_id, from_chat_id=int(storage_chat), message_id=int(storage_mid))
                logger.info("Forwarded book %s to user %s from storage %s/%s", code, chat_id, storage_chat, storage_mid)
                return True
            except Exception:
                logger.exception("Failed to forward stored message for code %s", code)

        # try file_id
        file_id = book.get("file_id") or book.get("fileid") or book.get("file")
        if file_id:
            try:
                bot.send_document(chat_id=chat_id, document=file_id)
                logger.info("Sent file_id for book %s to user %s", code, chat_id)
                return True
            except Exception:
                logger.exception("Failed to send file_id for code %s", code)

        # fallback: send title/info if present
        title = book.get("title") or book.get("name")
        if title:
            try:
                bot.send_message(chat_id=chat_id, text=f"Kitob topildi: {title}")
                return True
            except Exception:
                logger.exception("Failed to send title for code %s", code)

    return False


def _send_casual_start(update: Update, context: CallbackContext):
    """Send the casual /start reply so ?start=start looks identical to plain /start."""
    user = update.effective_user
    name = (getattr(user, "first_name", None) or "").strip()
    if name:
        greeting = f"Assalomu alaykum, {name}!"
    else:
        greeting = "Assalomu alaykum!"

    # This is the friendly prompt you displayed in screenshots:
    text = (
        f"{greeting}\n"
        "Menga faqat kitob kodini yuboring (masalan: 3)"
    )
    try:
        update.message.reply_text(text)
    except Exception:
        logger.exception("Failed to send casual start reply")


def start_handler(update: Update, context: CallbackContext):
    payload = _read_payload(update, context)
    logger.info("start_deeplink invoked by user=%s payload=%r", getattr(update.effective_user, "id", None), payload)

    # No payload -> let core start handler handle it
    if not payload:
        logger.debug("no payload, skipping (letting core /start run)")
        return

    # If payload is the literal "start", treat it as casual /start
    if payload.strip().lower() == "start":
        _send_casual_start(update, context)
        return

    # Try to handle as book code
    try:
        handled = _send_book_to_user(payload, update, context)
    except Exception:
        logger.exception("Error in _send_book_to_user")
        handled = False

    if handled:
        return

    # fallback not found message
    try:
        update.message.reply_text("Bu kod bo‘yicha kitob topilmadi.")
    except Exception:
        logger.exception("Failed to send fallback not-found reply")


def setup(dispatcher):
    # register so context.args works (PTB v13 style)
    dispatcher.add_handler(CommandHandler("start", start_handler, pass_args=True))
    logger.info("start_deeplink feature loaded")
