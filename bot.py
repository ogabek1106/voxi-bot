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

# 🔐 Environment
BOT_TOKEN = os.getenv("BOT_TOKEN")
USERS_FILE = "users.txt"

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
    },
    "2": {
        "file_path": "books/print (58).pdf",
        "file_name": "test2",
        "caption": (
            "📘 *test2\n\n"
            "⏰ File will be deleted after 15 minutes, so make sure that you've downloaded it.\n\n"
            "📚 For more -> @IELTSforeverybody"
        )
    }
}

# ✅ Save user ID to file
def save_user(user_id: int):
    try:
        if not os.path.exists(USERS_FILE):
            with open(USERS_FILE, "w") as f:
                f.write(f"{user_id}\n")
        else:
            with open(USERS_FILE, "r") as f:
                users = f.read().splitlines()
            if str(user_id) not in users:
                with open(USERS_FILE, "a") as f:
                    f.write(f"{user_id}\n")
    except Exception as e:
        logger.error(f"Failed to save user: {e}")

# ✅ Get total number of users
def get_user_count() -> int:
    if not os.path.exists(USERS_FILE):
        return 0
    with open(USERS_FILE, "r") as f:
        return len(f.read().splitlines())

# ✅ /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user.id)
    args = context.args

    # If user sends something like /start 1
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

    # Normal /start
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

# ✅ Handle messages
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message.text.strip()
    save_user(user.id)

    # If numeric code
    if msg.isdigit():
        if msg in BOOKS:
            book = BOOKS[msg]
            if os.path.exists(book["file_path"]):
                logger.info(f"Book code '{msg}' → sending to {user.id}")
                with open(book["file_path"], "rb") as f:
                    await update.message.reply_document(
                        document=f,
                        filename=book["file_name"],
                        caption=book["caption"],
                        parse_mode="Markdown"
                    )
                return
        await update.message.reply_text("🚫 Book not found.")
        return

    # If random unrecognized text
    await update.message.reply_text("Huh? 🤔")

# ✅ /stats command
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = get_user_count()
    await update.message.reply_text(f"📊 Total unique users: {count}")

# ✅ Set up the bot
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

logger.info("Starting polling...")
app.run_polling()
