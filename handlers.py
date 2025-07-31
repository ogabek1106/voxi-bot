# handlers.py

import asyncio
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from books import BOOKS
from config import ADMIN_IDS
from user_data import (
    load_users,
    add_user,
    increment_book_count,
    load_stats,
    save_rating,
    has_rated,
)
from utils import countdown_timer, delete_after_delay


# ------------------ REGISTER HANDLERS ------------------
def register_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("book_stats", book_stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))
    app.add_handler(CallbackQueryHandler(rate_book_callback, pattern=r"^rate_"))


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
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    user_count = len(load_users())
    await update.message.reply_text(f"👥 Total Users: {user_count}")


# ------------------ /book_stats ------------------
async def book_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return

    stats = load_stats()
    if not stats:
        await update.message.reply_text("📊 No book stats yet.")
        return

    message = "📚 Book Request Stats:\n\n"
    for code, count in stats.items():
        book = BOOKS.get(code, {})
        name = book.get("filename", "Unknown")
        message += f"🔢 Code {code} — {count} requests\n📘 {name}\n\n"
    await update.message.reply_text(message.strip())


# ------------------ Handle Book Request ------------------
async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    if code not in BOOKS:
        await update.message.reply_text("❌ Book not found. Try a valid code.")
        return

    user_id = update.effective_user.id
    increment_book_count(code)

    book = BOOKS[code]
    file_id = book["file_id"]
    caption = book["caption"]

    sent = await update.message.reply_document(
        file_id,
        caption=caption,
        parse_mode="Markdown"
    )

    # Rating buttons
    rating_buttons = [
        [InlineKeyboardButton(f"{i} ⭐️", callback_data=f"rate_{code}_{i}") for i in range(1, 6)]
    ]
    await update.message.reply_text(
        "⭐️ Rate this book:",
        reply_markup=InlineKeyboardMarkup(rating_buttons)
    )

    # Countdown message
    countdown_msg = await update.message.reply_text("⏳ [██████████] 15:00 remaining")

    # Start timer in background
    asyncio.create_task(
        countdown_timer(
            context.bot,
            countdown_msg.chat.id,
            countdown_msg.message_id,
            900,
            final_text="❌ This file was deleted for your privacy."
        )
    )

    # Auto delete file after 15 mins
    asyncio.create_task(
        delete_after_delay(
            context.bot,
            sent.chat.id,
            sent.message_id,
            900
        )
    )


# ------------------ Handle Rating ------------------
async def rate_book_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    data = query.data  # format: rate_{code}_{rating}
    _, code, rating = data.split("_")

    if has_rated(user_id, code):
        await query.answer("You've already rated this book!", show_alert=True)
        return

    save_rating(user_id, code, int(rating))
    await query.answer("✅ Feedback sent!", show_alert=False)
