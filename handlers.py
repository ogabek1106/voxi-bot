#handlers.py

import asyncio
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters
)
from telegram.error import BadRequest
from config import ADMIN_IDS
from books import BOOKS
from database import (
    add_user_if_not_exists, get_user_count,
    increment_book_request, get_book_stats,
    has_rated, save_rating, get_rating_stats,
    save_countdown, get_remaining_countdown,
    get_all_users,

    # --- NEW TOKEN FUNCTIONS ---
    get_token_owner, get_token_for_user, save_token,
)
from utils import delete_after_delay, countdown_timer
from database import start_bridge, get_bridge_admin, end_bridge
from config import ADMIN_IDS
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# ------------------ Helpers ------------------
def cancel_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="mock_cancel")]])

def _bar_left(seconds_left: int, total: int, length: int = 10) -> str:
    elapsed = max(0, total - seconds_left)
    filled = int(length * elapsed / total)
    return "█" * filled + "-" * (length - filled)

# Keys for chat_data (per chat state for pre-exam countdown)
KD_COUNT_LEFT = "mock_count_left"
KD_COUNT_TOTAL = "mock_count_total"
KD_MSG_ID     = "mock_msg_id"
KD_JOB_NAME   = "mock_job_name"

# ------------------ Listening placeholder ------------------
async def mock_begin_listening(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "▶️ Starting <b>Listening — Part 1</b>\n\n"
            "🎧 Please put on your headphones.\n"
            "<i>(Demo placeholder — we’ll add real audio & questions next.)</i>"
        ),
        parse_mode="HTML"
    )

# ------------------ /start ------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Robust /start:
    - parses context.args, raw message text and entities for payload
    - if payload == 'get_test' -> call get_test(update, context)
    - otherwise show fallback "Get test" button
    """
    msg = update.effective_message
    user_id = update.effective_user.id if update.effective_user else None
    raw_text = msg.text if msg else None
    logger.info("START received raw_text=%r args=%r from=%s", raw_text, context.args, user_id)

    payload = None

    # 1) context.args (typical)
    if context.args:
        payload = context.args[0]

    # 2) raw text parsing (typed "/start get_test")
    if not payload and raw_text:
        parts = raw_text.strip().split(maxsplit=1)
        if len(parts) >= 2:
            payload = parts[1].strip()

    # 3) parse using entities (most robust)
    if not payload and msg and getattr(msg, "entities", None):
        try:
            for ent in msg.entities:
                if ent.type == "bot_command":
                    start_idx = ent.offset + ent.length
                    rest = raw_text[start_idx:].strip() if raw_text and start_idx < len(raw_text) else ""
                    if rest:
                        if rest.startswith("start="):
                            payload = rest.split("=", 1)[1].strip()
                        else:
                            payload = rest.split()[0].strip()
                        break
        except Exception as e:
            logger.exception("Failed to parse entities for start payload: %s", e)

    if payload and payload.startswith("start="):
        payload = payload.split("=", 1)[1]

    logger.info("Parsed start payload=%r", payload)

    # If payload requests test, call existing get_test handler
    if payload and payload.lower() == "get_test":
        return await get_test(update, context)

    # Default start behaviour
    add_user_if_not_exists(user_id)

    # If user already has a token, show it
    existing = get_token_for_user(user_id)
    if existing:
        await msg.reply_text(
            f"Assalomu alaykum! Sizda allaqachon token mavjud: <code>{existing}</code>\n\n"
            "Agar yangi token kerak bo'lsa, yozing /get_test",
            parse_mode="HTML"
        )
        return

    # Fallback button (calls get_test_callback)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📝 Get test", callback_data="get_test_cmd")]])
    await msg.reply_text(
        "Welcome! Press the button below to get your test (fallback if deep-link payload was lost).",
        reply_markup=keyboard
    )

# ------------------ /stats ------------------
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in ADMIN_IDS:
        total_users = get_user_count()
        await update.message.reply_text(f"📊 Total users: {total_users}")
    else:
        await update.message.reply_text("Darling, you are not an admin 🤪")

## ------------------ /whois ------------------
async def whois_token(update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.message.reply_text("You are not admin.")

    if not context.args:
        return await update.message.reply_text("Usage: /whois <token>")

    token = context.args[0]
    owner = get_token_owner(token)

    if owner:
        await update.message.reply_text(f"Token belongs to user_id: {owner}")
    else:
        await update.message.reply_text("Token not found.")


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

# ------------------ Handle all messages (book codes) ------------------
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

# ------------------ /mock command (intro) ------------------
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
        [InlineKeyboardButton("✅ I am ready", callback_data="mock_ready"),
         InlineKeyboardButton("⏳ Not now, need more time", callback_data="mock_later")]
    ])
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=buttons)

# ------------------ "I am ready" → start 10s countdown via JobQueue ------------------
async def mock_ready(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    # Cancel any previous countdown jobs for this chat
    job_name = f"mock_pre_{q.message.chat.id}"
    for j in context.job_queue.get_jobs_by_name(job_name):
        j.schedule_removal()

    total = 10
    context.chat_data[KD_COUNT_LEFT] = total
    context.chat_data[KD_COUNT_TOTAL] = total
    context.chat_data[KD_MSG_ID] = q.message.message_id
    context.chat_data[KD_JOB_NAME] = job_name

    try:
        await q.edit_message_text(
            "📝 <b>IELTS Mock Exam</b>\n\n"
            f"🕒 Exam will start in <b>{total}</b> second(s)...\n"
            f"[{'-'*10}]\n\n"
            "Press <b>Cancel</b> if you’re not ready.",
            parse_mode="HTML",
            reply_markup=cancel_kb()
        )
    except BadRequest:
        pass

    context.job_queue.run_repeating(
        mock_pre_tick,
        interval=1.0,
        first=1.0,
        name=job_name,
        data={"chat_id": q.message.chat.id}
    )

# ------------------ Countdown tick ------------------
async def mock_pre_tick(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data["chat_id"]
    chat_data = context.application.chat_data.get(chat_id, {})

    left  = chat_data.get(KD_COUNT_LEFT, 0)
    total = chat_data.get(KD_COUNT_TOTAL, 10)
    msgid = chat_data.get(KD_MSG_ID)

    # Finished/cancelled
    if left <= 0 or not msgid:
        for j in context.job_queue.get_jobs_by_name(chat_data.get(KD_JOB_NAME, "")):
            j.schedule_removal()
        return

    left -= 1
    chat_data[KD_COUNT_LEFT] = left
    context.application.chat_data[chat_id] = chat_data  # persist change

    if left > 0:
        bar = _bar_left(left, total, 10)
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=msgid,
                text=(
                    "📝 <b>IELTS Mock Exam</b>\n\n"
                    f"🕒 Exam will start in <b>{left}</b> second(s)...\n"
                    f"[{bar}]\n\n"
                    "Press <b>Cancel</b> if you’re not ready."
                ),
                parse_mode="HTML",
                reply_markup=cancel_kb()
            )
        except BadRequest:
            pass
        return

    # left == 0 → finish, remove cancel, start exam
    for j in context.job_queue.get_jobs_by_name(chat_data.get(KD_JOB_NAME, "")):
        j.schedule_removal()

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=msgid,
            text="✅ Ready! Starting <b>Listening — Part 1</b>...",
            parse_mode="HTML"
        )
    except BadRequest:
        pass

    await mock_begin_listening(context, chat_id)

# ------------------ "Not now" ------------------
async def mock_later(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("No rush — come back when you’re ready!")
    await q.edit_message_text("No problem. You can type /mock whenever you’re ready.", parse_mode="HTML")

# ------------------ Cancel during countdown ------------------
async def mock_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Cancelled.")
    chat_id = q.message.chat.id

    job_name = context.chat_data.get(KD_JOB_NAME, f"mock_pre_{chat_id}")
    for j in context.job_queue.get_jobs_by_name(job_name):
        j.schedule_removal()

    try:
        await q.edit_message_text(
            "⛔️ Mock exam cancelled.\nType /mock when you’re ready again.",
            parse_mode="HTML"
        )
    except BadRequest:
        pass

    for k in [KD_COUNT_LEFT, KD_COUNT_TOTAL, KD_MSG_ID, KD_JOB_NAME]:
        context.chat_data.pop(k, None) 

## ---------------- Google Test ----------------

import uuid
from database import save_token, get_token_for_user
from config import GOOGLE_FORM_BASE, GOOGLE_FORM_ENTRY_TOKEN
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram import Update
from telegram.ext import ContextTypes

# Callback that triggers get_test when user presses fallback button
async def get_test_callback(query_update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = query_update.callback_query
    await q.answer()  # acknowledge button press

    # Reuse existing get_test logic by passing q.message as the message update
    fake_update = Update(update_id=query_update.update_id, message=q.message)
    return await get_test(fake_update, context)

async def get_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Check if user already has a token
    existing = get_token_for_user(user_id)
    if existing:
        token = existing
    else:
        # Generate a new unique token and save it
        token = uuid.uuid4().hex[:12]
        save_token(user_id, token)

    # Build pre-filled Google Form link
    form_link = f"{GOOGLE_FORM_BASE}?usp=pp_url&{GOOGLE_FORM_ENTRY_TOKEN}={token}"

    # Inline button (prevents Telegram from breaking the URL)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Start test", url=form_link)]
    ])

    # Send message
    await update.message.reply_text(
        f"✏️ Testga ulanish havolangiz tayyor!\n\n"
        f"🔑 Sizning tokeningiz: <code>{token}</code>\n\n",
        parse_mode="HTML",
        reply_markup=keyboard
    )

# --- Constants
SPAM_HELP_URL = "/mnt/data/voxi-form-responses-823c82ea7719.json"  # uploaded local path (you'll map this to a public URL as needed)
ADMIN_TG = "Ogabek1106"  # your personal username without @
ADMIN_TG_LINK = f"https://t.me/{ADMIN_TG}"

# Called when user presses the "I'm spam-blocked" callback button
async def spam_help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    # data format may be "spam_help|<target_user>" or "spam_help_start|<target_user>|<admin_id>"
    parts = data.split("|")

    # If the button contains admin id (from notify_user), extract it; otherwise link to first admin
    admin_id = None
    if len(parts) >= 3 and parts[0] in ("spam_help", "spam_help_start"):
        # format: spam_help_start|<target_user>|<admin_id>
        try:
            admin_id = int(parts[2])
        except Exception:
            admin_id = None

    # the target_user from callback (the user who will be bridged) — usually current chat id
    # prefer to use query.from_user.id (the person pressing) as the user to bridge
    target_user = query.from_user.id

    if not admin_id:
        # fallback: pick first admin from ADMIN_IDS set
        try:
            admin_id = next(iter(ADMIN_IDS))
        except StopIteration:
            admin_id = None

    # create the bridge
    start_bridge(target_user, admin_id)

    # notify admin that bridge is started
    try:
        await context.bot.send_message(
            chat_id=admin_id,
            text=(f"🔔 Bridge opened with user <code>{target_user}</code> — they pressed 'I'm spam-blocked'.\n\n"
                  "You can reply using:\n"
                  f"<code>/reply {target_user} Your message here</code>\n"
                  f"When finished, close with: <code>/close_bridge {target_user}</code>"),
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Failed to notify admin {admin_id}: {e}")

    # confirm to user and provide contact admin button too
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Contact admin", url=ADMIN_TG_LINK)]
    ])

    try:
        await query.edit_message_text(
            "✅ Bizga xabar yubordik. Endi siz admin bilan bot orqali bog'lanishingiz mumkin.\n\n"
            "Admin sizga tez orada javob beradi. Agar adminga to'g'ridan-to'g'ri yozmoqchi bo'lsangiz ishlabchi tugmani bosing.",
            reply_markup=keyboard
        )
    except Exception:
        pass


# Forward user's messages (while bridged) to the linked admin automatically
async def bridge_forward_user_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only handle messages from users (not channels/groups)
    user = update.effective_user
    if not user:
        return

    # Do not forward admin messages here
    if user.id in ADMIN_IDS:
        return

    admin_id = get_bridge_admin(user.id)
    if not admin_id:
        return  # no active bridge for this user

    msg = update.message
    if not msg:
        return

    # Forward the original message to admin (preserves content and attachments)
    try:
        await context.bot.forward_message(chat_id=admin_id, from_chat_id=msg.chat.id, message_id=msg.message_id)
    except Exception as e:
        # fallback: send a text summary
        try:
            await context.bot.send_message(chat_id=admin_id, text=f"[From {user.id}] {msg.text or '<non-text message>'}")
        except Exception:
            pass


# Admin command: reply to bridged user via bot
async def reply_bridge_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not allowed to use this command.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("❗ Usage: /reply <user_id> <message>")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❗ Invalid user_id.")
        return

    text = " ".join(context.args[1:])
    try:
        await context.bot.send_message(chat_id=target_id, text=text)
        await update.message.reply_text("✅ Sent.")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Failed to send: {e}")


# Admin command: close the bridge
async def close_bridge_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not allowed to use this command.")
        return

    if not context.args:
        await update.message.reply_text("❗ Usage: /close_bridge <user_id>")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❗ Invalid user_id.")
        return

    end_bridge(target_id)
    await update.message.reply_text(f"✅ Bridge with <code>{target_id}</code> closed.", parse_mode="HTML")

    # notify user
    try:
        await context.bot.send_message(chat_id=target_id,
                                       text="🔒 Admin bilan aloqangiz yakunlandi. Agar kerak bo'lsa, yana murojaat qiling.")
    except Exception:
        pass


# ------------------ Register ------------------
def register_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("get_test", get_test))
    app.add_handler(CommandHandler("whois", whois_token))
    app.add_handler(CommandHandler("asd", admin_commands))
    app.add_handler(CommandHandler("all_books", all_books))
    app.add_handler(CommandHandler("book_stats", book_stats))
    app.add_handler(CommandHandler("broadcast_new", broadcast_new))
    app.add_handler(CommandHandler("mock", mock_cmd))  # IELTS mock command
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))
    app.add_handler(CallbackQueryHandler(get_test_callback, pattern=r"^get_test_cmd$"))
    app.add_handler(CallbackQueryHandler(rating_callback, pattern=r"^rate\|"))
    app.add_handler(CallbackQueryHandler(mock_ready,  pattern=r"^mock_ready$"))
    app.add_handler(CallbackQueryHandler(mock_later,  pattern=r"^mock_later$"))
    app.add_handler(CallbackQueryHandler(mock_cancel, pattern=r"^mock_cancel$"))
    # Callback for spam-help button
    app.add_handler(CallbackQueryHandler(spam_help_callback, pattern=r"^spam_help"))

    # Admin reply and close commands
    app.add_handler(CommandHandler("reply", reply_bridge_cmd))
    app.add_handler(CommandHandler("close_bridge", close_bridge_cmd))

    # Forward user messages to admin if bridge is active — register this AFTER your handle_code and other main handlers
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, bridge_forward_user_messages))
