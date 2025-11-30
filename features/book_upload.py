# features/book_upload.py
"""
Feature: /book_upload (admin only)

Flow:
1. Admin sends /book_upload
2. Bot replies: "Send me the file"
3. Admin sends any file (document / photo / video / audio / voice / animation)
4. Bot forwards the file to STORAGE_CHAT_ID
5. Bot replies with the forwarded message_id (admin uses that in books.py)
"""

import logging
from telegram import Update, Message
from telegram.ext import (
    CallbackContext,
    CommandHandler,
    MessageHandler,
    Filters,
)
import admins

logger = logging.getLogger(__name__)

# YOUR STORAGE CHANNEL
STORAGE_CHAT_ID = -1002714023986


def _get_admin_ids():
    raw = getattr(admins, "ADMIN_IDS", []) or getattr(admins, "ADMINS", [])
    out = set()
    for x in raw:
        try:
            out.add(int(x))
        except:
            pass
    return out


def _is_admin(uid):
    return uid in _get_admin_ids()


# In-memory state: which admin is waiting for file
awaiting_upload = {}


def cmd_book_upload(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user:
        return

    if not _is_admin(user.id):
        update.message.reply_text("❌ You are not allowed to use this command.")
        return

    awaiting_upload[user.id] = True
    update.message.reply_text(
        "📤 *Send me the file you want to upload.*\n\n"
        "I will forward it to the Storage channel and send you the message ID.\n\n"
        "Send /cancel to abort.",
        parse_mode="Markdown",
    )


def cmd_cancel(update: Update, context: CallbackContext):
    user = update.effective_user
    if not _is_admin(user.id):
        return

    awaiting_upload.pop(user.id, None)
    update.message.reply_text("🛑 Upload cancelled.")


def _has_media(msg: Message) -> bool:
    return any([
        msg.document,
        msg.photo,
        msg.video,
        msg.audio,
        msg.voice,
        msg.animation,
    ])


def upload_router(update: Update, context: CallbackContext):
    """Handles file after /book_upload command."""
    user = update.effective_user
    msg = update.message

    if not user or not msg:
        return
    if not _is_admin(user.id):
        return

    waiting = awaiting_upload.pop(user.id, None)
    if not waiting:
        return

    if not _has_media(msg):
        update.message.reply_text("⚠️ Please send a FILE. Not text.\nSend /cancel to abort.")
        awaiting_upload[user.id] = True
        return

    # Forward to storage
    try:
        forwarded = context.bot.forward_message(
            chat_id=STORAGE_CHAT_ID,
            from_chat_id=msg.chat.id,
            message_id=msg.message_id
        )

        mid = forwarded.message_id

        update.message.reply_text(
            f"✅ *File uploaded successfully!*\n\n"
            f"Storage Message ID: `{mid}`\n"
            f"Use this ID in *books.py* for the new book.",
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.exception(e)
        update.message.reply_text("❌ Error: cannot forward file to Storage channel.")
        return


def setup(dispatcher):
    dispatcher.add_handler(CommandHandler("book_upload", cmd_book_upload))
    dispatcher.add_handler(CommandHandler("cancel", cmd_cancel))
    dispatcher.add_handler(
        MessageHandler(
            Filters.document
            | Filters.photo
            | Filters.video
            | Filters.audio
            | Filters.voice
            | Filters.animation,
            upload_router,
        )
    )

    logger.info("book_upload.py loaded. STORAGE_CHAT_ID=%s", STORAGE_CHAT_ID)
