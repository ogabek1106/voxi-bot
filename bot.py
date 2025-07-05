import os
import asyncio
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    ContextTypes, filters
)

# Environment variables
TOKEN = os.getenv("TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 8443))
BOOKS_DIR = "books"

# Book mappings
BOOKS = {
    "1": "1.pdf",
    "445": "445.pdf",
    "446": "446.pdf",
    "447": "447.pdf"
}

FILENAMES = {
    "1": "@ieltsforeverybody - 400 must-have words for the TOEFL-MGH 2005.pdf",
    "445": "445.pdf",
    "446": "446.pdf",
    "447": "447.pdf"
}

DESCRIPTIONS = {
    "1": "📘 *400 Must-Have Words for the TOEFL* (McGraw-Hill, 2005)\n\n⏰ File will be deleted after 15 minutes, so make sure that you've downloaded it.\n\n📚 For more -> @IELTSforeverybody",
    "445": "Basic IELTS book with practice tests.",
    "446": "Intermediate level IELTS grammar guide.",
    "447": "Advanced writing techniques for IELTS Task 2."
}

# Send book by code
async def send_book(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
    file_path = os.path.join(BOOKS_DIR, BOOKS[code])
    custom_name = FILENAMES.get(code, BOOKS[code])
    caption = DESCRIPTIONS.get(code, "")

    if os.path.exists(file_path):
        sent_msg = await update.message.reply_document(
            document=open(file_path, "rb"),
            filename=custom_name,
            caption=caption,
            parse_mode="Markdown"
        )
        await asyncio.sleep(900)
        try:
            await context.bot.delete_message(chat_id=sent_msg.chat_id, message_id=sent_msg.message_id)
        except:
            pass
    else:
        await update.message.reply_text("❌ Sorry, file not found.")

# /start handler
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        code = context.args[0]
        if code in BOOKS:
            await send_book(update, context, code)
        else:
            await update.message.reply_text("❌ Invalid code.")
    else:
        user_first = update.effective_user.first_name or "friend"
        welcome = f"""
👋 Hi, {user_first}!

🦊 I’m *Voxi*, your AI assistant.
Send me the code of a e-book and I’ll deliver the e-book to you instantly.

⏳ Files will self-destruct in 15 minutes for your privacy.

Need help? Type `/help` or [contact Ogabek]
