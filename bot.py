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

# Send book
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
        welcome = (
            f"👋 Hi, {user_first}!\n\n"
            "🦊 I’m *Voxi*, your AI assistant.\n"
            "Send me the code of a e-book and I’ll deliver the e-book to you instantly.\n\n"
            "⏳ Files will self-destruct in 15 minutes for your privacy.\n\n"
            "Need help? Type `/help` or [contact Ogabek](https://t.me/ogabek1106) directly 😉"
        )
        await update.message.reply_text(welcome, parse_mode="Markdown")

# Handle normal messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and text in BOOKS:
        await send_book(update, context, text)
    elif text.isdigit():
        await update.message.reply_text("❌ This code is not available.")
    else:
        await update.message.reply_text("🔍 Please send a valid book code (like 445).")

# Main
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Voxi Bot is live with webhook on Railway!")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=WEBHOOK_URL
    )
