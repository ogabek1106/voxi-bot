# features/all_members_command.py
"""
Admin broadcast feature (directly using database.get_all_users).

- Admin runs /all_members
- Bot asks for broadcast content
- Admin sends any message (text/photo/video/document/voice/audio/animation/sticker)
- Bot sends content to all user IDs from database.get_all_users()
- Skips blocked users and counts failures
- Replies summary and ends conversation
"""

import logging
import time
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
from database import get_all_users  # direct import now that database.py exists

logger = logging.getLogger(__name__)

WAITING_FOR_BROADCAST = 1
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


def _is_rate_limit_exc(e) -> bool:
    return e.__class__.__name__ == "RetryAfter"


def _is_forbidden_exc(e) -> bool:
    return e.__class__.__name__ in ("Forbidden", "Unauthorized")


def _is_badrequest_exc(e) -> bool:
    return e.__class__.__name__ == "BadRequest"


def _get_retry_after(e) -> int:
    return int(getattr(e, "retry_after", 1))


def _send_to_user(bot, user_id: int, message: Message) -> bool:
    try:
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

        try:
            bot.forward_message(chat_id=user_id, from_chat_id=message.chat.id, message_id=message.message_id)
            return True
        except Exception:
            return False

    except Exception as e:
        if _is_rate_limit_exc(e):
            wait = _get_retry_after(e) + 1
            logger.warning("Hit rate limit. Sleeping %s seconds before retrying for user %s", wait, user_id)
            time.sleep(wait)
            try:
                return _send_to_user(bot, user_id, message)
            except Exception as e2:
                logger.exception("Retry failed for user %s: %s", user_id, e2)
                return False

        if _is_forbidden_exc(e):
            logger.debug("Forbidden/Unauthorized for user %s: %s", user_id, e)
            return False

        if _is_badrequest_exc(e):
            logger.debug("BadRequest for user %s: %s", user_id, e)
            return False

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

        time.sleep(PAUSE_BETWEEN_SENDS)

        if idx % 100 == 0:
            logger.info("Broadcast progress: %s/%s (success=%s, failed=%s)", idx, total, success, failed)

    update.message.reply_text(f"Sent to {success} users! {failed} failed to send.")
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
        "all_members_command feature loaded. Admins=%r",
        list(getattr(admins, "ADMIN_IDS", getattr(admins, "ADMINS", set()))),
    )
