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

# 🔐 Load bot token
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ✅ /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args  # e.g., ['1']

    if args and args[0] == "1":
        file_path = "books/1.pdf"
        file_name = "@ieltsforeverybody_400_must_have_words_for_the_TOEFL_MGH_2005.pdf"
        caption = (
            "📘 *400 Must-Have Words for the TOEFL* (McGraw-Hill, 2005)\n\n"
            "⏰ File will be deleted after 15 minutes, so make sure that you've downloaded it.\n\n"
            "📚 For more -> @IELTSforeverybody"
        )

        if os.path.exists(file_path):
            logger.info(f"Sending book '1.pdf' to user {user.id}")
            with open(file_path, "rb") as book:
                await update.message.reply_document(
                    document=book,
                    filename=file_name,
                    caption=caption,
                    parse_mode="Markdown"
                )
        else:
            await update.message.reply_text("🚫 Book not found.")
        return

    logger.info(f"/start from {user.id}")
    await update.message.reply_text("I hear you 👂")

# ✅ Echo other text
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"Text from {user.id}: {update.message.text}")
    await update.message.reply_text("📩 I received your message!")

# ✅ Set up app
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

logger.info("Starting polling...")
app.run_polling()
