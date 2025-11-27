# handlers.py — minimal handlers for Voxi bot
import asyncio
import logging
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from config import ADMIN_IDS
from books import BOOKS
from database import (
    add_user_if_not_exists,
    get_user_count,
    increment_book_request,
    get_book_stats,
    has_rated,
    save_rating,
    get_rating_stats,
)

logger = logging.getLogger(__name__)

# ----------------- Safe wrapper -----------------
def safe_handler(fn):
    if not asyncio.iscoroutinefunction(fn):
        raise ValueError("safe_handler expects an async function")

    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            return await fn(update, context)
        except Exception as e:
            logger.exception("Handler %s failed: %s", fn.__name__, e)
            try:
                if update and getattr(update, "effective_message", None):
                    await update.effective_message.reply_text("⚠️ Internal error. Admins notified.")
            except Exception:
                logger.exception("Failed to send error message to user")
    return wrapper

# ----------------- Track every user -----------------
@safe_handler
async def track_every_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    try:
        add_user_if_not_exists(user.id)
    except Exception:
        logger.exception("Failed to add user %s", user.id)

# ----------------- /start -----------------
@safe_handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if user:
        try:
            add_user_if_not_exists(user.id)
        except Exception:
            logger.exception("add_user_if_not_exists failed for %s", user.id)

    text = (
        "Assalomu alaykum 👋\n\n"
        "Welcome to the Voxi bot.\n\n"
        "• Send a book code (example: `1`) to receive the file.\n"
        "• If you are an admin, use /stats and /book_stats.\n\n"
        "Enjoy!"
    )
    await msg.reply_text(text, parse_mode=None)

# ----------------- /stats (admin only) -----------------
@safe_handler
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not an admin.")
        return
    total = get_user_count()
    await update.message.reply_text(f"📊 Total users: {total}")

# ----------------- /book_stats (admin only) -----------------
@safe_handler
async def book_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not an admin.")
        return

    stats = get_book_stats()
    ratings = get_rating_stats()

    if not stats:
        await update.message.reply_text("📉 No book requests recorded yet.")
        return

    lines = ["📊 Book stats:\n"]
    for code, count in sorted(stats.items(), key=lambda x: int(x[0]) if x[0].isdigit() else x[0]):
        title = BOOKS.get(code, {}).get("caption", "").splitlines()[0] if BOOKS.get(code) else f"Code {code}"
        rating_info = ""
        if code in ratings:
            votes = ratings[code]
            total_votes = sum(votes.get(i, 0) for i in range(1, 6))
            if total_votes:
                avg = sum(i * votes.get(i, 0) for i in range(1, 6)) / total_votes
                rating_info = f" — ⭐ {avg:.1f}/5 ({total_votes} votes)"
        lines.append(f"{code}. {title} — {count} requests{rating_info}")

    await update.message.reply_text("\n".join(lines))

# ----------------- Handle text messages as book codes -----------------
@safe_handler
async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    user = update.effective_user
    user_id = user.id if user else None
    text = msg.text.strip()

    # If user sent a numeric code that matches a book
    if text.isdigit() and text in BOOKS:
        code = text
        book = BOOKS[code]
        try:
            increment_book_request(code)
        except Exception:
            logger.exception("Failed to increment book request for %s", code)

        try:
            await msg.reply_document(
                document=book["file_id"],
                filename=book.get("filename"),
                caption=book.get("caption"),
                parse_mode=None,
            )
        except Exception as e:
            logger.exception("Failed to send book %s to %s: %s", code, user_id, e)
            await msg.reply_text("❌ Failed to send file. Please try again later.")
            return

        # Send rating buttons if user hasn't rated this book yet
        try:
            if user_id is not None and not has_rated(user_id, code):
                buttons = [[InlineKeyboardButton(f"{i}⭐", callback_data=f"rate|{code}|{i}")] for i in range(1, 6)]
                await msg.reply_text("How would you rate this book?", reply_markup=InlineKeyboardMarkup(buttons))
        except Exception:
            logger.exception("Failed to send rating buttons for %s to %s", code, user_id)
        return

    # Not a known code
    await msg.reply_text("I didn't understand. Send a numeric book code (e.g. `1`).")

# ----------------- Rating callback -----------------
@safe_handler
async def rating_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    await q.answer()

    parts = (q.data or "").split("|")
    if len(parts) != 3 or parts[0] != "rate":
        return

    _, code, rating_str = parts
    try:
        rating = int(rating_str)
    except Exception:
        await q.edit_message_text("Invalid rating.")
        return

    user = q.from_user
    user_id = user.id if user else None
    if user_id is None:
        await q.edit_message_text("Unable to identify you.")
        return

    if has_rated(user_id, code):
        await q.edit_message_text("📌 You've already rated this book.")
        return

    try:
        save_rating(user_id, code, rating)
        await q.edit_message_text("✅ Thanks for your rating!")
    except Exception:
        logger.exception("Failed to save rating %s for %s by %s", rating, code, user_id)
        try:
            await q.edit_message_text("⚠️ Failed to save your rating.")
        except Exception:
            pass

# ----------------- Register handlers -----------------
def register_handlers(app):
    # Track every user first
    app.add_handler(MessageHandler(filters.ALL, track_every_user), group=0)
    app.add_handler(CallbackQueryHandler(track_every_user), group=0)

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("book_stats", book_stats))

    # Message handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))

    # Callback handlers
    app.add_handler(CallbackQueryHandler(rating_callback, pattern=r"^rate\|"))

    logger.info("Minimal handlers registered.")
