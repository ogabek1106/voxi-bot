# handlers.py
import logging
import threading
from telegram import Update
from telegram.ext import CallbackContext
from books import BOOKS

logger = logging.getLogger(__name__)

DELETE_SECONDS = 15 * 60  # ⬅️ 15 mins


def send_book_by_code(chat_id: int, code: str, context: CallbackContext):
    book = BOOKS.get(code)
    if not book:
        return None

    file_id = book.get("file_id")
    caption = book.get("caption", "")

    try:
        sent = context.bot.send_document(
            chat_id=chat_id,
            document=file_id,
            caption=caption,
            parse_mode="Markdown",
        )

        # 🔥 schedule deletion after DELETE_SECONDS
        def delete_message():
            try:
                context.bot.delete_message(chat_id=chat_id, message_id=sent.message_id)
            except Exception as e:
                logger.exception("Failed to delete message: %s", e)

        threading.Timer(DELETE_SECONDS, delete_message).start()
        return sent.message_id

    except Exception as e:
        logger.exception("Failed to send book: %s", e)
        return None


def start_handler(update: Update, context: CallbackContext):
    """Handles /start and deep links."""
    args = context.args or []
    chat_id = update.effective_chat.id

    # deep link: /start 3
    if args:
        code = args[0].strip()
        sent = send_book_by_code(chat_id, code, context)
        if sent:
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
    text = update.message.text.strip()

    if not text.isdigit():
        return  # ignore non-numeric messages

    chat_id = update.effective_chat.id

    if text not in BOOKS:
        update.message.reply_text("Bunday kod topilmadi.")
        return

    sent = send_book_by_code(chat_id, text, context)
    if not sent:
        update.message.reply_text("Kitobni yuborishda xatolik yuz berdi.")
