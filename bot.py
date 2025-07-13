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

# 🔐 Bot Token
BOT_TOKEN = os.getenv("BOT_TOKEN")

# 📁 User data file
USERS_FILE = "users.txt"

# 📚 Book data
BOOKS = {
    "1": {
        "file_id": "BQACAgIAAyEFAAShxLgyAAMHaHOY0YvtH2OCcLR0ZAxKbt9JIGIAAtp_AALlEZhLhfS_vbLV6oY2BA",
        "filename": "400 Must-Have Words for the TOEFL.pdf",
        "caption": "📘 *400 Must-Have Words for the TOEFL*\n\n⏰ File will delete in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
    },
    # Add more if needed
}

# ✅ Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ✅ Save user ID
def save_user(user_id: int):
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w") as f:
            f.write(f"{user_id}\n")
    else:
        with open(USERS_FILE, "r") as f:
            users = f.read().splitlines()
        if str(user_id) not in users:
            with open(USERS_FILE, "a") as f:
                f.write(f"{user_id}\n")

# ✅ Get user count
def get_user_count() -> int:
    if not os.path.exists(USERS_FILE):
        return 0
    with open(USERS_FILE, "r") as f:
        return len(f.read().splitlines())

# ✅ /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_user(user_id)

    args = context.args
    if args and args[0] in BOOKS:
        book = BOOKS[args[0]]
        await update.message.reply_document(
            document=book["file_id"],
            caption=book["caption"],
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        "🦊 Welcome to Voxi Bot!\n\n"
        "Send me a book code (like 1, 2, etc.) and I’ll send the file.\n\n"
        "Need help? Contact @ogabek1106"
    )

# ✅ Handle codes & unknown messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_user(user_id)

    msg = update.message.text.strip()

    if msg.isdigit():
        if msg in BOOKS:
            book = BOOKS[msg]
            await update.message.reply_document(
                document=book["file_id"],
                caption=book["caption"],
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("🚫 Book not found.")
    else:
        await update.message.reply_text("Huh? 🤔")

# ✅ /stats command
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = get_user_count()
    await update.message.reply_text(f"📊 Total unique users: {count}")

# ✅ Start app
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

logger.info("Bot started.")
app.run_polling()
