#handlers.py

import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
    save_countdown, get_remaining_countdown,
    get_all_users
)
from utils import delete_after_delay, countdown_timer

logger = logging.getLogger(__name__)

# ------------------ helpers ------------------
def cancel_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="mock_cancel")]])

def _get_user_task_store(context: ContextTypes.DEFAULT_TYPE):
    if "mock_tasks" not in context.application.bot_data:
        context.application.bot_data["mock_tasks"] = {}
    return context.application.bot_data["mock_tasks"]

def _task_key(user_id: int) -> str:
    return f"preexam:{user_id}"

def _bar(current: int, total: int, length: int = 10) -> str:
    filled = max(0, min(length, length - (current - 1)))  # visually fills as time goes down
    # Instead, make it more intuitive: fill as time passes
    elapsed = total - current
    filled = int(length * elapsed / total)
    return "█" * filled + "-" * (length - filled)

async def mock_begin_listening(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """
    Starts the actual exam flow (Listening Part 1 placeholder).
    You can replace this with your real content delivery (audio, questions, timers).
    """
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "▶️ Starting <b>Listening — Part 1</b>\n\n"
            "🎧 Please put on your headphones.\n"
            "I’ll play the audio and then show questions.\n\n"
            "<i>(Demo placeholder — we’ll add real tasks next.)</i>"
        ),
        parse_mode="HTML"
    )
    # TODO: send audio + questions here in the next step.

async def run_preexam_countdown(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    seconds: int = 10
):
    """
    Live 10-second pre-exam countdown. Edits the same message each second.
    Supports cancellation via mock_cancel.
    At 0, it starts Listening Part 1 automatically.
    """
    try:
        total = seconds
        for s in range(seconds, 0, -1):
            bar = _bar(s, total, length=10)
            text = (
                "📝 <b>IELTS Mock Exam</b>\n\n"
                f"🕒 Exam will start in <b>{s}</b> second(s)...\n"
                f"[{bar}]\n\n"
                "Press <b>Cancel</b> if you’re not ready."
            )
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode="HTML",
                reply_markup=cancel_kb()
            )
            await asyncio.sleep(1)

        # Final tick → remove cancel button and announce start
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="✅ Ready! Starting <b>Listening — Part 1</b>...",
            parse_mode="HTML"
        )

        # Now actually start the exam (next step handler)
        await mock_begin_listening(context, chat_id)

    except asyncio.CancelledError:
        # Clean stop when user cancels
        raise
    except Exception as e:
        logger.error(f"[run_preexam_countdown ERROR] {e}")

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

# ------------------ /broadcast_new <code> ------------------
async def broadcast_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ You’re not allowed to use this command.")
        return

    if not context.args:
        await update.message.reply_text("❗ Usage: /broadcast_new <code>")
        return

    code = context.args[0]
    book = BOOKS.get(code)

    if not book:
        await update.message.reply_text("❌ Book with this code not found.")
        return

    title_line = book["caption"].split('\n')[0]
    text = (
        "📚 <b>New Book Uploaded!</b>\n\n"
        f"{title_line}\n"
        f"🆔 <b>Code:</b> <code>{code}</code>\n\n"
        "Send this number to get the file!"
    )

    count = 0
    for uid in get_all_users():
        try:
            await context.bot.send_message(uid, text, parse_mode="HTML")
            count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Failed to send to {uid}: {e}")

    await update.message.reply_text(f"✅ Sent to {count} users.")

# ------------------ Handle Document Uploads ------------------
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ You can't upload files.")
        return

    if not update.message.document:
        await update.message.reply_text("❗️ Please send a PDF file.")
        return

    file = update.message.document
    if file.mime_type != "application/pdf":
        await update.message.reply_text("❗️ Only PDF files are supported.")
        return

    forwarded = await update.message.forward(chat_id=-1002714023986)
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
                [InlineKeyboardButton(f"{i}⭐️", callback_data=f"rate|{msg}|{i}")] for i in range(1, 6)
            ]
            rating_msg = await update.message.reply_text(
                "How would you rate this book? 🤔",
                reply_markup=InlineKeyboardMarkup(rating_buttons)
            )

        remaining = get_remaining_countdown(user_id, msg)
        if remaining == 0:
            remaining = 600
            save_countdown(user_id, msg, remaining)

        countdown_msg = await update.message.reply_text(
            f"⏳ [██████████] {remaining // 60:02}:{remaining % 60:02} remaining"
        )

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

# ------------------ /mock command ------------------
async def mock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📝 <b>IELTS Mock Exam</b>\n\n"
        "⏳ Total duration: <b>~3 hours</b>\n\n"
        "The test includes 4 parts:\n"
        "1) <b>Listening</b> (~30–40 min)\n"
        "2) <b>Reading</b> (60 min)\n"
        "3) <b>Writing</b> (60 min)\n"
        "4) <b>Speaking</b> (11–14 min)\n\n"
        "📍 Please sit in a quiet place and prepare your headphones and notebook.\n"
        "When you’re ready, press <b>I am ready</b> to begin.\n\n"
        "Good luck! 🍀"
    )

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ I am ready", callback_data="mock_ready"),
            InlineKeyboardButton("⏳ Not now, need more time", callback_data="mock_later")
        ]
    ])

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=buttons)

# ------------------ User pressed "I am ready" ------------------
async def mock_ready(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    tasks = _get_user_task_store(context)
    key = _task_key(query.from_user.id)
    old_task = tasks.get(key)
    if old_task and not old_task.done():
        old_task.cancel()

    # Initial view of countdown + cancel
    text = (
        "📝 <b>IELTS Mock Exam</b>\n\n"
        "🕒 Exam will start in <b>10</b> second(s)...\n"
        "[----------]\n\n"
        "Press <b>Cancel</b> if you’re not ready."
    )
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=cancel_kb())

    # Start live countdown task
    task = asyncio.create_task(run_preexam_countdown(context, query.message.chat.id, query.message.message_id, 10))
    tasks[key] = task

# ------------------ User pressed "Not now" ------------------
async def mock_later(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("No rush — come back when you’re ready!")
    await query.edit_message_text(
        "No problem. You can type /mock whenever you’re ready.",
        parse_mode="HTML"
    )

# ------------------ User pressed "Cancel" during 10s countdown ------------------
async def mock_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Cancelled.")
    tasks = _get_user_task_store(context)
    key = _task_key(query.from_user.id)
    t = tasks.get(key)
    if t and not t.done():
        t.cancel()
    await query.edit_message_text(
        "⛔️ Mock exam cancelled.\nType /mock when you’re ready again.",
        parse_mode="HTML"
    )

# ------------------ Register ------------------
def register_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("asd", admin_commands))
    app.add_handler(CommandHandler("all_books", all_books))
    app.add_handler(CommandHandler("book_stats", book_stats))
    app.add_handler(CommandHandler("broadcast_new", broadcast_new))
    app.add_handler(CommandHandler("mock", mock_cmd))  # IELTS mock command
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))
    app.add_handler(CallbackQueryHandler(rating_callback, pattern=r"^rate\|"))
    app.add_handler(CallbackQueryHandler(mock_ready, pattern=r"^mock_ready$"))
    app.add_handler(CallbackQueryHandler(mock_later, pattern=r"^mock_later$"))
    app.add_handler(CallbackQueryHandler(mock_cancel, pattern=r"^mock_cancel$"))
