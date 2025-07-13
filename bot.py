import logging
import os
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from dotenv import load_dotenv

# Load environment variables (optional)
load_dotenv()

# 🔐 Bot token
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# 📚 Book data
BOOKS = {
    "1": {
        "file_id": "BQACAgIAAyEFAAShxLgyAAMHaHOY0YvtH2OCcLR0ZAxKbt9JIGIAAtp_AALlEZhLhfS_vbLV6oY2BA",
        "filename": "400 Must-Have Words for the TOEFL.pdf",
        "caption": "📘 *400 Must-Have Words for the TOEFL*\n\n⏰ File will delete in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
    },
    # Add more books as needed
}

# 👤 Track users
user_ids = set()

# ⚙️ Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ▶️ /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_ids.add(update.effective_user.id)
    args = context.args

    if args and args[0] in BOOKS:
        code = args[0]
        await send_book(update, context, code)
    else:
        await update.message.reply_text(
            "🦊 Welcome to Voxi Bot!\n\n"
            "Send me a number (like 1, 2, 3...) and I’ll send the file.\n"
            "Use deep links like https://t.me/voxi_aibot?start=1\n\n"
            "Need help? Contact @ogabek1106"
        )

# 📦 Book sender with auto-delete
async def send_book(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
    book = BOOKS[code]
    sent_message = await update.message.reply_document(
        document=book["file_id"],
        caption=book["caption"],
        filename=book["filename"],
        parse_mode="Markdown"
    )

    # ⏳ Schedule deletion after 15 minutes (900 seconds)
    await context.application.job_queue.run_once(
        callback=delete_message,
        when=900,
        data={
            "chat_id": update.effective_chat.id,
            "message_id": sent_message.message_id
        }
    )

# 🗑️ Delete message job
async def delete_message(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    try:
        await context.bot.delete_message(
            chat_id=job_data["chat_id"],
            message_id=job_data["message_id"]
        )
    except Exception as e:
        logger.warning(f"Failed to delete message: {e}")

# 📩 Message handler
async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_ids.add(update.effective_user.id)
    msg = update.message.text.strip()

    if msg.isdigit():
        if msg in BOOKS:
            await send_book(update, context, msg)
        else:
            await update.message.reply_text("🚫 Book not found.")
    else:
        await update.message.reply_text("Huh? 🤔")

# 📊 /stats command
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"📊 Unique users: {len(user_ids)}")

# ▶️ Main
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))

logger.info("Bot started.")
app.run_polling()
