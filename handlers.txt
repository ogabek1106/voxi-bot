import asyncio
import json
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters
)

from config import ADMIN_IDS, USER_FILE, STORAGE_CHANNEL_ID
from books import BOOKS, BOOKS_FILE
from user_data import (
    load_users, add_user,
    increment_book_count, load_stats,
    has_rated, save_rating, load_rating_stats
)
from utils import delete_after_delay, countdown_timer

logger = logging.getLogger(__name__)

upload_state = {}

# ------------------ /start ------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_ids = load_users()
    is_new = add_user(user_ids, user_id)

    arg = context.args[0] if context.args else None
    if arg and arg in BOOKS:
        await handle_code(update, context, override_code=arg)
        return

    if is_new:
        await update.message.reply_text("🦧 Welcome to Voxi Bot!\n\nSend a code like 1, 2, 3...")
    else:
        await update.message.reply_text("📚 You're already in!\nSend a book code to get started.")

# ------------------ /stats ------------------
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in ADMIN_IDS:
        total_users = len(load_users())
        await update.message.reply_text(f"📊 Total users: {total_users}")
    else:
        await update.message.reply_text("Darling, you are not an admin 🤪")

# ------------------ /all_books ------------------
async def all_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not BOOKS:
        await update.message.reply_text("😕 No books are currently available.")
        return
    message = "📚 *Available Books:*\n\n"
    for code, data in BOOKS.items():
        title_line = data["caption"].split('\n')[0]
        message += f"{code}. {title_line}\n"
    await update.message.reply_text(message, parse_mode="Markdown")

# ------------------ /book_stats ------------------
async def book_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You’re not allowed to see the stats 😎")
        return

    stats = load_stats()
    ratings = load_rating_stats()

    if not stats:
        await update.message.reply_text("📉 No book requests have been recorded yet.")
        return

    message = "📊 *Book Stats:*\n\n"
    for code, count in stats.items():
        book = BOOKS.get(code)
        if book:
            title = book['caption'].splitlines()[0]
            rating_info = ""
            if code in ratings:
                votes = ratings[code]
                total_votes = sum(votes[str(i)] for i in range(1, 6))
                avg = sum(int(star) * votes[str(star)] for star in votes) / total_votes if total_votes > 0 else 0
                rating_info = f" — ⭐️ {avg:.1f}/5 ({total_votes} votes)"
            message += f"{code}. {title} — {count} requests{rating_info}\n"

    await update.message.reply_text(message, parse_mode="Markdown")

# ------------------ /broadcast_new ------------------
async def broadcast_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    user_ids = load_users()
    if not context.args:
        await update.message.reply_text("❗ Usage: /broadcast_new <book_code>")
        return

    code = context.args[0]
    if code not in BOOKS:
        await update.message.reply_text("❌ No such book code.")
        return

    book = BOOKS[code]
    msg = (
        f"📚 *New Book Uploaded!*\n\n"
        f"{book['caption'].splitlines()[0]}\n"
        f"🆔 Code: `{code}`\n\n"
        f"Send this number to get the file!"
    )

    success, fail = 0, 0
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
            success += 1
        except Exception as e:
            fail += 1
            logger.warning(f"Couldn't message {uid}: {e}")
    await update.message.reply_text(f"✅ Sent to {success} users.\n❌ Failed for {fail}.")

# ------------------ Handle all messages ------------------
async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE, override_code=None):
    print(f"📩 Received message: {update.message.text if update.message else update}")

    user_id = update.effective_user.id
    user_ids = load_users()
    add_user(user_ids, user_id)
    msg = override_code or update.message.text.strip()

    if user_id in upload_state:
        state = upload_state[user_id]

        if "name" not in state:
            upload_state[user_id]["name"] = msg
            await update.message.reply_text("🔢 Now send the *code* (number) for this book", parse_mode=ParseMode.MARKDOWN)
            return

        if "code" not in state:
            if not msg.isdigit():
                await update.message.reply_text("❌ Code must be a number.")
                return
            if msg in BOOKS:
                await update.message.reply_text("⚠️ This code already exists. Choose a different one.")
                return

            name = state["name"]
            file_id = state["file_id"]
            filename = state["filename"]
            caption = f"👘 *{name}*\n\n⏰ File will be deleted in 15 minutes.\n\nMore 👉 @IELTSforeverybody"
            BOOKS[msg] = {
                "file_id": file_id,
                "filename": filename,
                "caption": caption
            }
            with open(BOOKS_FILE, "w", encoding="utf-8") as f:
                json.dump(BOOKS, f, indent=4, ensure_ascii=False)

            upload_state.pop(user_id)
            await update.message.reply_text("✅ Uploaded successfully and saved to BOOKS.")
            return

    if msg in BOOKS:
        book = BOOKS[msg]
        increment_book_count(msg)

        sent = await update.message.reply_document(
            document=book["file_id"],
            filename=book["filename"],
            caption=book["caption"],
            parse_mode="Markdown"
        )

        rating_msg = None
        if not has_rated(str(user_id), msg):
            rating_buttons = [
                [InlineKeyboardButton(f"{i}⭐️", callback_data=f"rate|{msg}|{i}")]
                for i in range(1, 6)
            ]
            rating_msg = await update.message.reply_text(
                "How would you rate this book? 🤔",
                reply_markup=InlineKeyboardMarkup(rating_buttons)
            )

        countdown_msg = await update.message.reply_text("⏳ [██████████] 10:00 remaining")
        asyncio.create_task(countdown_timer(
            context.bot,
            countdown_msg.chat.id,
            countdown_msg.message_id,
            600,
            final_text=f"♻️ File was deleted for your privacy.\nTo see it again, type `{msg}`."
        ))
        asyncio.create_task(delete_after_delay(context.bot, sent.chat.id, sent.message_id, 600))
        asyncio.create_task(delete_after_delay(context.bot, countdown_msg.chat.id, countdown_msg.message_id, 600))
        if rating_msg:
            asyncio.create_task(delete_after_delay(context.bot, rating_msg.chat.id, rating_msg.message_id, 600))

    elif msg.isdigit():
        await update.message.reply_text("❌ Book not found.")
    else:
        await update.message.reply_text("Huh? 🤔")

# ------------------ Handle PDF uploads ------------------
async def handle_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return

    doc = update.message.document
    if not doc or not doc.file_name.endswith(".pdf"):
        await update.message.reply_text("❌ Please send a valid PDF file.")
        return

    forwarded = await context.bot.send_document(
        chat_id=STORAGE_CHANNEL_ID,
        document=doc.file_id,
        caption=f"📚 *{doc.file_name}*",
        parse_mode=ParseMode.MARKDOWN
    )

    upload_state[user_id] = {
        "file_id": doc.file_id,
        "filename": doc.file_name,
        "message_id": forwarded.message_id
    }

    await update.message.reply_text("📖 Please enter the *name of the book*", parse_mode=ParseMode.MARKDOWN)

# ------------------ Handle Rating ------------------
async def rating_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer("Feedback sent!", show_alert=False)
        data = query.data.split("|")
        if len(data) != 3:
            return

        _, book_code, rating = data
        user_id = str(query.from_user.id)

        if not has_rated(user_id, book_code):
            save_rating(user_id, book_code, int(rating))
            await query.edit_message_text("✅ Thanks for your rating!")
        else:
            await query.edit_message_text("📌 You've already rated this book.")
    except Exception as e:
        logger.error(f"[rating_callback ERROR] {e}")

# ------------------ Global Error Handler ------------------
import traceback

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    error_text = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
    logger.error(f"❌ Exception caught:\n{error_text}")

    try:
        await context.bot.send_message(
            chat_id=list(ADMIN_IDS)[0],
            text=f"🚨 *Exception in bot:*\n```{error_text[-4000:]}```",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning(f"⚠️ Failed to notify admin: {e}")

# ------------------ Register Handlers ------------------
def register_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("all_books", all_books))
    app.add_handler(CommandHandler("book_stats", book_stats))
    app.add_handler(CommandHandler("broadcast_new", broadcast_new))

    app.add_handler(MessageHandler(filters.Document.PDF, handle_upload))
    app.add_handler(CallbackQueryHandler(rating_callback, pattern=r"^rate\|"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))

    app.add_error_handler(error_handler)

    # ✅ Echo test
    async def echo_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("✅ Bot is alive and received your message.")

    app.add_handler(MessageHandler(filters.TEXT, echo_test))

