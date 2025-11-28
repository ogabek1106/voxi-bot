# features/all_members_command.py
"""
Admin broadcast feature.

Usage:
- Admin runs /all_members
- Bot asks: "Send the message you want to broadcast"
- Admin sends any message (text/photo/video/document/audio/voice/animation/sticker)
- Bot sends that content to all user IDs returned by database.get_all_users()
- Skips users who blocked the bot or cause permanent errors
- Handles RetryAfter by sleeping the requested time then retrying
- Replies: "Sent to X users! Y failed to send"
"""

import logging
import time
from typing import List

from telegram import Update, Message, InputMediaPhoto
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    Filters,
)
from telegram.error import Forbidden, BadRequest, RetryAfter

import admins
from database import get_all_users  # must exist in your repo

logger = logging.getLogger(__name__)

# Conversation state
WAITING_FOR_BROADCAST = 1

# small pause between sends to avoid hitting Telegram limits too fast (seconds)
PAUSE_BETWEEN_SENDS = 0.05


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

    update.message.reply_text("Send the message (text/photo/video/document/voice/audio/animation/sticker) you want to broadcast to ALL users.\n\nSend /cancel to abort.")
    return WAITING_FOR_BROADCAST


def all_members_cancel(update: Update, context: CallbackContext):
    update.message.reply_text("Broadcast cancelled.")
    return ConversationHandler.END


def _prepare_targets() -> List[int]:
    try:
        users = get_all_users()
        # expecting list of rows or list of ints: normalize
        ids = []
        for u in users:
            # if each row is tuple like (user_id, ...) or just int
            if isinstance(u, (list, tuple)):
                ids.append(int(u[0]))
            else:
                ids.append(int(u))
        return ids
    except Exception as e:
        logger.exception("Failed to fetch users from DB: %s", e)
        return []


def _send_to_user(bot, user_id: int, message: Message) -> bool:
    """
    Send the message to single user_id.
    Returns True on success, False on permanent failure.
    Handles RetryAfter by sleeping required seconds then retrying.
    """
    try:
        # Text
        if message.text or message.caption and not (
            message.photo or message.video or message.document or message.audio or message.voice or message.animation or message.sticker
        ):
            # If caption present but no media, use caption as text
            text_to_send = message.text if message.text else message.caption
            bot.send_message(chat_id=user_id, text=text_to_send)
            return True

        # Photo (send highest resolution)
        if message.photo:
            file_id = message.photo[-1].file_id
            bot.send_photo(chat_id=user_id, photo=file_id, caption=message.caption)
            return True

        # Video
        if message.video:
            bot.send_video(chat_id=user_id, video=message.video.file_id, caption=message.caption)
            return True

        # Document
        if message.document:
            bot.send_document(chat_id=user_id, document=message.document.file_id, caption=message.caption)
            return True

        # Audio
        if message.audio:
            bot.send_audio(chat_id=user_id, audio=message.audio.file_id, caption=message.caption)
            return True

        # Voice
        if message.voice:
            bot.send_voice(chat_id=user_id, voice=message.voice.file_id, caption=message.caption)
            return True

        # Animation (gif)
        if message.animation:
            bot.send_animation(chat_id=user_id, animation=message.animation.file_id, caption=message.caption)
            return True

        # Sticker
        if message.sticker:
            bot.send_sticker(chat_id=user_id, sticker=message.sticker.file_id)
            return True

        # Fallback: try forwarding the original message (preserves content but may show "forwarded from")
        try:
            bot.forward_message(chat_id=user_id, from_chat_id=message.chat.id, message_id=message.message_id)
            return True
        except Exception:
            # last resort, fail
            return False

    except RetryAfter as e:
        wait = int(getattr(e, "retry_after", 1)) + 1
        logger.warning("Hit rate limit. Sleeping %s seconds before retrying for user %s", wait, user_id)
        time.sleep(wait)
        try:
            # retry once
            return _send_to_user(bot, user_id, message)
        except Exception as e2:
            logger.exception("Retry failed for user %s: %s", user_id, e2)
            return False

    except Forbidden:
        # user blocked the bot or chat not available — permanent skip
        return False
    except BadRequest as e:
        # BadRequest may be caused by invalid file, chat not available, etc. treat as permanent failure
        logger.debug("BadRequest when sending to %s: %s", user_id, e)
        return False
    except Exception as e:
        logger.exception("Unexpected error when sending to %s: %s", user_id, e)
        return False


def broadcast_message(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        update.message.reply_text("You are not authorized to do that.")
        return ConversationHandler.END

    message = update.message
    bot = context.bot

    targets = _prepare_targets()
    if not targets:
        update.message.reply_text("No users found to send to.")
        return ConversationHandler.END

    success = 0
    failed = 0
    total = len(targets)

    update.message.reply_text(f"Broadcast started: sending to {total} users...")

    for idx, uid in enumerate(targets, start=1):
        ok = _send_to_user(bot, uid, message)
        if ok:
            success += 1
        else:
            failed += 1

        # small pause
        time.sleep(PAUSE_BETWEEN_SENDS)

        # optional: progress log every 100 sends
        if idx % 100 == 0:
            logger.info("Broadcast progress: %s/%s (success=%s, failed=%s)", idx, total, success, failed)

    update.message.reply_text(f"Sent to {success} users! {failed} failed to send.")
    return ConversationHandler.END


def setup(dispatcher, bot=None):
    """
    Register the conversation handler for /all_members.
    This registers:
    - /all_members -> ask admin to send broadcast -> WAITING_FOR_BROADCAST
    - /cancel to abort
    """
    conv = ConversationHandler(
        entry_points=[CommandHandler("all_members", all_members_entry)],
        states={
            WAITING_FOR_BROADCAST: [MessageHandler(Filters.all & ~Filters.command, broadcast_message)]
        },
        fallbacks=[CommandHandler("cancel", all_members_cancel)],
        allow_reentry=False,
    )
    dispatcher.add_handler(conv)
    logger.info("all_members_command feature loaded. Admins=%r", list(getattr(admins, "ADMIN_IDS", getattr(admins, "ADMINS", set()))))
