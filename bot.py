import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# ✅ Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🔐 Your bot token
BOT_TOKEN = os.getenv("BOT_TOKEN")

# 📦 Replace these with actual file_ids from your private "storage" channel
BOOKS = {
    "1": {
        "file_id": "YOUR_FILE_ID_1",
        "caption": "📘 *400 Must-Have Words for the TOEFL*\n\n⏰ File will self-delete in 15 min.\nMore 👉 @IELTSforeverybody"
    },
    "2": {
        "file_id": "YOUR_FILE_ID_2",
        "caption": "📘 *test2*\n\n⏰ File will self-delete in 15 min.\nMore 👉 @IELTSforeverybody"
    }
}

# ✅ /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    if args and args[0] in BOOKS:
        book = BOOKS[args[0]]
        logger.info(f"/start {args[0]} from {user.id}")
        await update.message.reply_document(
            document=book["file_id"],
            caption=book["caption"],
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        f"👋 Hi {user.first_name or 'friend'}!\nSend me the book code (like `1`) and I’ll send you the file.",
        parse_mode="Markdown"
    )

# ✅ Code input
async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    user = update.effective_user

    if code in BOOKS:
        book = BOOKS[code]
        logger.info(f"Code {code} from {user.id}")
        await update.message.reply_document(
            document=book["file_id"],
            caption=book["caption"],
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("🚫 Book not found.")

# ✅ Bot app
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))

logger.info("Bot is running...")
app.run_polling()
