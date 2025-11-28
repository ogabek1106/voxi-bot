# handlers.py
import logging
import threading
import time
from telegram import Update
from telegram.ext import CallbackContext
from books import BOOKS

logger = logging.getLogger(__name__)

DELETE_SECONDS = 15 * 60  # ⬅️ 15 mins


def _format_mmss(seconds: int) -> str:
    """Return MM:SS formatted string for given seconds (non-negative)."""
    if seconds < 0:
        seconds = 0
    m = seconds // 60
    s = seconds % 60
    return f"{m:02d}:{s:02d}"


def _wallclock_end_time_str(total_seconds: int) -> str:
    """Return wall-clock end time as HH:MM (localtime) for total_seconds from now."""
    end_ts = time.time() + total_seconds
    t = time.localtime(end_ts)
    return f"{t.tm_hour:02d}:{t.tm_min:02d}"


def send_book_by_code(chat_id: int, code: str, context: CallbackContext):
    """
    Sends the book (document) and a live-updating countdown message in the format:
    ⏳ [ MM:SS ] HH:MM
    Returns tuple (document_message_id, countdown_message_id) if successful, else (None, None).
    """
    book = BOOKS.get(code)
    if not book:
        return None, None

    file_id = book.get("file_id")
    caption = book.get("caption", "")

    try:
        sent = context.bot.send_document(
            chat_id=chat_id,
            document=file_id,
            caption=caption,
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.exception("Failed to send book: %s", e)
        return None, None

    # Prepare initial countdown text
    mmss = _format_mmss(DELETE_SECONDS)
    wallclock = _wallclock_end_time_str(DELETE_SECONDS)
    countdown_text = f"⏳ [{mmss}] {wallclock}"

    try:
        countdown_msg = context.bot.send_message(chat_id=chat_id, text=countdown_text)
    except Exception as e:
        logger.exception("Failed to send countdown message: %s", e)
        # fallback: schedule a simple delete of the document if countdown can't be created
        def _del_doc():
            try:
                time.sleep(DELETE_SECONDS)
                context.bot.delete_message(chat_id=chat_id, message_id=sent.message_id)
            except Exception:
                pass
        t = threading.Thread(target=_del_doc, daemon=True)
        t.start()
        return sent.message_id, None

    # Start updater thread that edits countdown every 60 seconds and deletes both at the end
    thread = threading.Thread(
        target=_countdown_updater_thread,
        args=(context, chat_id, sent.message_id, countdown_msg.message_id, DELETE_SECONDS),
        daemon=True,
    )
    thread.start()

    return sent.message_id, countdown_msg.message_id


def _countdown_updater_thread(context: CallbackContext, chat_id: int, doc_msg_id: int, countdown_msg_id: int, total_seconds: int):
    """
    Background thread to:
      - update countdown message roughly every 60 seconds (MM:SS)
      - at the end, delete both the document message and the countdown message
    """
    start = time.time()
    end = start + total_seconds

    # First update was already sent; now loop until time is up
    while True:
        now = time.time()
        remaining = int(end - now)

        if remaining <= 0:
            # Time's up: delete both messages (ignore any exceptions)
            try:
                context.bot.delete_message(chat_id=chat_id, message_id=doc_msg_id)
            except Exception:
                pass
            try:
                context.bot.delete_message(chat_id=chat_id, message_id=countdown_msg_id)
            except Exception:
                pass
            logger.info("Deleted book msg %s and countdown %s in chat %s", doc_msg_id, countdown_msg_id, chat_id)
            break

        # Build new countdown text: emoji + [MM:SS] + end HH:MM
        mmss = _format_mmss(remaining)
        wallclock = _wallclock_end_time_str(remaining)
        new_text = f"⏳ [{mmss}] {wallclock}"

        # Try to edit the countdown message. If it fails (deleted by user), continue but ensure doc will be deleted.
        try:
            context.bot.edit_message_text(text=new_text, chat_id=chat_id, message_id=countdown_msg_id)
        except Exception as e:
            logger.debug("Could not edit countdown message %s: %s", countdown_msg_id, e)
            # If editing fails, we don't stop the loop — we still must delete the document at the end.
            # Sleep a short time and re-check remaining time so we still delete on schedule.
            time.sleep(5)
            continue

        # Sleep either 60 seconds, or the remaining if less than 60
        sleep_for = 60 if remaining > 60 else remaining
        time.sleep(sleep_for)


def start_handler(update: Update, context: CallbackContext):
    """Handles /start and deep links."""
    args = context.args or []
    chat_id = update.effective_chat.id

    # deep link: /start 3
    if args:
        code = args[0].strip()
        doc_id, countdown_id = send_book_by_code(chat_id, code, context)
        if doc_id:
            return
        update.message.reply_text("Bu kod bo‘yicha kitob topilmadi.")
        return

    user = update.effective_user
    name = user.first_name or "do‘st"
    update.message.reply_text(
        f"Assalomu alaykum, {name}!\nMenga faqat kitob kodini yuboring (masalan: 3)"
    )


def numeric_message_handler(update: Update, context: CallbackContext):
    """Handles messages that are ONLY a number like '3'."""
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if not text.isdigit():
        return  # ignore non-numeric messages

    chat_id = update.effective_chat.id

    if text not in BOOKS:
        update.message.reply_text("Bunday kod topilmadi.")
        return

    doc_id, countdown_id = send_book_by_code(chat_id, text, context)
    if not doc_id:
        update.message.reply_text("Kitobni yuborishda xatolik yuz berdi.")
