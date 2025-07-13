import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# 🔐 Replace with your actual bot token
BOT_TOKEN = "7687239994:AAFJ3PazUciXzEVTmSIm4WGPRJN5GxosOBo"

# ✅ Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 📚 Book data
BOOKS = {
    "1": {
        "file_id": "BQACAgIAAyEFAAShxLgyAAMEaHOF-3v-VPSIAyQRR29W55mC6pAAAjV3AAJbeaFLtR5EyjrCEkE2BA",
        "file_name": "@ieltsforeverybody_400_must_have_words_for_the_TOEFL.pdf",
        "caption": (
            "📘 *400 Must-Have Words for the TOEFL* (McGraw-Hill, 2005)\n\n"
            "⏰ File will be deleted after 15 minutes, so make sure that you've downloaded it.\n\n"
            "📚 For more -> @IELTSforeverybody"
        )
    }
}

# 🟢 /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hi! Send me a code like '1' to get your book.")

# 📩 Message handler
async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    if code in BOOKS:
        book = BOOKS[code]
        await update.message.reply_document(
            document=book["file_id"],
            filename=book["file_name"],
            caption=book["caption"],
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("🚫 Book not found.")

# 🚀 Run bot
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))
app.run_polling()
