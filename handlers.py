# handlers.py

import asyncio
import logging
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters
from config import ADMIN_IDS, USER_FILE, STORAGE_CHANNEL_ID
from books import BOOKS
from user_data import load_users, add_user
from utils import delete_after_delay

logger = logging.getLogger(__name__)
user_ids = load_users()

# /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global user_ids
    user_id = update.effective_user.id

    if user_ids is None:
        await update.message.reply_text("❌ user_ids.json not found.")
        return

    add_user(user_ids, user_id)

    arg = context.args[0] if context.args else None
    if arg and arg in BOOKS:
        await handle_code(update, context, override_code=arg)
    else:
        await update.message.reply_text(
            "🦧 Welcome to Voxi Bot!\n\n"
            "Send me a number (1, 2, etc.) and I’ll send you the file.\n\n"
            "Need help? Contact @ogabek1106"
        )

# /stats command
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in ADMIN_IDS:
        count = len(user_ids) if user_ids else 0
        await update.message.reply_text(f"📊 Total users: {count}")
    else:
        await update.message.reply_text("Darling, you are not an admin🤪")

# /all_books command
async def all_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not BOOKS:
        await update.message.reply_text("😕 No books are currently available.")
        return

    message = "📚 *Available Books:*\n\n"
    for code, data in BOOKS.items():
        title_line = data["caption"].split('\n')[0]
        message += f"{code}. {title_line}\n"

    await update.message.reply_text(message, parse_mode="Markdown")

# Handle book codes
async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE, override_code=None):
    user_id = update.effective_user.id

    if user_ids is None:
        await update.message.reply_text("❌ user_ids.json not found.")
        return

    add_user(user_ids, user_id)

    msg = override_code or update.message.text.strip()
    if msg in BOOKS:
        book = BOOKS[msg]
        sent = await update.message.reply_document(
            document=book["file_id"],
            filename=book["filename"],
            caption=book["caption"],
            parse_mode="Markdown"
        )
        context.application.create_task(
            delete_after_delay(context.bot, sent.chat.id, sent.message_id, delay=900)
        )
    elif msg.isdigit():
        await update.message.reply_text("❌ Book not found.")
    else:
        await update.message.reply_text("Huh?🤔")

# Admin uploads file
async def save_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    doc = update.message.document
    if doc:
        file_id = doc.file_id
        file_name = doc.file_name or "Untitled.pdf"

        await context.bot.send_document(
            chat_id=STORAGE_CHANNEL_ID,
            document=file_id,
            caption=f"📚 *{file_name}*",
            parse_mode="Markdown"
        )
        await update.message.reply_text(f"`{file_id}`", parse_mode="Markdown")

# Broadcast new book to all users
async def broadcast_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    if user_ids is None:
        await update.message.reply_text("❌ user_ids.json not found.")
        return

    if not context.args:
        await update.message.reply_text("❗ Usage: /broadcast_new <book_code>")
        return

    code = context.args[0]
    if code not in BOOKS:
        await update.message.reply_text("❌ No such book code.")
        return

    book = BOOKS[code]
    msg = (
        f"📚 *New Book Uploaded!*\n\n"
        f"{book['caption'].splitlines()[0]}\n"
        f"🆔 Code: `{code}`\n\n"
        f"Send this number to get the file!"
    )

    success, fail = 0, 0
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
            success += 1
        except Exception as e:
            fail += 1
            logger.warning(f"Couldn't message {uid}: {e}")

    await update.message.reply_text(f"✅ Sent to {success} users.\n❌ Failed for {fail}.")

# Registers all handlers
def register_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("all_books", all_books))
    app.add_handler(CommandHandler("broadcast_new", broadcast_new))
    app.add_handler(MessageHandler(filters.Document.PDF, save_pdf))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))
