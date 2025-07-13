import os
import logging
import asyncio
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# 🔐 Token from Railway variable
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# 📚 Book data
BOOKS = {
    "1": {
        "file_id": "BQACAgIAAyEFAAShxLgyAAMHaHOY0YvtH2OCcLR0ZAxKbt9JIGIAAtp_AALlEZhLhfS_vbLV6oY2BA",
        "filename": "400 Must-Have Words for the TOEFL.pdf",
        "caption": "📘 *400 Must-Have Words for the TOEFL*\n\n⏰ File will delete in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
    },
    # Add more books like:
    # "2": { "file_id": "...", "filename": "...", "caption": "..." }
}

# 📊 In-memory user count
user_ids = set()

# ✅ Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ✅ /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_ids.add(update.effective_user.id)
    await update.message.reply_text(
        "🦊 Welcome to Voxi Bot!\n\n"
        "Send me a number (1, 2, etc.) and I’ll send you the file.\n\n"
        "Need help? Contact @ogabek1106"
    )

# ✅ /stats
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"📊 Total users: {len(user_ids)}")

# ✅ Code handler
async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_ids.add(update.effective_user.id)
    msg = update.message.text.strip()

    if msg in BOOKS:
        book = BOOKS[msg]
        sent = await update.message.reply_document(
            document=book["file_id"],
            filename=book["filename"],
            caption=book["caption"],
            parse_mode="Markdown"
        )
        # Delete after 15 minutes (900 sec)
        await asyncio.sleep(900)
        try:
            await context.bot.delete_message(chat_id=sent.chat.id, message_id=sent.message_id)
        except Exception as e:
            logger.warning(f"Couldn't delete message: {e}")
    elif msg.isdigit():
        await update.message.reply_text("🚫 Book not found.")
    else:
        await update.message.reply_text("Huh?🤔")

# ✅ Main
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))

    logger.info("Bot started.")

    # 👇 Fix for polling conflict
    await app.bot.delete_webhook(drop_pending_updates=True)
    await app.run_polling()

# ✅ Entry point
if __name__ == "__main__":
    asyncio.run(main())
