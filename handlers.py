# handlers.py — minimal handlers for Voxi bot + improved debug/fallback logic
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


# ----------------- Safe wrapper (logs entry/exit) -----------------
def safe_handler(fn):
    if not asyncio.iscoroutinefunction(fn):
        raise ValueError("safe_handler expects an async function")

    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            logger.debug("Entering handler %s for update_id=%s", fn.__name__, getattr(update, "update_id", None))
            result = await fn(update, context)
            logger.debug("Exiting handler %s for update_id=%s", fn.__name__, getattr(update, "update_id", None))
            return result
        except Exception as e:
            logger.exception("Handler %s failed: %s", fn.__name__, e)
            try:
                if update and getattr(update, "effective_message", None):
                    await update.effective_message.reply_text("⚠️ Internal error. Admins notified.")
            except Exception:
                logger.exception("Failed to send error message to user")
    return wrapper


# ----------------- Track every user (group 0) -----------------
@safe_handler
async def track_every_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.debug("track_every_user called (user=%s)", getattr(user, "id", None))
    if not user:
        return
    try:
        add_user_if_not_exists(user.id)
        logger.debug("Added/tracked user %s", user.id)
    except Exception:
        logger.exception("Failed to add user %s", user.id)


# ----------------- /start -----------------
@safe_handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    logger.debug("start handler invoked by user=%s", getattr(user, "id", None))
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
    logger.debug("stats handler invoked by %s", getattr(user, "id", None))
    if not user or user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not an admin.")
        return
    total = get_user_count()
    await update.message.reply_text(f"📊 Total users: {total}")


# ----------------- /book_stats (admin only) -----------------
@safe_handler
async def book_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.debug("book_stats handler invoked by %s", getattr(user, "id", None))
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
    """
    Main message handler that interprets plain text as a book code.
    Sets a flag in context.chat_data to prevent the debug fallback from replying.
    """
    msg = update.message
    if not msg or not msg.text:
        logger.debug("handle_code: no text -> returning")
        return

    # mark handled flag for this update/chat so debug fallback can skip
    try:
        context.chat_data["voxi_last_handled"] = True
    except Exception:
        # context.chat_data may not be available in some rare cases; ignore
        pass

    user = update.effective_user
    user_id = user.id if user else None
    text = msg.text.strip()
    logger.debug("handle_code: user=%s text=%r", user_id, text)

    # If user sent a numeric code that matches a book
    if text.isdigit() and text in BOOKS:
        code = text
        book = BOOKS[code]
        try:
            increment_book_request(code)
            logger.debug("incremented request counter for book %s", code)
        except Exception:
            logger.exception("Failed to increment book request for %s", code)

        try:
            await msg.reply_document(
                document=book["file_id"],
                filename=book.get("filename"),
                caption=book.get("caption"),
                parse_mode=None,
            )
            logger.debug("Sent book %s to user %s", code, user_id)
        except Exception as e:
            logger.exception("Failed to send book %s to %s: %s", code, user_id, e)
            await msg.reply_text("❌ Failed to send file. Please try again later.")
            return

        # Send rating buttons if user hasn't rated this book yet
        try:
            if user_id is not None and not has_rated(user_id, code):
                buttons = [[InlineKeyboardButton(f"{i}⭐", callback_data=f"rate|{code}|{i}")] for i in range(1, 6)]
                await msg.reply_text("How would you rate this book?", reply_markup=InlineKeyboardMarkup(buttons))
                logger.debug("Sent rating buttons for book %s to user %s", code, user_id)
        except Exception:
            logger.exception("Failed to send rating buttons for %s to %s", code, user_id)
        return

    # Not a known code
    logger.debug("handle_code: unknown code %r from user %s", text, user_id)
    await msg.reply_text("I didn't understand. Send a numeric book code (e.g. `1`).")


# ----------------- Rating callback -----------------
@safe_handler
async def rating_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        logger.debug("rating_callback: no callback_query -> return")
        return
    await q.answer()
    logger.debug("rating_callback invoked by user=%s data=%r", getattr(q.from_user, "id", None), q.data)

    parts = (q.data or "").split("|")
    if len(parts) != 3 or parts[0] != "rate":
        logger.debug("rating_callback: malformed data %r", q.data)
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
        logger.debug("Saved rating %s for book %s by user %s", rating, code, user_id)
    except Exception:
        logger.exception("Failed to save rating %s for %s by %s", rating, code, user_id)
        try:
            await q.edit_message_text("⚠️ Failed to save your rating.")
        except Exception:
            pass


# ---- DEBUG: fallback handler (only runs if main handler did not handle) ----
@safe_handler
async def debug_log_and_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    This is a low-priority fallback debug handler.
    It will only reply if handle_code didn't mark the update as handled.
    Use /ping to verify bot is alive. Otherwise it replies 'debug: received...' only
    if the main handler did not handle the message.
    """
    logger.debug("debug_log_and_reply invoked for update_id=%s", getattr(update, "update_id", None))

    # If main handler ran for this chat/update, skip reply (pop flag)
    handled = False
    try:
        handled = bool(context.chat_data.pop("voxi_last_handled", False))
    except Exception:
        handled = False

    # Log compact info for debugging
    try:
        info = {
            "update_id": getattr(update, "update_id", None),
            "from": getattr(update.effective_user, "id", None),
            "chat_id": getattr(getattr(update, "effective_chat", None), "id", None),
            "message_text": (update.message.text if update.message and update.message.text else None),
            "callback_data": (update.callback_query.data if update.callback_query else None),
            "handled_by_main": handled,
        }
        logger.debug("DEBUG_UPDATE (full): %s", info)
    except Exception:
        logger.exception("Failed to log debug update info")

    # If main handler already handled — do nothing
    if handled:
        logger.debug("debug_log_and_reply: skipping because main handler already responded")
        return

    # If user explicitly asked /ping (command) — reply
    if update.message and update.message.text and update.message.text.strip().lower() == "/ping":
        await update.message.reply_text("pong — debug handler alive")
        return

    # Only respond in private chats so we don't spam groups
    chat = getattr(update, "effective_chat", None)
    if chat and getattr(chat, "type", None) == "private":
        await update.effective_message.reply_text("debug: received. Check logs.")
    else:
        logger.debug("debug_log_and_reply: not replying because chat is not private")


# ----------------- Register handlers -----------------
def register_handlers(app):
    logger.info("Registering minimal handlers (track,start,handle_code,ratings,debug)")

    # Track every user first (group 0)
    app.add_handler(MessageHandler(filters.ALL, track_every_user), group=0)
    app.add_handler(CallbackQueryHandler(track_every_user), group=0)

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("book_stats", book_stats))

    # Main message handler: interpret text as book code (group 1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code), group=1)

    # Rating callbacks
    app.add_handler(CallbackQueryHandler(rating_callback, pattern=r"^rate\|"))

    # TEMP DEBUG handlers — low priority group so they don't override core logic
    app.add_handler(CommandHandler("ping", debug_log_and_reply))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, debug_log_and_reply), group=2)

    logger.info("Minimal handlers registered (with verbose debug).")
