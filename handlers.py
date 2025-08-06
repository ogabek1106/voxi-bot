import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters
)
from config import ADMIN_IDS
from books import BOOKS
from database import (
    add_user_if_not_exists, get_user_count,
    increment_book_request, get_book_stats,
    has_rated, save_rating, get_rating_stats,
    save_countdown, get_remaining_countdown
)
from utils import delete_after_delay, countdown_timer

logger = logging.getLogger(__name__)

# ------------------ /start ------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    add_user_if_not_exists(user_id)

    arg = context.args[0] if context.args else None
    if arg and arg in BOOKS:
        await handle_code(update, context, override_code=arg)
        return

    await update.message.reply_text("🦧 Welcome to Voxi Bot!\n\nSend a code like 1, 2, 3...")

# ------------------ /stats ------------------
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in ADMIN_IDS:
        total_users = get_user_count()
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

    stats = get_book_stats()
    ratings = get_rating_stats()

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
                total_votes = sum(votes[i] for i in range(1, 6))
                avg = sum(i * votes[i] for i in range(1, 6)) / total_votes if total_votes > 0 else 0
                rating_info = f" — ⭐️ {avg:.1f}/5 ({total_votes} votes)"
            message += f"{code}. {title} — {count} requests{rating_info}\n"

    await update.message.reply_text(message, parse_mode="Markdown")

# ------------------ /asd (admin help) ------------------
async def admin_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You don’t have access to this command.")
        return

    help_text = (
        "🛠 <b>Admin Commands Help</b>\n\n"
        "<code>/stats</code> — Show total user count\n"
        "<code>/all_books</code> — List all available books with their codes\n"
        "<code>/book_stats</code> — View book download counts and ratings\n"
        "<code>/broadcast_new &lt;code&gt;</code> — Broadcast a newly added book to all users\n"
        "<code>/asd</code> — Show this help message\n\n"
        "📤 <b>To upload a book:</b>\n"
        "Just send a PDF and the bot will reply with file info.\n"
        "You can later manually add it to <code>BOOKS</code> using code and name."
    )
    await update.message.reply_text(help_text, parse_mode="HTML")

# ------------------ Handle Document Uploads ------------------
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ You can't upload files.")
        return

    if not update.message.document:
        await update.message.reply_text("❗ Please send a PDF file.")
        return

    file = update.message.document
    if file.mime_type != "application/pdf":
        await update.message.reply_text("❗ Only PDF files are supported.")
        return

    # ✅ Forward to storage channel
    forwarded = await update.message.forward(chat_id=-1002714023986)

    # ℹ️ Reply with file_id and message_id for t.me/c/ link
    file_id = file.file_id
    msg_id = forwarded.message_id
    await update.message.reply_text(
        f"✅ File forwarded.\n\n"
        f"<b>file_id</b>:\n<code>{file_id}</code>\n\n"
        f"<b>message_id</b>: <code>{msg_id}</code>",
        parse_mode="HTML"
    )

# ------------------ Handle all messages ------------------
async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE, override_code=None):
    user_id = update.effective_user.id
    add_user_if_not_exists(user_id)
    msg = override_code or update.message.text.strip()

    if msg in BOOKS:
        book = BOOKS[msg]
        increment_book_request(msg)

        sent = await update.message.reply_document(
            document=book["file_id"],
            filename=book["filename"],
            caption=book["caption"],
            parse_mode="Markdown"
        )

        rating_msg = None
        if not has_rated(user_id, msg):
            rating_buttons = [
                [InlineKeyboardButton(f"{i}⭐️", callback_data=f"rate|{msg}|{i}")]
                for i in range(1, 6)
            ]
            rating_msg = await update.message.reply_text(
                "How would you rate this book? 🤔",
                reply_markup=InlineKeyboardMarkup(rating_buttons)
            )

        remaining = get_remaining_countdown(user_id, msg)
        if remaining == 0:
            remaining = 600
            save_countdown(user_id, msg, remaining)

        countdown_msg = await update.message.reply_text(f"⏳ [██████████] {remaining // 60:02}:{remaining % 60:02} remaining")
        asyncio.create_task(countdown_timer(
            context.bot,
            countdown_msg.chat.id,
            countdown_msg.message_id,
            remaining,
            final_text=f"♻️ File was deleted for your privacy.\nTo see it again, type `{msg}`."
        ))
        asyncio.create_task(delete_after_delay(context.bot, sent.chat.id, sent.message_id, remaining))
        asyncio.create_task(delete_after_delay(context.bot, countdown_msg.chat.id, countdown_msg.message_id, remaining))
        if rating_msg:
            asyncio.create_task(delete_after_delay(context.bot, rating_msg.chat.id, rating_msg.message_id, remaining))
    elif msg.isdigit():
        await update.message.reply_text("❌ Book not found.")
    else:
        await update.message.reply_text("Huh? 🤔")

# ------------------ Rating Callback ------------------
async def rating_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer("Feedback sent!", show_alert=False)
        data = query.data.split("|")
        if len(data) != 3:
            return
        _, book_code, rating = data
        user_id = query.from_user.id
        if not has_rated(user_id, book_code):
            save_rating(user_id, book_code, int(rating))
            await query.edit_message_text("✅ Thanks for your rating!")
        else:
            await query.edit_message_text("📌 You've already rated this book.")
    except Exception as e:
        logger.error(f"[rating_callback ERROR] {e}")

# ------------------ Register ------------------
def register_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("asd", admin_commands))
    app.add_handler(CommandHandler("all_books", all_books))
    app.add_handler(CommandHandler("book_stats", book_stats))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))
    app.add_handler(CallbackQueryHandler(rating_callback, pattern=r"^rate\|"))
