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

# 🔐 Load bot token from environment
BOT_TOKEN = os.environ["BOT_TOKEN"]

# ✅ Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 📚 Book data
BOOKS = {
    "1": {
        "file_id": "BQACAgIAAyEFAAShxLgyAAMHaHOY0YvtH2OCcLR0ZAxKbt9JIGIAAtp_AALlEZhLhfS_vbLV6oY2BA",
        "filename": "400 Must-Have Words for the TOEFL.pdf",
        "caption": "📘 *400 Must-Have Words for the TOEFL*\n\n⏰ File will delete in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
    },
    # Add more if needed
}

# ✅ /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if args and args[0] in BOOKS:
        await send_book(update, context, args[0])
    else:
        await update.message.reply_text(
            "🦊 Welcome to Voxi Bot!\n\n"
            "Send me a book code (like 1, 2, etc.) and I’ll send the file.\n\n"
            "Need help? Contact @ogabek1106"
        )

# ✅ Book sender with background deletion
async def send_book(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
    book = BOOKS.get(code)
    if book:
        msg = await update.message.reply_document(
            document=book["file_id"],
            filename=book["filename"],
            caption=book["caption"],
            parse_mode="Markdown"
        )

        async def delete_later():
            await asyncio.sleep(900)
            try:
                await context.bot.delete_message(chat_id=msg.chat.id, message_id=msg.message_id)
                logger.info(f"Deleted message {msg.message_id} from chat {msg.chat.id}")
            except Exception as e:
                logger.warning(f"Failed to delete message: {e}")

        asyncio.create_task(delete_later())
    else:
        await update.message.reply_text("🚫 Book not found.")

# ✅ Handle general messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.strip()
    if msg.isdigit():
        await send_book(update, context, msg)
    else:
        await update.message.reply_text("Huh?🤔")

# ✅ Run the bot
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot started.")
    app.run_polling()
