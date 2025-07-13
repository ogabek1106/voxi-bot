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

# 🔐 Bot Token from Railway variable
BOT_TOKEN = os.environ.get("BOT_TOKEN")

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
    # Add more like "2": {...}
}

# 📊 Stats memory
user_ids = set()

# 🕒 Delete message after 15 minutes
async def delete_after_delay(bot, chat_id, message_id):
    await asyncio.sleep(900)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.warning(f"Couldn't delete message: {e}")

# ✅ /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_ids.add(update.effective_user.id)
    args = context.args

    if args and args[0] in BOOKS:
        book = BOOKS[args[0]]
        sent = await update.message.reply_document(
            document=book["file_id"],
            filename=book["filename"],
            caption=book["caption"],
            parse_mode="Markdown"
        )
        asyncio.create_task(delete_after_delay(context.bot, sent.chat.id, sent.message_id))
    elif args:
        await update.message.reply_text("🚫 Book not found.")
    else:
        await update.message.reply_text(
            "🦊 Welcome to Voxi Bot!\n\n"
            "Send me a number (1, 2, etc.) and I’ll send you the file.\n\n"
            "Need help? Contact @ogabek1106"
        )

# ✅ /stats command
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"📊 Total users: {len(user_ids)}")

# ✅ Handle message
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
        asyncio.create_task(delete_after_delay(context.bot, sent.chat.id, sent.message_id))
    elif msg.isdigit():
        await update.message.reply_text("🚫 Book not found.")
    else:
        await update.message.reply_text("Huh?🤔")

# ✅ App start
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))

logger.info("Bot started.")
app.run_polling()
