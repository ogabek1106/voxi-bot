# features/all_members_command.py
"""
Debug-friendly broadcast feature.

- Immediately acknowledges receipt of admin content and prints message type.
- Starts background thread to send to users and update status every 10 processed.
- Logs rich debug info to help diagnose "silent" behavior.
"""

import logging
import time
import threading
from typing import List

from telegram import Update, Message
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    Filters,
)

import admins
from database import get_all_users

logger = logging.getLogger(__name__)

WAITING_FOR_BROADCAST = 1

# timing (safe)
PAUSE_BETWEEN_SENDS = 5        # seconds between each send
LONG_REST_INTERVAL = 100      # after this many messages take a longer rest
LONG_REST_SECS = 10           # extra rest seconds every LONG_REST_INTERVAL sends

# progress update frequency
PROGRESS_BATCH = 10           # update the admin-visible status after every PROGRESS_BATCH processed


def _is_admin(user_id: int) -> bool:
    try:
        raw = getattr(admins, "ADMIN_IDS", None) or getattr(admins, "ADMINS", None)
        if not raw:
            return False
        return int(user_id) in {int(x) for x in raw}
    except Exception:
        return False


def all_members_entry(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        update.message.reply_text("You are not authorized to use this command.")
        return ConversationHandler.END

    update.message.reply_text(
        "Send the message (text/photo/video/document/voice/audio/animation/sticker) you want to broadcast to ALL users.\n\nSend /cancel to abort."
    )
    return WAITING_FOR_BROADCAST


def all_members_cancel(update: Update, context: CallbackContext):
    update.message.reply_text("Broadcast cancelled.")
    return ConversationHandler.END


def _prepare_targets() -> List[int]:
    try:
        users = get_all_users()
        ids = []
        for u in users:
            if isinstance(u, (list, tuple)):
                ids.append(int(u[0]))
            else:
                ids.append(int(u))
        return ids
    except Exception as e:
        logger.exception("Failed to fetch users from DB: %s", e)
        return []


def _identify_msg_type(msg: Message) -> str:
    """Return a short string describing the received message type for debugging."""
    types = []
    if msg.text:
        types.append("text")
    if msg.photo:
        types.append("photo")
    if msg.video:
        types.append("video")
    if msg.document:
        types.append("document")
    if msg.audio:
        types.append("audio")
    if msg.voice:
        types.append("voice")
    if msg.animation:
        types.append("animation")
    if msg.sticker:
        types.append("sticker")
    if msg.contact:
        types.append("contact")
    if msg.location:
        types.append("location")
    if msg.caption and not types:
        types.append("caption-only")
    if not types:
        return "unknown"
    return "+".join(types)


def _is_rate_limit_exc(e) -> bool:
    return e.__class__.__name__ == "RetryAfter"


def _is_forbidden_exc(e) -> bool:
    return e.__class__.__name__ in ("Forbidden", "Unauthorized")


def _is_badrequest_exc(e) -> bool:
    return e.__class__.__name__ == "BadRequest"


def _get_retry_after(e) -> int:
    return int(getattr(e, "retry_after", 1))


def _send_to_user(bot, user_id: int, message: Message) -> bool:
    """
    Send a message to a single user. Returns True on success, False on permanent failure.
    """
    try:
        # Text or caption-only (no media)
        if (message.text and not (message.photo or message.video or message.document or message.audio or message.voice or message.animation or message.sticker)) or (
            not message.text and message.caption and not (message.photo or message.video or message.document or message.audio or message.voice or message.animation)
        ):
            text_to_send = message.text if message.text else message.caption
            bot.send_message(chat_id=user_id, text=text_to_send)
            return True

        if message.photo:
            file_id = message.photo[-1].file_id
            bot.send_photo(chat_id=user_id, photo=file_id, caption=message.caption)
            return True

        if message.video:
            bot.send_video(chat_id=user_id, video=message.video.file_id, caption=message.caption)
            return True

        if message.document:
            bot.send_document(chat_id=user_id, document=message.document.file_id, caption=message.caption)
            return True

        if message.audio:
            bot.send_audio(chat_id=user_id, audio=message.audio.file_id, caption=message.caption)
            return True

        if message.voice:
            bot.send_voice(chat_id=user_id, voice=message.voice.file_id, caption=message.caption)
            return True

        if message.animation:
            bot.send_animation(chat_id=user_id, animation=message.animation.file_id, caption=message.caption)
            return True

        if message.sticker:
            bot.send_sticker(chat_id=user_id, sticker=message.sticker.file_id)
            return True

        # fallback: forward original message
        try:
            bot.forward_message(chat_id=user_id, from_chat_id=message.chat.id, message_id=message.message_id)
            return True
        except Exception:
            return False

    except Exception as e:
        # Rate limit: wait and retry once
        if _is_rate_limit_exc(e):
            wait = _get_retry_after(e) + 1
            logger.warning("RetryAfter for user %s: sleeping %s seconds", user_id, wait)
            time.sleep(wait)
            try:
                return _send_to_user(bot, user_id, message)
            except Exception as e2:
                logger.exception("Retry failed for user %s: %s", user_id, e2)
                return False

        if _is_forbidden_exc(e):
            logger.debug("Forbidden for user %s: %s", user_id, e)
            return False

        if _is_badrequest_exc(e):
            logger.debug("BadRequest for user %s: %s", user_id, e)
            return False

        logger.exception("Unexpected error sending to %s: %s", user_id, e)
        return False


def _format_status(sent: int, failed: int, processed: int, total: int) -> str:
    return f"Progress: ✅ {sent} sent  •  ❌ {failed} failed  •  {processed}/{total} processed"


def _background_broadcast(bot, admin_chat_id: int, status_chat_id: int, status_message_id: int, message: Message, targets: List[int]):
    total = len(targets)
    success = 0
    failed = 0
    processed = 0
    status_msg_id = status_message_id
    status_chat = status_chat_id

    logger.info("Background broadcast started by admin %s; total=%s", admin_chat_id, total)

    for idx, uid in enumerate(targets, start=1):
        ok = _send_to_user(bot, uid, message)
        if ok:
            success += 1
        else:
            failed += 1
        processed += 1

        if (processed % PROGRESS_BATCH == 0) or (processed == total):
            text = _format_status(success, failed, processed, total)
            try:
                if status_msg_id is not None:
                    bot.edit_message_text(text=text, chat_id=status_chat, message_id=status_msg_id)
                else:
                    m = bot.send_message(chat_id=admin_chat_id, text=text)
                    status_msg_id = m.message_id
                    status_chat = m.chat.id
            except Exception as e:
                logger.debug("Failed to edit/create status message: %s", e)
                status_msg_id = None

        # pause between sends
        time.sleep(PAUSE_BETWEEN_SENDS)

        if LONG_REST_INTERVAL > 0 and idx % LONG_REST_INTERVAL == 0:
            logger.info("Long rest after %s sends: sleeping %s seconds", idx, LONG_REST_SECS)
            time.sleep(LONG_REST_SECS)

        if idx % 50 == 0:
            logger.info("Broadcast progress: %s/%s (success=%s, failed=%s)", idx, total, success, failed)

    try:
        bot.send_message(chat_id=admin_chat_id, text=f"Sent to {success} users! {failed} failed to send.")
    except Exception as e:
        logger.exception("Failed to send final summary to admin %s: %s", admin_chat_id, e)

    logger.info("Background broadcast finished. success=%s failed=%s total=%s", success, failed, total)


def broadcast_message(update: Update, context: CallbackContext):
    """
    Triggered when admin sends the broadcast content.
    This handler immediately ACKs (with debug info) and launches background worker.
    """
    user = update.effective_user
    if not user or not _is_admin(user.id):
        update.message.reply_text("You are not authorized to do that.")
        return ConversationHandler.END

    message = update.message
    bot = context.bot

    # debug: always acknowledge with message type (so UI never looks silent)
    msg_type = _identify_msg_type(message)
    try:
        update.message.reply_text(f"Broadcast received. Detected message type: {msg_type}")
    except Exception as e:
        logger.debug("Failed to send debug ack to admin %s: %s", user.id, e)

    targets = _prepare_targets()
    total = len(targets)
    if total == 0:
        try:
            update.message.reply_text("No users found to send to.")
        except Exception:
            pass
        return ConversationHandler.END

    # immediate start ack
    try:
        update.message.reply_text(f"Broadcast started: sending to {total} users... I will notify you when finished.")
    except Exception:
        logger.exception("Failed to send start acknowledgement to admin %s", user.id)

    # create initial status message for edits
    status_msg = None
    try:
        status_msg = update.message.reply_text(_format_status(0, 0, 0, total))
    except Exception as e:
        logger.debug("Failed to send initial status message (admin may have deleted): %s", e)
        status_msg = None

    status_chat_id = status_msg.chat.id if status_msg else update.effective_chat.id
    status_message_id = status_msg.message_id if status_msg else None

    # start background thread
    thread = threading.Thread(
        target=_background_broadcast,
        args=(bot, update.effective_chat.id, status_chat_id, status_message_id, message, targets),
        daemon=True,
    )
    thread.start()

    # return immediately so handler finishes
    return ConversationHandler.END


def setup(dispatcher, bot=None):
    conv = ConversationHandler(
        entry_points=[CommandHandler("all_members", all_members_entry)],
        states={
            WAITING_FOR_BROADCAST: [MessageHandler(Filters.all & ~Filters.command, broadcast_message)]
        },
        fallbacks=[CommandHandler("cancel", all_members_cancel)],
        allow_reentry=False,
    )
    dispatcher.add_handler(conv)
    logger.info(
        "all_members_command feature loaded (debug mode). Admins=%r",
        list(getattr(admins, "ADMIN_IDS", getattr(admins, "ADMINS", set()))),
    )
