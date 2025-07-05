import os
import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# Bot token
TOKEN = "7687239994:AAGRHu3GE0HehgnmcwdrJQnwQvNCXE4t7Mo"

# Folder where PDF files are stored
BOOKS_DIR = "books"

# Code → File path
BOOKS = {
    "1": "1.pdf",
    "445": "445.pdf",
    "446": "446.pdf",
    "447": "447.pdf"
}

# Code → Custom filename when sending
FILENAMES = {
    "1": "@ieltsforeverybody - 400 must-have words for the TOEFL-MGH 2005.pdf",
    "445": "445.pdf",
    "446": "446.pdf",
    "447": "447.pdf"
}

# Code → Description
DESCRIPTIONS = {
    "1": "📘 *400 Must-Have Words for the TOEFL* (McGraw-Hill, 2005)\n\n⏰ File will be deleted after 15 minutes, so make sure that you've downloaded it.\n\n📚 For more -> @IELTSforeverybody",
    "445": "📘 Basic IELTS book with practice tests.\n\n⏰ Auto-deletes in 15 minutes.",
    "446": "📗 Intermediate IELTS grammar guide.\n\n⏰ Auto-deletes in 15 minutes.",
    "447": "📕 Advanced writing techniques for IELTS Task 2.\n\n⏰ Auto-deletes in 15 minutes."
}

# Background deletion task
async def delete_after_delay(context: ContextTypes.DEFAULT_TYPE, chat_id, message_id):
    await asyncio.sleep(900)  # 15 minutes
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except:
        pass

# Send file by code
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
        # Start background task (don't block)
        context.application.create_task(
            delete_after_delay(context, sent_msg.chat_id, sent_msg.message_id)
        )
    else:
        await update.message.reply_text("❌ Sorry, file not found.")

# /start or referral link
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
Send me the code of an e-book and I’ll deliver it instantly.

⏳ Files self-destruct in 15 minutes for your privacy.

Need help? Type /help or [contact Ogabek](https://t.me/ogabek1106) 😉
"""
        await update.message.reply_text(welcome, parse_mode="Markdown")

# Handle messages (codes or ping)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text.lower() == "ping":
        await update.message.reply_text("pong 🏓")
    elif text.isdigit() and text in BOOKS:
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

    print("✅ Voxi Bot is running...")

    # Railway (webhook mode)
    if "RAILWAY_STATIC_URL" in os.environ:
        PORT = int(os.environ.get("PORT", 8443))
        URL = f"https://{os.environ['RAILWAY_STATIC_URL']}/webhook"

        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=URL
        )
    else:
        # For local testing
        app.run_polling()
