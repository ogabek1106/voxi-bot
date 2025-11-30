# features/book_upload.py
"""
Feature: /book_upload (admin only)

Flow:
1. Admin sends /book_upload
2. Bot replies: "Send me the file"
3. Admin sends any file (document / photo / video / audio / voice / animation)
4. Bot forwards the file to STORAGE_CHAT_ID
5. Bot replies with an inline button "Show FILE_ID"
   - when tapped, the bot shows a popup (alert) containing the FILE_ID and storage link,
     so the admin can copy it with a single tap to open the alert and then copy text.
"""

import logging
import os
import time
import uuid
from typing import Optional

from telegram import Update, Message, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackContext,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    Filters,
)

import admins

logger = logging.getLogger(__name__)

try:
    STORAGE_CHAT_ID = int(os.getenv("STORAGE_CHAT_ID", "-1002714023986"))
except Exception:
    STORAGE_CHAT_ID = -1002714023986

# small in-memory token -> (file_id, storage_msg_id, created_ts)
_file_tokens = {}  # token -> (file_id, storage_mid, ts)
_TOKEN_TTL = 60 * 30  # seconds (30 minutes)


def _cleanup_tokens():
    """Remove expired tokens (best-effort)."""
    now = time.time()
    to_del = [t for t, (_, _, ts) in _file_tokens.items() if now - ts > _TOKEN_TTL]
    for t in to_del:
        try:
            del _file_tokens[t]
        except Exception:
            pass


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


# Small in-memory state to mark which admin is awaiting upload
_awaiting_upload = set()  # set of admin_ids


def cmd_book_upload(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user:
        return

    if not _is_admin(user.id):
        update.message.reply_text("❌ You are not allowed to use this command.")
        logger.info("Unauthorized /book_upload attempt by %s", getattr(user, "id", None))
        return

    _awaiting_upload.add(user.id)
    update.message.reply_text(
        "📤 Send me the file you want to upload (document/photo/video/audio/voice/animation).\n\n"
        "I will forward it to the Storage channel and give you a button to show the FILE_ID (one tap).\n\n"
        "Send /cancel to abort."
    )
    logger.info("Admin %s started book upload flow", user.id)


def cmd_cancel(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user:
        return
    if not _is_admin(user.id):
        return

    _awaiting_upload.discard(user.id)
    update.message.reply_text("🛑 Upload cancelled.")
    logger.info("Admin %s cancelled upload flow", user.id)


def _has_media(msg: Message) -> bool:
    return any([
        getattr(msg, "document", None),
        getattr(msg, "photo", None),
        getattr(msg, "video", None),
        getattr(msg, "audio", None),
        getattr(msg, "voice", None),
        getattr(msg, "animation", None),
    ])


def _extract_file_id_from_message(msg: Message) -> Optional[str]:
    """
    Return the most relevant file_id contained in the message.
    Preference order: document, photo (largest), video, audio, voice, animation.
    """
    if not msg:
        return None
    try:
        if getattr(msg, "document", None):
            return msg.document.file_id
        if getattr(msg, "photo", None):
            return msg.photo[-1].file_id
        if getattr(msg, "video", None):
            return msg.video.file_id
        if getattr(msg, "audio", None):
            return msg.audio.file_id
        if getattr(msg, "voice", None):
            return msg.voice.file_id
        if getattr(msg, "animation", None):
            return msg.animation.file_id
    except Exception:
        logger.debug("Error extracting file_id", exc_info=True)
    return None


def upload_router(update: Update, context: CallbackContext):
    """Handles file after /book_upload command."""
    user = update.effective_user
    msg = update.message

    if not user or not msg:
        return
    if not _is_admin(user.id):
        return

    if user.id not in _awaiting_upload:
        # not in flow
        return

    # remove awaiting flag regardless (we'll re-add on error)
    _awaiting_upload.discard(user.id)

    if not _has_media(msg):
        update.message.reply_text("⚠️ Please send a FILE (document/photo/video/audio/voice/animation). Send /cancel to abort.")
        _awaiting_upload.add(user.id)
        return

    # Forward original message to storage channel
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
            "Check that the bot is a member/admin of the storage channel and STORAGE_CHAT_ID is correct."
        )
        return

    # Try to extract file_id from forwarded (or original)
    file_id = _extract_file_id_from_message(forwarded) or _extract_file_id_from_message(msg)
    storage_mid = getattr(forwarded, "message_id", None)

    # Prepare token and store mapping
    _cleanup_tokens()
    token = uuid.uuid4().hex[:18]  # short token fits in callback_data
    _file_tokens[token] = (file_id, storage_mid, int(time.time()))

    # Build storage message link (works for private channel if bot is member: t.me/c/<id_without_-100>/<mid>)
    storage_link = None
    try:
        # if channel id format -100xxxxxxxxxxx -> extract xxxxx and build t.me/c/<x>/<mid>
        sid = int(STORAGE_CHAT_ID)
        if str(sid).startswith("-100"):
            ch = str(sid)[4:]  # remove -100
            if storage_mid:
                storage_link = f"https://t.me/c/{ch}/{storage_mid}"
    except Exception:
        storage_link = None

    # Compose reply: show inline button to reveal FILE_ID in popup
    try:
        kb = [
            [InlineKeyboardButton("Show FILE_ID", callback_data=f"showfile:{token}")]
        ]
        if storage_link:
            kb.append([InlineKeyboardButton("Open storage message", url=storage_link)])
        markup = InlineKeyboardMarkup(kb)
        # send short confirmation and the inline button
        update.message.reply_text("✅ File uploaded. Tap the button below to view/copy the FILE_ID.", reply_markup=markup)
        logger.info("Admin %s uploaded file. token=%s file_id_present=%s storage_mid=%s", user.id, token, bool(file_id), storage_mid)
    except Exception as e:
        logger.exception("Failed to reply after upload: %s", e)
        # fallback plain reply
        try:
            update.message.reply_text("✅ Uploaded but failed to present button. Check logs.")
        except Exception:
            pass


def callback_showfile(update: Update, context: CallbackContext):
    """Handle button press to show file_id in an alert popup (copyable)."""
    query = update.callback_query
    if not query:
        return
    user = query.from_user
    data = query.data or ""
    if not data.startswith("showfile:"):
        query.answer()  # ignore
        return

    token = data.split(":", 1)[1]
    rec = _file_tokens.get(token)
    if not rec:
        query.answer(text="This token expired or is invalid.", show_alert=True)
        return

    file_id, storage_mid, ts = rec
    # only allow admins to see it
    if not _is_admin(user.id):
        query.answer(text="Not allowed.", show_alert=True)
        return

    # create alert text: file_id first (or not found), and optional storage link info
    lines = []
    if file_id:
        lines.append("FILE_ID (copy this):")
        lines.append(file_id)
    else:
        lines.append("No FILE_ID could be extracted automatically for this file.")
    if storage_mid is not None:
        try:
            sid = int(STORAGE_CHAT_ID)
            if str(sid).startswith("-100"):
                ch = str(sid)[4:]
                lines.append("")
                lines.append("Storage message link:")
                lines.append(f"https://t.me/c/{ch}/{storage_mid}")
            else:
                lines.append("")
                lines.append(f"Storage message_id: {storage_mid}")
        except Exception:
            lines.append("")
            lines.append(f"Storage message_id: {storage_mid}")

    # show alert (popup). On most clients the alert text is selectable so user can copy.
    text = "\n".join(lines)
    try:
        query.answer(text=text, show_alert=True)
    except Exception:
        # fallback short answer
        try:
            query.answer(text="Could not show full file id in popup. Check logs.", show_alert=True)
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
    dispatcher.add_handler(CallbackQueryHandler(callback_showfile, pattern=r"^showfile:"))
    logger.info("book_upload feature loaded. STORAGE_CHAT_ID=%s", STORAGE_CHAT_ID)
