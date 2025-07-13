import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# 🔐 Bot Token
BOT_TOKEN = "7687239994:AAECEOwpI4LcoxmTmPenit8By-KgwGffang"

# ✅ Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 📚 Your books mapped by code
BOOKS = {
    "1": {
        "file_id": "BQACAgIAAyEFAAShxLgyAAMEaHOF-3v-VPSIAyQRR29W55mC6pAAAjV3AAJbeaFLtR5EyjrCEkE2BA",
        "caption": "📘 *400 Must-Have Words for the TOEFL*\n⏰ File will delete in 15 minutes.\nMore 👉 @IELTSforeverybody"
    },
    # Add more like this
    "2": {
        "file_id": "YOUR_SECOND_FILE_ID_HERE",
        "caption": "📘 *Test Book 2*\n⏰ File will delete in 15 minutes.\nMore 👉 @IELTSforeverybody"
    }
}

# ✅ /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🦊 Welcome to Voxi Bot!\n\n"
        "Send me a book code (like 1, 2, etc.) and I’ll send the file.\n\n"
        "Need help? Contact @ogabek1106"
    )

# ✅ Handle book codes
async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.strip()
    if msg in BOOKS:
        book = BOOKS[msg]
        await update.message.reply_document(
            document=book["file_id"],
            caption=book["caption"],
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("🚫 Book not found.")

# ✅ Start bot
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))

logger.info("Bot started.")
app.run_polling()
