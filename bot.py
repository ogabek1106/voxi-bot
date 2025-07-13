import os
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# 🔐 Bot Token from environment
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ✅ Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 📚 Book data
BOOKS = {
    "1": {
        "file_id": "BQACAgIAAyEFAAShxLgyAAMHaHOY0YvtH2OCcLR0ZAxKbt9JIGIAAtp_AALlEZhLhfS_vbLV6oY2BA",
        "filename": "400 Must-Have Words for the TOEFL.pdf",
        "caption": "\ud83d\udcd8 *400 Must-Have Words for the TOEFL*\n\n\u23f0 File will delete in 15 minutes.\n\nMore \ud83d\udc49 @IELTSforeverybody"
    },
    # Add more if needed
}

# 📁 User stats persistence
USERS_FILE = "users.txt"

def get_user_ids():
    try:
        with open(USERS_FILE, "r") as f:
            return set(map(int, f.read().splitlines()))
    except FileNotFoundError:
        return set()

def save_user_id(user_id):
    user_ids = get_user_ids()
    if user_id not in user_ids:
        with open(USERS_FILE, "a") as f:
            f.write(str(user_id) + "\n")

# ✅ /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user_id(update.effective_user.id)
    await update.message.reply_text(
        "\ud83e\udd8a Welcome to Voxi Bot!\n\n"
        "Send me a book code (like 1, 2, etc.) and I\u2019ll send the file.\n\n"
        "Need help? Contact @ogabek1106"
    )

# ✅ /stats command
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_ids = get_user_ids()
    await update.message.reply_text(f"\ud83d\udcca Total users: {len(user_ids)}")

# ✅ Handle messages
async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.strip()
    user_id = update.effective_user.id
    save_user_id(user_id)

    if msg.isdigit():
        if msg in BOOKS:
            book = BOOKS[msg]
            sent_msg = await update.message.reply_document(
                document=book["file_id"],
                filename=book["filename"],
                caption=book["caption"],
                parse_mode="Markdown"
            )
            # ⏳ Delete after 15 minutes (900 sec)
            context.job_queue.run_once(
                lambda ctx: ctx.bot.delete_message(chat_id=sent_msg.chat_id, message_id=sent_msg.message_id),
                when=900
            )
        else:
            await update.message.reply_text("\ud83d\udeab Book not found.")
    else:
        await update.message.reply_text("Huh?\ud83e\udd14")

# ✅ Start bot
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))

logger.info("Bot started.")
app.run_polling()
