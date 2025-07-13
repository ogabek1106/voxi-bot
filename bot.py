import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import os

# 🔐 Bot Token from Railway variables
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ✅ Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 📚 Book data
BOOKS = {
    "1": {
        "file_id": "BQACAgIAAyEFAAShxLgyAAMGaHOSqauACG3rUDbW-TXDoNBrp70AAoV_AALlEZhLDIyFa-vyqIc2BA",
        "filename": "400 Must-Have Words for the TOEFL.pdf",
        "caption": "📘 *400 Must-Have Words for the TOEFL*\n\n⏰ File will delete in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
    },
    # Add more if needed
}

# ✅ /start handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    if args and args[0].isdigit():
        code = args[0]
        if code in BOOKS:
            book = BOOKS[code]
            await update.message.reply_document(
                document=book["file_id"],
                filename=book["filename"],
                caption=book["caption"],
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("🚫 Book not found.")
        return

    await update.message.reply_text(
        "🦊 Welcome to Voxi Bot!\n\n"
        "Send me a book code (like 1, 2, etc.) and I’ll send the file.\n\n"
        "Need help? Contact @ogabek1106"
    )

# ✅ Message handler for codes or text
async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.strip()
    logger.info(f"Received message: {msg}")

    if msg.isdigit():
        if msg in BOOKS:
            book = BOOKS[msg]
            await update.message.reply_document(
                document=book["file_id"],
                filename=book["filename"],
                caption=book["caption"],
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("🚫 Book not found.")
    else:
        await update.message.reply_text("Huh? 🤔")

# ✅ Run bot
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))

logger.info("Bot started.")
app.run_polling()
