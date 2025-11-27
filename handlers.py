# handlers.py — minimal handlers for Voxi bot + improved debug logic
import logging
import time
import asyncio
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from books import BOOKS
from database import (
    add_user_if_not_exists,
    increment_book_request,
    save_rating,
    save_countdown,
    get_all_countdowns,
    get_expired_countdowns,
    delete_countdown,
    has_rated,
)

logger = logging.getLogger(__name__)


# ----------------------------
# COMMAND HANDLERS
# ----------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = getattr(user, "id", None)
    if user_id:
        try:
            add_user_if_not_exists(user_id)
        except Exception:
            logger.exception("add_user_if_not_exists failed for %s", user_id)
    await update.message.reply_text("Assalomu alaykum! 👋")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Commands:\n/book CODE\n/rate CODE 1-5")


async def send_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /book CODE
    Sends a book document and creates a countdown row (15 minutes) that will be
    processed by the background worker. Uses database.save_countdown(user_id, code, end_timestamp, message_id).
    """
    user = update.effective_user
    user_id = getattr(user, "id", None)
    chat_id = update.effective_chat.id

    if len(context.args) == 0:
        await update.message.reply_text("❗ Write book code. Example: /book A1")
        return

    code = context.args[0].strip()
    # allow uppercase match
    if code not in BOOKS and code.upper() in BOOKS:
        code = code.upper()

    if code not in BOOKS:
        await update.message.reply_text("❌ This book code does not exist.")
        return

    book = BOOKS[code]
    file_id = book["file_id"]

    # increment request counter (DB)
    try:
        increment_book_request(code)
    except Exception:
        logger.exception("increment_book_request failed for %s", code)

    # send file and capture message_id
    try:
        sent = await context.bot.send_document(chat_id=chat_id, document=file_id,
                                               filename=book.get("filename"),
                                               caption=book.get("caption"))
        message_id = getattr(sent, "message_id", None)
    except Exception as e:
        logger.exception("Failed to send document %s to %s: %s", code, chat_id, e)
        await update.message.reply_text("❌ Failed to send file. Please try again later.")
        return

    # schedule countdown: 15 minutes from now
    end_ts = int(time.time()) + 15 * 60
    try:
        # save_countdown(user_id, book_code, end_timestamp, message_id)
        save_countdown(user_id, code, end_ts, message_id)
        logger.debug("Saved countdown: user=%s code=%s msg=%s end_ts=%s", user_id, code, message_id, end_ts)
    except Exception:
        logger.exception("Failed to save countdown for %s %s", user_id, code)

    # send rating buttons if user hasn't rated this book yet
    try:
        if user_id is not None and not has_rated(user_id, code):
            buttons = [[InlineKeyboardButton(f"{i}⭐", callback_data=f"rate|{code}|{i}")] for i in range(1, 6)]
            await context.bot.send_message(chat_id=chat_id, text="How would you rate this book?",
                                           reply_markup=InlineKeyboardMarkup(buttons))
    except Exception:
        logger.exception("Failed to send rating buttons for %s to %s", code, user_id)


async def rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /rate CODE RATING  or  /rate CODE 5
    If user only sends a single numeric argument, ask them to provide CODE as well.
    """
    user = update.effective_user
    user_id = getattr(user, "id", None)

    if len(context.args) == 0:
        await update.message.reply_text("❗ Write rating in format: /rate CODE 5")
        return

    if len(context.args) == 1:
        # single arg — might be a rating number, but we need a book code as well
        try:
            _ = int(context.args[0])
            await update.message.reply_text("Please specify book code too. Example: /rate A1 5")
            return
        except Exception:
            await update.message.reply_text("Invalid format. Example: /rate A1 5")
            return

    # assume args[0] = code, args[1] = rating
    code = context.args[0].strip()
    if code not in BOOKS and code.upper() in BOOKS:
        code = code.upper()
    if code not in BOOKS:
        await update.message.reply_text("❌ This book code does not exist.")
        return

    try:
        rating = int(context.args[1])
    except Exception:
        await update.message.reply_text("❗ Rating must be a number from 1 to 5.")
        return

    if not (1 <= rating <= 5):
        await update.message.reply_text("❗ Rating must be 1–5.")
        return

    try:
        save_rating(user_id, code, rating)
        await update.message.reply_text("⭐ Rating saved. Thank you!")
    except Exception:
        logger.exception("save_rating failed for %s %s by %s", user_id, code, rating)
        await update.message.reply_text("⚠️ Failed to save rating.")


# ----------------------------
# MESSAGE HANDLER
# ----------------------------

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Keep behaviour for unknown commands (commands we don't handle).
    Note: plain text that isn't a code is ignored in this implementation (no spam).
    """
    # If it's a command (starts with /) and not recognized, notify the user.
    # If you want to silently ignore all non-command texts, register a separate text handler.
    await update.message.reply_text("❗ I don't understand this command.")


# ----------------------------
# BACKGROUND COUNTDOWN WORKER
# ----------------------------

async def _countdown_worker(application):
    """
    Background task — checks DB for expired countdowns, deletes messages and removes rows.
    This runs continuously while the bot is alive.
    """
    logger.info("Countdown worker started")
    bot = application.bot
    while True:
        try:
            now_ts = int(time.time())
            expired = get_expired_countdowns(now_ts)
            if expired:
                logger.debug("Countdown worker: %d expired rows", len(expired))
            for row in expired:
                user_id = row["user_id"]
                book_code = row["book_code"]
                message_id = row["message_id"]
                try:
                    await bot.delete_message(chat_id=user_id, message_id=message_id)
                    logger.info("Deleted message %s for user %s (book %s)", message_id, user_id, book_code)
                except BadRequest as e:
                    # message may already be deleted or too old
                    logger.debug("Could not delete message %s for %s: %s", message_id, user_id, e)
                except TelegramError:
                    logger.exception("Telegram error when deleting message %s for %s", message_id, user_id)
                except Exception:
                    logger.exception("Unexpected error deleting message %s for %s", message_id, user_id)

                # remove DB row regardless of deletion result
                try:
                    delete_countdown(user_id, book_code)
                except Exception:
                    logger.exception("Failed to delete countdown DB row for %s %s", user_id, book_code)

            # sleep for a short interval (tunable)
            await asyncio.sleep(8)
        except Exception:
            logger.exception("Countdown worker encountered an error; sleeping briefly")
            await asyncio.sleep(5)


# ----------------------------
# REQUIRED FUNCTION: register handlers and start worker
# ----------------------------

def register_handlers(application):
    """ REQUIRED by bot.py """

    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("book", send_book))
    application.add_handler(CommandHandler("rate", rate))

    # rating via inline buttons (if used elsewhere)
    async def _rating_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
        # pattern 'rate|CODE|N' — keep compatibility if you use inline buttons
        q = update.callback_query
        if not q:
            return
        await q.answer()
        parts = (q.data or "").split("|")
        if len(parts) != 3 or parts[0] != "rate":
            return
        _, code, rating_str = parts
        try:
            rating = int(rating_str)
        except Exception:
            await q.edit_message_text("Invalid rating.")
            return
        user_id = getattr(q.from_user, "id", None)
        if user_id is None:
            await q.edit_message_text("Unable to identify you.")
            return
        try:
            save_rating(user_id, code, rating)
            await q.edit_message_text("✅ Thanks for your rating!")
        except Exception:
            logger.exception("Failed to save rating via callback %s %s by %s", user_id, code, rating)
            try:
                await q.edit_message_text("⚠️ Failed to save your rating.")
            except Exception:
                pass

    application.add_handler(CallbackQueryHandler(_rating_cb, pattern=r"^rate\|"))

    # Unknown commands -> this handler will reply "I don't understand..."
    application.add_handler(MessageHandler(filters.COMMAND, unknown))

    # If you want plain text codes (like sending '1') to work, register a separate handler:
    async def _text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message
        if not msg or not msg.text:
            return
        text = msg.text.strip()
        chat_id = update.effective_chat.id
        user = update.effective_user
        user_id = getattr(user, "id", None)

        code = text
        if code not in BOOKS and code.upper() in BOOKS:
            code = code.upper()

        if code in BOOKS:
            # re-use send_book logic but avoid duplicating DB increment: call increment + send + save_countdown
            try:
                increment_book_request(code)
            except Exception:
                logger.exception("increment_book_request failed for %s", code)

            book = BOOKS[code]
            try:
                sent = await context.bot.send_document(chat_id=chat_id, document=book["file_id"],
                                                       filename=book.get("filename"),
                                                       caption=book.get("caption"))
                message_id = getattr(sent, "message_id", None)
                end_ts = int(time.time()) + 15 * 60
                if message_id is not None:
                    try:
                        save_countdown(user_id, code, end_ts, message_id)
                        logger.debug("Saved countdown (text): user=%s code=%s msg=%s end=%s", user_id, code, message_id, end_ts)
                    except Exception:
                        logger.exception("Failed to save countdown (text) for %s %s", user_id, code)
                # rating buttons
                try:
                    if user_id is not None and not has_rated(user_id, code):
                        buttons = [[InlineKeyboardButton(f"{i}⭐", callback_data=f"rate|{code}|{i}")] for i in range(1, 6)]
                        await context.bot.send_message(chat_id=chat_id, text="How would you rate this book?", reply_markup=InlineKeyboardMarkup(buttons))
                except Exception:
                    logger.exception("Failed to send rating buttons for %s to %s", code, user_id)
            except Exception:
                logger.exception("Failed to send document for code %s to %s", code, chat_id)
            return

        # otherwise ignore plain text (do not spam user)
        logger.debug("Ignored plain text from %s: %r", user_id, text)

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _text_handler), group=1)

    # Start countdown worker task
    try:
        application.create_task(_countdown_worker(application))
        logger.info("Scheduled countdown worker")
    except Exception:
        logger.exception("Failed to schedule countdown worker")

    logger.info("Handlers registered.")
    return application
