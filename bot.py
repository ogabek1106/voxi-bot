import os
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters

TOKEN = "7687239994:AAFAD9tHc3bJWOgOx6G5SB82CWboveKmKko"

# Dictionary of code: filename
BOOKS = {
    "445": "445.pdf",
    "446": "446.pdf",
    "447": "447.pdf"
}

BOOKS_DIR = "books"

async def send_book(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
    file_path = os.path.join(BOOKS_DIR, BOOKS[code])
    if os.path.exists(file_path):
        sent_msg = await update.message.reply_document(
            document=open(file_path, "rb"),
            filename=BOOKS[code]
        )
        # Delete after 15 minutes
        await asyncio.sleep(900)
        try:
            await context.bot.delete_message(chat_id=sent_msg.chat_id, message_id=sent_msg.message_id)
        except:
            pass
    else:
        await update.message.reply_text("❌ Sorry, file not found.")

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

Need help? Type `/help` or contact Ogabek directly 😉
"""
        await update.message.reply_text(welcome, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and text in BOOKS:
        await send_book(update, context, text)
    elif text.isdigit():
        await update.message.reply_text("❌ This code is not available.")
    else:
        await update.message.reply_text("🔍 Please send a valid book code (like 445).")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Voxi Bot is running... Waiting for codes...")
    app.run_polling()
