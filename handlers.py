# handlers.py

import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters

from config import ADMIN_IDS, USER_FILE, STORAGE_CHANNEL_ID
from books import BOOKS
from user_data import load_users, add_user, increment_book_count, load_stats
from utils import delete_after_delay, countdown_timer
from ratings import add_rating, has_rated, get_average_rating

logger = logging.getLogger(__name__)
user_ids = load_users()

# ✅ /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global user_ids
    user_id = update.effective_user.id
    if user_ids is None:
        await update.message.reply_text("♻️ user_ids.json not found.")
        return
    add_user(user_ids, user_id)

    arg = context.args[0] if context.args else None
    if arg and arg in BOOKS:
        await handle_code(update, context, override_code=arg)
    else:
        await update.message.reply_text(
            "🦧 Welcome to Voxi Bot!\n\n"
            "Send me a number (1, 2, etc.) and I’ll send you the file.\n\n"
            "Need help? Contact @ogabek1106"
        )

# ✅ /stats command
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in ADMIN_IDS:
        total_users = len(user_ids) if user_ids else 0
        await update.message.reply_text(f"📊 Total users: {total_users}")
    else:
        await update.message.reply_text("Darling, you are not an admin🤪")

# ✅ /all_books command
async def all_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not BOOKS:
        await update.message.reply_text("😕 No books are currently available.")
        return
    message = "📚 *Available Books:*\n\n"
    for code, data in BOOKS.items():
        title_line = data["caption"].split('\n')[0]
        message += f"{code}. {title_line}\n"
    await update.message.reply_text(message, parse_mode="Markdown")

# ✅ Book stats (rating counts)
async def book_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You’re not allowed to see the stats 😎")
        return

    stats = load_stats()
    if not stats:
        await update.message.reply_text("📉 No book requests have been recorded yet.")
        return

    message = "📊 *Book Request Stats:*\n\n"
    for code, count in stats.items():
        book = BOOKS.get(code)
        if book:
            title = book['caption'].splitlines()[0]
            message += f"{code}. {title} — {count} requests\n"

    await update.message.reply_text(message, parse_mode="Markdown")

# ✅ Handle book download
async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE, override_code=None):
    user_id = update.effective_user.id
    if user_ids is None:
        await update.message.reply_text("♻️ user_ids.json not found.")
        return

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

        # Rating buttons
        rating_buttons = [
            InlineKeyboardButton(f"{i}⭐️", callback_data=f"rate|{msg}|{i}")
            for i in range(1, 6)
        ]
        reply_markup = InlineKeyboardMarkup([rating_buttons])

        await update.message.reply_text(
            "⭐️ Rate this book:", reply_markup=reply_markup
        )

        countdown_msg = await update.message.reply_text("⏳ [██████████] 15:00 remaining")
        print(f"⏳ Countdown started for user {user_id}")

        await asyncio.create_task(
            countdown_timer(
                context.bot,
                countdown_msg.chat.id,
                countdown_msg.message_id,
                900,
                final_text=f"♻️ File was deleted for your privacy.\nTo see it again, type `{msg}`.",
            )
        )

        await asyncio.create_task(
            delete_after_delay(context.bot, sent.chat.id, sent.message_id, 900)
        )

    elif msg.isdigit():
        await update.message.reply_text("❌ Book not found.")
    else:
        await update.message.reply_text("Huh?🤔")

# ✅ Save PDFs to storage channel
async def save_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    doc = update.message.document
    if doc:
        file_id = doc.file_id
        file_name = doc.file_name or "Untitled.pdf"
        await context.bot.send_document(
            chat_id=STORAGE_CHANNEL_ID,
            document=file_id,
            caption=f"📚 *{file_name}*",
            parse_mode="Markdown"
        )
        await update.message.reply_text(f"`{file_id}`", parse_mode="Markdown")

# ✅ Broadcast new book
async def broadcast_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if user_ids is None:
        await update.message.reply_text("♻️ user_ids.json not found.")
        return
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

# ✅ Handle star rating
async def handle_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Feedback sent!", show_alert=False)

    try:
        _, book_code, score = query.data.split("|")
        user_id = query.from_user.id
        score = int(score)
    except:
        return

    if has_rated(book_code, user_id):
        return  # Already rated

    add_rating(book_code, user_id, score)
    avg, total = get_average_rating(book_code)

    await query.edit_message_text(
        f"✅ Thanks for rating!\n⭐️ Average rating: {avg} ({total} votes)"
    )

# ✅ Register all handlers
def register_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("all_books", all_books))
    app.add_handler(CommandHandler("broadcast_new", broadcast_new))
    app.add_handler(CommandHandler("book_stats", book_stats))
    app.add_handler(CallbackQueryHandler(handle_rating, pattern=r"^rate\|"))
    app.add_handler(MessageHandler(filters.Document.PDF, save_pdf))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))
