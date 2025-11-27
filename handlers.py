# handlers.py — minimal handlers for Voxi bot + improved debug/fallback logic
import logging
from telegram import Update
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    CallbackContext,
    filters
)

from books import BOOKS
from database import (
    save_user,
    save_book_request,
    save_rating,
    save_countdown,
    get_countdown,
    delete_countdown
)

logger = logging.getLogger(__name__)


# ----------------------------
# COMMAND HANDLERS
# ----------------------------

async def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    save_user(user_id)
    await update.message.reply_text("Assalomu alaykum! 👋")


async def help_command(update: Update, context: CallbackContext):
    await update.message.reply_text("Commands:\n/book CODE\n/rate 1-5")


async def send_book(update: Update, context: CallbackContext):
    user_id = update.effective_user.id

    if len(context.args) == 0:
        await update.message.reply_text("❗ Write book code. Example: /book A1")
        return

    code = context.args[0].upper()

    if code not in BOOKS:
        await update.message.reply_text("❌ This book code does not exist.")
        return

    file_id = BOOKS[code]["file_id"]
    save_book_request(user_id, code)

    # Send book
    await update.message.reply_document(file_id)

    # Start countdown
    end_timestamp = save_countdown(user_id, code)
    context.application.create_task(
        countdown_task(update, context, user_id, code, end_timestamp)
    )


async def countdown_task(update, context, user_id, code, end_timestamp):
    import asyncio
    import time

    remaining = end_timestamp - int(time.time())
    while remaining > 0:
        await asyncio.sleep(5)
        remaining = end_timestamp - int(time.time())

    await update.message.reply_text("⏳ 15 minutes finished. The file was auto-deleted.")
    delete_countdown(user_id, code)


async def rate(update: Update, context: CallbackContext):
    user_id = update.effective_user.id

    if len(context.args) == 0:
        await update.message.reply_text("❗ Write rating 1–5. Example: /rate 5")
        return

    try:
        rating = int(context.args[0])
    except:
        await update.message.reply_text("❗ Rating must be a number from 1 to 5.")
        return

    if rating < 1 or rating > 5:
        await update.message.reply_text("❗ Rating must be 1–5.")
        return

    save_rating(user_id, rating)
    await update.message.reply_text("⭐ Rating saved. Thank you!")


# ----------------------------
# MESSAGE HANDLER
# ----------------------------

async def unknown(update: Update, context: CallbackContext):
    await update.message.reply_text("❗ I don't understand this command.")


# ----------------------------
# REQUIRED FUNCTION
# ----------------------------

def register_handlers(application):
    """
    REQUIRED by bot.py
    """

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("book", send_book))
    application.add_handler(CommandHandler("rate", rate))

    # Unknown messages
    application.add_handler(MessageHandler(filters.TEXT, unknown))

    return application
