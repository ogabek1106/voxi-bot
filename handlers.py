# handlers.py
import logging
import threading
import time
from telegram import Update
from telegram.ext import CallbackContext
from books import BOOKS

logger = logging.getLogger(__name__)

DELETE_SECONDS = 15 * 60  # ⬅️ 15 mins
PROGRESS_BAR_LENGTH = 12  # adjust length of bar if you want


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


def _build_progress_bar(remaining: int, total: int, length: int = PROGRESS_BAR_LENGTH) -> str:
    """Return a bar like █████----- based on remaining/total."""
    if total <= 0:
        return "─" * length
    frac = max(0.0, min(1.0, remaining / total))
    filled = int(round(frac * length))
    filled = max(0, min(length, filled))
    bar = "█" * filled + "─" * (length - filled)
    return bar


def send_book_by_code(chat_id: int, code: str, context: CallbackContext):
    """
    Sends the book (document) and a live-updating countdown message in the format:
    ⏳ [█████-----] 04:30 - qolgan vaqt
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

    # Prepare initial countdown text (full bar)
    mmss = _format_mmss(DELETE_SECONDS)
    bar = _build_progress_bar(DELETE_SECONDS, DELETE_SECONDS)
    countdown_text = f"⏳ [{bar}] {mmss} - qolgan vaqt"

    try:
        # send a plain text countdown (no markup)
        countdown_msg = context.bot.send_message(chat_id=chat_id, text=countdown_text, disable_web_page_preview=True)
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
      - update countdown message roughly every 60 seconds (progress bar + MM:SS - qolgan vaqt)
      - at the end, delete both the document message and the countdown message
    """
    start = time.time()
    end = start + total_seconds
    current_countdown_id = countdown_msg_id

    # Loop until time is up
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
                context.bot.delete_message(chat_id=chat_id, message_id=current_countdown_id)
            except Exception:
                pass
            logger.info("Deleted book msg %s and countdown %s in chat %s", doc_msg_id, current_countdown_id, chat_id)
            break

        # Build progress bar and MM:SS text
        bar = _build_progress_bar(remaining, total_seconds)
        mmss = _format_mmss(remaining)
        new_text = f"⏳ [{bar}] {mmss} - qolgan vaqt"

        # Try to edit the countdown message. If it fails, create a new one and delete old (best-effort).
        try:
            context.bot.edit_message_text(text=new_text, chat_id=chat_id, message_id=current_countdown_id)
        except Exception as e:
            logger.debug("Could not edit countdown message %s: %s", current_countdown_id, e)
            # Attempt to post a new countdown message so the user sees the timer
            try:
                new_msg = context.bot.send_message(chat_id=chat_id, text=new_text, disable_web_page_preview=True)
                # best-effort delete old countdown message (ignore any error)
                try:
                    context.bot.delete_message(chat_id=chat_id, message_id=current_countdown_id)
                except Exception:
                    pass
                # update current countdown id to the newly created message
                current_countdown_id = new_msg.message_id
            except Exception as send_err:
                # If even sending fails, log and continue — we'll still delete the document at the end
                logger.debug("Also failed to send new countdown message: %s", send_err)
                # Sleep a short time and loop again so deletion still happens on schedule
                time.sleep(5)
                continue

        # Sleep either 60 seconds, or the remaining if less than 60
        sleep_for = 60 if remaining > 60 else remaining
        time.sleep(sleep_for)


def start_handler(update: Update, context: CallbackContext):
    """Handles /start and deep links.

    Important changes:
    - If payload == 'get_test' -> do nothing here (feature handles it).
    - If payload is numeric -> treat as book code (unchanged).
    - If payload is non-numeric and not 'get_test' -> ignore.
    """

    # 🔴 BLOCK /start logic during admin conversations
    if context.user_data:
        return
        
    args = context.args or []
    chat_id = update.effective_chat.id

    if args:
        payload = str(args[0]).strip()

        # If deep link is explicitly for test feature, let the feature handle it.
        if payload.lower() == "get_test":
            # Do nothing here so features/test_form.py (or features/deep_link.py) can respond.
            # This prevents the core handler from sending greetings or "book not found" replies.
            return

        # Normal numeric deep-link -> book code (keep existing behaviour)
        if payload.isdigit():
            code = payload
            doc_id, countdown_id = send_book_by_code(chat_id, code, context)
            if doc_id:
                return
            update.message.reply_text("Bu kod bo‘yicha kitob topilmadi.")
            return

        # Non-numeric payload (not get_test) -> ignore (no reply).
        # This avoids misinterpreting arbitrary deep-link payloads and prevents unwanted replies.
        return

    # No payload: regular /start invoked by user — keep original greeting behaviour.
    user = update.effective_user
    # use user's first name (or fallback 'do‘st')
    name = (user.first_name or "do‘st") if user else "do‘st"
    update.message.reply_text(
        f"Assalomu alaykum, {name}!\nMenga faqat kitob kodini yuboring (masalan: 3)"
    )


def numeric_message_handler(update: Update, context: CallbackContext):
    # 🔴 BLOCK numeric handler during admin conversations (e.g. /create_test)
    if context.user_data:
        return
        
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
