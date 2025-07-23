# 📦 Section 1: Imports
import os
import logging
import asyncio
import json
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# 🛡️ Section 2: Config and Logging
BOT_TOKEN = os.environ.get("BOT_TOKEN")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 👮 Section 3: Admin Setup
ADMIN_IDS = {1150875355}
USER_FILE = "user_ids.json"

# 📚 Section 4: Book Data
BOOKS = {
    "1": {
        "file_id": "BQACAgIAAyEFAAShxLgyAAMHaHOY0YvtH2OCcLR0ZAxKbt9JIGIAAtp_AALlEZhLhfS_vbLV6oY2BA",
        "filename": "400 Must-Have Words for the TOEFL.pdf",
        "caption": "📘 *400 Must-Have Words for the TOEFL*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
    },
    "2": {
        "file_id": "BQACAgIAAyEFAAShxLgyAAMIaHTLj1ymrZu1diD984RuvlAj_koAAiJ4AAIqialLGblaFusMwbE2BA",
        "filename": "English for Everyone - English Vocabulary Builder.pdf",
        "caption": "📔 *English for Everyone - English Vocabulary Builder*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
    },
    "3": {
        "file_id": "BQACAgIAAyEFAAShxLgyAAMJaHTV90bucYoT77gYbOqvQDBaAzQAArl4AAIqialLGRvupb7SoTw2BA",
        "filename": "179 IELTS Speaking Part 2 Samples.pdf",
        "caption": "📔 *179 IELTS Speaking Part 2 Samples*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
    },
    "4": {
        "file_id": "BQACAgIAAyEFAAShxLgyAAMKaHuTV-6UuvFfsN2IoBBZOPhBL1IAArF7AAII39lLZcNcwPuNh0c2BA",
        "filename": "IELTS the vocabulary fies.pdf",
        "caption": "📘 *IELTS the vocabulary fies*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
    },
    "5": {
        "file_id": "BQACAgIAAyEFAAShxLgyAAMLaH5BmPsEv1jcuRSJ9psgugurCMUAAoR1AAJXF_BLF9jUggPZszU2BA",
        "filename": "📕 The Big Book of Words You Should Know.pdf",
        "caption": "📕 *The Big Book of Words You Should Know*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
    }
}

# 📊 Section 5: Persistent User Memory
# 📊 Section 5: Persistent User Memory
try:
    with open(USER_FILE, "r") as f:
        user_ids = set(json.load(f))
except (FileNotFoundError, json.JSONDecodeError):
    user_ids = set()

# 📖 Section 6: Command Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_ids:
        user_ids.add(user_id)
        with open(USER_FILE, "w") as f:
            json.dump(list(user_ids), f)

    arg = context.args[0] if context.args else None
    if arg and arg in BOOKS:
        await handle_code(update, context, override_code=arg)
    else:
        await update.message.reply_text(
            "🦧 Welcome to Voxi Bot!\n\n"
            "Send me a number (1, 2, etc.) and I’ll send you the file.\n\n"
            "Need help? Contact @ogabek1106"
        )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in ADMIN_IDS:
        await update.message.reply_text(f"📊 Total users: {len(user_ids)}")
    else:
        await update.message.reply_text("Darling, you are not an admin🤪")

async def all_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not BOOKS:
        await update.message.reply_text("😕 No books are currently available.")
        return

    message = "📚 *Available Books:*\n\n"
    for code, data in BOOKS.items():
        title_line = data["caption"].split('\n')[0]
        message += f"{code}. {title_line}\n"

    await update.message.reply_text(message, parse_mode="Markdown")

async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE, override_code=None):
    user_id = update.effective_user.id
if user_id not in user_ids:
    user_ids.add(user_id)
    with open(USER_FILE, "w") as f:
        json.dump(list(user_ids), f)

    msg = override_code or update.message.text.strip()
    if msg in BOOKS:
        book = BOOKS[msg]
        sent = await update.message.reply_document(
            document=book["file_id"],
            filename=book["filename"],
            caption=book["caption"],
            parse_mode="Markdown"
        )
        async def delete_later(bot, chat_id, message_id):
            await asyncio.sleep(900)
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
            except Exception as e:
                logger.warning(f"Couldn't delete message: {e}")

        context.application.create_task(delete_later(context.bot, sent.chat.id, sent.message_id))
    elif msg.isdigit():
        await update.message.reply_text("❌ Book not found.")
    else:
        await update.message.reply_text("Huh?🤔")

# 🚀 Section 7: Bot Setup and Run
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(CommandHandler("all_books", all_books))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))

logger.info("Bot started.")
app.run_polling()
