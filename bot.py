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

# ✅ Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🔐 Bot token from Railway
BOT_TOKEN = os.getenv("BOT_TOKEN")

# 📘 Available books
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
    args = context.args

    # 🎯 If a code is provided (e.g., /start 1)
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

    # 👋 Welcome message if no code is given
    first_name = user.first_name or "there"
    welcome = (
        f"👋 Hi, {first_name}!\n\n"
        "🦊 I’m *Voxi*, your AI assistant.\n"
        "Send me the code of an e-book and I’ll deliver it instantly.\n\n"
        "⏳ Files will self-destruct in 15 minutes for your privacy.\n\n"
        "Need help? Type /help or contact [Ogabek](https://t.me/ogabek1106) 😉"
    )
    logger.info(f"/start (no args) from {user.id}")
    await update.message.reply_text(welcome, parse_mode="Markdown")

# ✅ Echo text messages
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

# ✅ Initialize bot
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

logger.info("Starting polling...")
app.run_polling()
