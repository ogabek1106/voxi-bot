# handlers.py — minimal handlers for Voxi bot + improved debug/fallback logic
import threading
import time
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters
from books import BOOKS
from database import (
    save_user,
    increment_book_request,
    save_countdown,
    get_all_countdowns,
    delete_countdown,
)
from datetime import datetime


# ============================================================
# Background Worker (always running)
# ============================================================

def countdown_worker(application):
    """
    This thread runs forever.
    Every 5 seconds it checks the countdowns table.
    If a countdown expired → deletes the book message + removes countdown.
    """

    while True:
        try:
            countdowns = get_all_countdowns()
            now = int(time.time())

            for cd in countdowns:
                user_id = cd["user_id"]
                book_code = cd["book_code"]
                end_ts = cd["end_timestamp"]
                message_id = cd["message_id"]

                if now >= end_ts:
                    try:
                        # delete the message
                        application.bot.delete_message(
                            chat_id=user_id,
                            message_id=message_id
                        )
                    except Exception as e:
                        print("Delete error:", e)

                    # remove countdown from DB
                    delete_countdown(user_id, book_code)

            time.sleep(5)

        except Exception as e:
            print("Worker error:", e)
            time.sleep(5)


# Starts the background thread
def start_worker(application):
    worker = threading.Thread(target=countdown_worker, args=(application,), daemon=True)
    worker.start()


# ============================================================
# Handlers
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user.id)
    await update.message.reply_text("Voxi bot online ⚡️")


async def get_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user.id)

    args = update.message.text.split()
    if len(args) < 2:
        return await update.message.reply_text("❗ Send code: /get <code>")

    code = args[1].upper()

    if code not in BOOKS:
        return await update.message.reply_text("❗ Invalid code")

    data = BOOKS[code]
    file_id = data["file_id"]

    # Send the book
    msg = await update.message.reply_document(
        document=file_id,
        caption=f"📘 *{code}* — you have 15 minutes!",
        parse_mode="Markdown"
    )

    # Count request
    increment_book_request(code)

    # Save countdown
    end_ts = int(time.time()) + 900  # 15 minutes
    save_countdown(
        user_id=user.id,
        book_code=code,
        end_timestamp=end_ts,
        message_id=msg.message_id
    )


# ============================================================
# Register
# ============================================================

def setup_handlers(application):
    # Start background countdown worker
    start_worker(application)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("get", get_book))

    # fallback echo
    application.add_handler(MessageHandler(filters.ALL, start))
