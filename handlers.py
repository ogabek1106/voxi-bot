# handlers.py

import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from config import ADMIN_IDS, USER_FILE, STORAGE_CHANNEL_ID
from books import BOOKS
from user_data import (
    load_users, add_user,
    increment_book_count, load_stats,
    has_rated, save_rating, load_rating_stats
)
from utils import delete_after_delay, countdown_timer

logger = logging.getLogger(__name__)

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

# ------------------ Main handler ------------------
async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE, override_code=None):
    user_id = update.effective_user.id
    user_ids = load_users()
    add_user(user_ids, user_id)

    msg = override_code or update.message.text.strip()

    if msg in BOOKS:
        book = BOOKS[msg]
        increment_book_count(msg)

        sent = await update.message.reply_document(
            document=book["file_id"],
            filename=book["filename"],
            caption=book["caption"],
            parse_mode="Markdown"
        )

        if not has_rated(str(user_id), msg):
            rating_buttons = [
                [InlineKeyboardButton(f"{i}⭐️", callback_data=f"rate|{msg}|{i}")]
                for i in range(1, 6)
            ]
            rating_msg = await update.message.reply_text(
                "How would you rate this book? 🤔",
                reply_markup=InlineKeyboardMarkup(rating_buttons)
            )
        else:
            rating_msg = None

        countdown_msg = await update.message.reply_text("⏳ [██████████] 10:00 remaining")
        print(f"⏳ Countdown started for user {user_id}")

        asyncio.create_task(
            countdown_timer(
                context.bot,
                countdown_msg.chat.id,
                countdown_msg.message_id,
                600,
                final_text=f"♻️ File was deleted for your privacy.\nTo see it again, type `{msg}`."
            )
        )

        asyncio.create_task(delete_after_delay(context.bot, sent.chat.id, sent.message_id, 600))
        asyncio.create_task(delete_after_delay(context.bot, countdown_msg.chat.id, countdown_msg.message_id, 600))

        if rating_msg:
            asyncio.create_task(delete_after_delay(context.bot, rating_msg.chat.id, rating_msg.message_id, 600))

    elif msg.isdigit():
        await update.message.reply_text("❌ Book not found.")
    else:
        await update.message.reply_text("Huh? 🤔")

# ------------------ Save PDF ------------------
async def save_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    doc = update.message.document
    if not doc:
        await update.message.reply_text("❌ No document found.")
        return

    try:
        # Forward to storage channel
        sent = await context.bot.send_document(
            chat_id=STORAGE_CHANNEL_ID,
            document=doc.file_id,
            caption=f"📚 *{doc.file_name or 'Untitled'}*",
            parse_mode="Markdown"
        )

        file_id = doc.file_id
        message_id = sent.message_id

        await update.message.reply_text(
            f"✅ Saved to storage!\n\n"
            f"`file_id`: `{file_id}`\n"
            f"`message_id`: `{message_id}`",
            parse_mode="Markdown"
        )

    except Exception as e:
        await update.message.reply_text(f"⚠️ Failed to save PDF: {e}")

# ------------------ Callback for ratings ------------------
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
        print(f"[rating_callback ERROR] {e}")

# ------------------ Register Handlers ------------------
def register_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("all_books", all_books))
    app.add_handler(CommandHandler("book_stats", book_stats))
    app.add_handler(CommandHandler("broadcast_new", broadcast_new))
    app.add_handler(MessageHandler(filters.Document.PDF, save_pdf))
    app.add_handler(CallbackQueryHandler(rating_callback, pattern=r"^rate\|"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))
