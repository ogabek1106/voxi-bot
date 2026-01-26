# features/book_upload.py
"""
Feature: /book_upload (admin only)

Flow:
1. Admin sends /book_upload
2. Bot replies: "Send me the file"
3. Admin sends any file (document / photo / video / audio / voice / animation)
4. Bot forwards the file to STORAGE_CHAT_ID
5. Bot replies with:
   - FILE_ID (use this in books.py) — primary value you want
   - forwarded message_id in the storage channel (optional, handy)
"""

import logging
import os
from telegram import Update, Message
from telegram.ext import (
    CallbackContext,
    CommandHandler,
    MessageHandler,
    Filters,
)
from global_checker import allow
from global_cleaner import clean_user
from database import set_user_mode
import admins

logger = logging.getLogger(__name__)

# Read storage chat id from env if set; fallback to your hardcoded value
try:
    STORAGE_CHAT_ID = int(os.getenv("STORAGE_CHAT_ID", "-1002714023986"))
except Exception:
    STORAGE_CHAT_ID = -1002714023986


def _get_admin_ids():
    raw = getattr(admins, "ADMIN_IDS", None) or getattr(admins, "ADMINS", None) or []
    out = set()
    for x in raw:
        try:
            out.add(int(x))
        except Exception:
            logger.debug("Ignoring bad admin id value: %r", x)
    return out


def _is_admin(uid: int) -> bool:
    try:
        return int(uid) in _get_admin_ids()
    except Exception:
        return False


def cmd_book_upload(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user:
        return

    # 🔐 FREE-STATE REQUIRED
    if not allow(user.id, mode=None):
        return

    if not _is_admin(user.id):
        update.message.reply_text("❌ You are not allowed to use this command.")
        return

    # 🔒 ENTER MODAL STATE
    set_user_mode(user.id, "book_upload")

    update.message.reply_text(
        "📤 Send me the file you want to upload (document/photo/video/audio/voice/animation).\n\n"
        "I will forward it to the Storage channel and reply with the FILE_ID (use that in books.py).\n\n"
        "Send /cancel to abort."
    )
    logger.info("Admin %s started book upload flow", user.id)


def cmd_cancel(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        return

    clean_user(user.id, reason="book_upload_cancelled")
    update.message.reply_text("🛑 Upload cancelled.")

def _has_media(msg: Message) -> bool:
    return any([
        getattr(msg, "document", None),
        getattr(msg, "photo", None),
        getattr(msg, "video", None),
        getattr(msg, "audio", None),
        getattr(msg, "voice", None),
        getattr(msg, "animation", None),
    ])


def _extract_file_id_from_message(msg: Message):
    """
    Return the most relevant file_id contained in the message.
    Preference order: document, photo (largest), video, audio, voice, animation.
    Returns None if nothing found.
    """
    if not msg:
        return None
    try:
        if getattr(msg, "document", None):
            return msg.document.file_id
        if getattr(msg, "photo", None):
            # photo is a list of sizes — return the biggest
            return msg.photo[-1].file_id
        if getattr(msg, "video", None):
            return msg.video.file_id
        if getattr(msg, "audio", None):
            return msg.audio.file_id
        if getattr(msg, "voice", None):
            return msg.voice.file_id
        if getattr(msg, "animation", None):
            return msg.animation.file_id
    except Exception as e:
        logger.debug("Error extracting file_id from message: %s", e)
    return None


def upload_router(update: Update, context: CallbackContext):
    """Handles file after /book_upload command."""
    user = update.effective_user
    msg = update.message

    if not user or not msg:
        return
    if not _is_admin(user.id):
        return

    # 🔐 OWNERSHIP CHECK
    if not allow(user.id, mode="book_upload"):
        return

    if not _has_media(msg):
        update.message.reply_text("⚠️ Please send a FILE (document/photo/video/audio/voice/animation). Send /cancel to abort.")
        # restore waiting state so admin can try again
        return

    # Try to forward the original message to the storage channel
    try:
        forwarded = context.bot.forward_message(
            chat_id=STORAGE_CHAT_ID,
            from_chat_id=msg.chat.id,
            message_id=msg.message_id
        )
    except Exception as e:
        logger.exception("Failed to forward file to storage channel: %s", e)
        update.message.reply_text(
            "❌ Error: failed to forward file to storage channel. "
            "Check that the bot is a member of the storage channel and STORAGE_CHAT_ID is correct."
        )
        return

    # Extract file_id from forwarded message (sometimes forward preserves media fields)
    file_id = _extract_file_id_from_message(forwarded)

    # If forwarded object didn't have media, try to inspect the original message
    if not file_id:
        file_id = _extract_file_id_from_message(msg)

    # Compose reply: primary is FILE_ID (for books.py); also include storage message id
    try:
        storage_mid = getattr(forwarded, "message_id", None)
        reply_lines = []
        if file_id:
            reply_lines.append("✅ File uploaded.")
            reply_lines.append("📂 FILE_ID (use this in books.py):")
            reply_lines.append(file_id)
        else:
            reply_lines.append("✅ File forwarded to storage channel, but I couldn't extract a FILE_ID automatically.")
        if storage_mid is not None:
            reply_lines.append("")
            reply_lines.append("📨 Storage message_id (optional reference):")
            reply_lines.append(str(storage_mid))

        # Use plain text reply to avoid entity parsing errors
        update.message.reply_text("\n".join(reply_lines))
        logger.info("Admin %s uploaded file. file_id=%r storage_mid=%r", user.id, file_id, storage_mid)
        # 🔓 EXIT MODAL STATE AFTER SUCCESS
        clean_user(user.id, reason="book_upload_success")
    except Exception as e:
        logger.exception("Failed to reply to admin after upload: %s", e)
        try:
            update.message.reply_text("✅ Uploaded but failed to format reply. Check logs.")
        except Exception:
            pass


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
    logger.info("book_upload feature loaded. STORAGE_CHAT_ID=%s", STORAGE_CHAT_ID)
