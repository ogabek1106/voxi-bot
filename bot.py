import os
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)

# ✅ Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🔐 Load bot token from Railway env
BOT_TOKEN = os.getenv("BOT_TOKEN")

# 📘 Book info
BOOKS = {
    "1": {
        "file_path": "books/1.pdf",
        "file_name": "@ieltsforeverybody_400_must_have_words_for_the_TOEFL_MGH_2005.pdf",
        "caption": (
            "📘 *400 Must-Have Words for the TOEFL* (McGraw-Hill, 2005)\n\n"
            "⏰ File will be deleted after 15 minutes, so make sure that you've downloaded it.\n\n"
            "📚 For more -> @IELTSforeverybody"
        )
    }
}

# ✅ /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args  # e.g., ['1']

    if args and args[0] in BOOKS:
        book = BOOKS[args[0]]
        if os.path.exists(book["file_path"]):
            logger.info(f"/start {args[0]} → sending to {user.id}")
            with open(book["file_path"], "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename=book["file_name"],
                    caption=book["caption"],
                    parse_mode="Markdown"
                )
        else:
            await update.message.reply_text("🚫 Book not found.")
        return

    logger.info(f"/start (no args) from {user.id}")
    await update.message.reply_text("I hear you 👂")

# ✅ Text message handler
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message.text.strip()

    if msg in BOOKS:
        book = BOOKS[msg]
        if os.path.exists(book["file_path"]):
            logger.info(f"Echo '{msg}' → sending to {user.id}")
            with open(book["file_path"], "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename=book["file_name"],
                    caption=book["caption"],
                    parse_mode="Markdown"
                )
        else:
            await update.message.reply_text("🚫 Book not found.")
        return

    logger.info(f"Text from {user.id}: {msg}")
    await update.message.reply_text("📩 I received your message!")

# ✅ Set up and run the bot (polling)
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

logger.info("Starting polling...")
app.run_polling()
