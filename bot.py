import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# 🔐 Telegram Bot Token
BOT_TOKEN = "7687239994:AAECEOwpI4LcoxmTmPenit8By-KgwGffang"

# ✅ Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 📚 Books stored by code with Telegram file_id
BOOKS = {
    "1": {
        "file_id": "BQACAgIAAyEFAAShxLgyAAMGaHOSqauACG3rUDbW-TXDoNBrp70AAoV_AALlEZhLDIyFa-vyqIc2BA",
        "caption": "📘 *400 Must-Have Words for the TOEFL*\n⏰ File will delete in 15 minutes.\nMore 👉 @IELTSforeverybody"
    },
    # Add more codes and file_ids below as needed
}

# 🔰 /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🦊 Welcome to Voxi Bot!\n\n"
        "Send me a book code (like 1, 2, etc.) and I’ll send the file.\n\n"
        "Need help? Contact @ogabek1106"
    )

# 📦 Book code handler
async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.strip()
    logger.info(f"Received message: {msg}")

    if msg in BOOKS:
        book = BOOKS[msg]
        await update.message.reply_document(
            document=book["file_id"],
            caption=book["caption"],
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("🚫 Book not found.")

# 🚀 Start the bot
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))

logger.info("Bot started.")
app.run_polling()
