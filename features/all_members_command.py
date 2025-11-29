# features/all_members_command.py
"""
Admin broadcast feature — persistent waiting flag + debug logging.

- Persists awaiting state to disk under /data/awaiting_broadcasts so restarts won't clear it.
- Logs when waiting is set and when message_router runs (so you can inspect Railway logs).
- Background sender with progress updates every PROGRESS_BATCH and 5s pause between sends.
"""

import logging
import time
import threading
import os
import json
from typing import Dict, List, Optional

from telegram import Update, Message
from telegram.ext import CallbackContext, CommandHandler, MessageHandler, Filters

import admins
from database import get_all_users

logger = logging.getLogger(__name__)

# timing / safety
PAUSE_BETWEEN_SENDS = 5        # seconds between each send
LONG_REST_INTERVAL = 100      # after this many messages take a longer rest
LONG_REST_SECS = 10           # extra rest seconds every LONG_REST_INTERVAL sends
PROGRESS_BATCH = 10           # update admin-visible status every PROGRESS_BATCH processed

# storage for persistence of awaiting flags
_AWAIT_DIR = os.getenv("AWAIT_DIR", "/data/awaiting_broadcasts")
os.makedirs(_AWAIT_DIR, exist_ok=True)

# in-memory state (kept for speed) and backed on disk
awaiting_broadcast: Dict[int, bool] = {}


def _await_file_path(admin_id: int) -> str:
    return os.path.join(_AWAIT_DIR, f"{admin_id}.json")


def _persist_set(admin_id: int):
    path = _await_file_path(admin_id)
    try:
        with open(path, "w") as f:
            json.dump({"admin_id": int(admin_id), "ts": int(time.time())}, f)
        awaiting_broadcast[admin_id] = True
        logger.info("awaiting set persisted for admin %s -> %s", admin_id, path)
    except Exception as e:
        logger.exception("Failed to persist awaiting flag for %s: %s", admin_id, e)
        # still set in memory
        awaiting_broadcast[admin_id] = True


def _persist_pop(admin_id: int):
    path = _await_file_path(admin_id)
    awaiting_broadcast.pop(admin_id, None)
    try:
        if os.path.exists(path):
            os.remove(path)
            logger.info("awaiting file removed for admin %s -> %s", admin_id, path)
    except Exception as e:
        logger.debug("Could not remove awaiting file %s: %s", path, e)


def _load_persisted():
    try:
        for fname in os.listdir(_AWAIT_DIR):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(_AWAIT_DIR, fname)
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                admin_id = int(data.get("admin_id"))
                awaiting_broadcast[admin_id] = True
                logger.info("Loaded persisted awaiting flag for admin %s from %s", admin_id, path)
            except Exception as e:
                logger.debug("Failed to load awaiting file %s: %s", path, e)
    except Exception as e:
        logger.debug("Failed to list/load awaiting dir %s: %s", _AWAIT_DIR, e)


# load persisted awaiting flags at import
_load_persisted()

# helper: admins check
def _is_admin(user_id: int) -> bool:
    try:
        raw = getattr(admins, "ADMIN_IDS", None) or getattr(admins, "ADMINS", None)
        if not raw:
            return False
        return int(user_id) in {int(x) for x in raw}
    except Exception:
        return False


def cmd_all_members(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        context.bot.send_message(chat_id=update.effective_chat.id, text="You are not authorized to use this command.")
        return

    # persist waiting state
    _persist_set(user.id)

    # log explicit debug line
    logger.info("Admin %s issued /all_members — awaiting broadcast content (persisted)", user.id)

    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Send the message (text/photo/video/document/voice/audio/animation/sticker) you want to broadcast to ALL users.\n\nSend /cancel to abort."
    )


def cmd_cancel(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        return
    _persist_pop(user.id)
    context.bot.send_message(chat_id=update.effective_chat.id, text="Broadcast cancelled.")
    logger.info("Admin %s cancelled broadcast (awaiting cleared).", user.id)


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

        logger.exception("Unexpected error when sending to %s: %s", user_id, e)
        return False


def _format_status(sent: int, failed: int, processed: int, total: int) -> str:
    return f"Progress: ✅ {sent} sent  •  ❌ {failed} failed  •  {processed}/{total} processed"


def _background_broadcast(bot, admin_chat_id: int, status_chat_id: int, status_message_id: Optional[int], message: Message, targets: List[int]):
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

        # update status every PROGRESS_BATCH processed or at the end
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

        # Sleep between sends
        time.sleep(PAUSE_BETWEEN_SENDS)

        # occasional long rest
        if LONG_REST_INTERVAL > 0 and idx % LONG_REST_INTERVAL == 0:
            logger.info("Long rest after %s sends: sleeping %s seconds", idx, LONG_REST_SECS)
            time.sleep(LONG_REST_SECS)

        if idx % 50 == 0:
            logger.info("Broadcast progress: %s/%s (success=%s, failed=%s)", idx, total, success, failed)

    # final summary to admin
    try:
        bot.send_message(chat_id=admin_chat_id, text=f"Sent to {success} users! {failed} failed to send.")
    except Exception as e:
        logger.exception("Failed to send final summary to admin %s: %s", admin_chat_id, e)

    logger.info("Background broadcast finished. success=%s failed=%s total=%s", success, failed, total)


def message_router(update: Update, context: CallbackContext):
    """Catch normal messages — if admin is waiting, treat it as broadcast content."""
    user = update.effective_user
    if not user:
        logger.debug("message_router: no effective_user; ignoring")
        return

    logger.info("message_router invoked by user=%s chat=%s", user.id, update.effective_chat.id)

    if not _is_admin(user.id):
        logger.debug("message_router: user %s is not admin; ignoring", user.id)
        return  # ignore non-admin messages here

    # check persisted/in-memory waiting flag
    waiting = awaiting_broadcast.pop(user.id, False)
    if not waiting:
        # also check persisted file just in case
        path = _await_file_path(user.id)
        if os.path.exists(path):
            # load it and treat as waiting
            try:
                awaiting_broadcast[user.id] = True
                waiting = True
                logger.info("message_router: found persisted awaiting file for admin %s; continuing", user.id)
            except Exception:
                waiting = False

    if not waiting:
        logger.info("message_router: admin %s is not awaiting broadcast (no flag); returning", user.id)
        return  # admin isn't in broadcast flow; ignore

    # clear persisted flag now
    try:
        _persist_pop(user.id)
    except Exception:
        pass

    message = update.message
    bot = context.bot

    # debug ack (ensures admin always sees immediate feedback)
    try:
        types = []
        if message.text:
            types.append("text")
        if message.photo:
            types.append("photo")
        if message.video:
            types.append("video")
        if message.document:
            types.append("document")
        if message.audio:
            types.append("audio")
        if message.voice:
            types.append("voice")
        if message.animation:
            types.append("animation")
        if message.sticker:
            types.append("sticker")
        msg_type = "+".join(types) if types else "unknown"

        bot.send_message(chat_id=update.effective_chat.id, text=f"Broadcast received. Detected message type: {msg_type}")
        logger.info("Broadcast content received from admin %s (type=%s)", user.id, msg_type)
    except Exception as e:
        logger.debug("Failed to send debug ack to admin %s: %s", user.id, e)

    # prepare targets and initial ack
    targets = _prepare_targets()
    total = len(targets)
    if total == 0:
        bot.send_message(chat_id=update.effective_chat.id, text="No users found to send to.")
        logger.info("Broadcast aborted: no target users found.")
        return

    try:
        bot.send_message(chat_id=update.effective_chat.id, text=f"Broadcast started: sending to {total} users... I will notify you when finished.")
    except Exception:
        logger.exception("Failed to send start ack to admin %s", user.id)

    # send initial status message to be edited
    status_msg = None
    try:
        status_msg = bot.send_message(chat_id=update.effective_chat.id, text=_format_status(0, 0, 0, total))
    except Exception as e:
        logger.debug("Failed to create initial status message: %s", e)
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
    # immediate return (handler done)


def setup(dispatcher, bot=None):
    # register command handlers and a catch-all message handler
    dispatcher.add_handler(CommandHandler("all_members", cmd_all_members))
    dispatcher.add_handler(CommandHandler("cancel", cmd_cancel))
    dispatcher.add_handler(MessageHandler(Filters.all & ~Filters.command, message_router))
    logger.info(
        "all_members_simple feature loaded. Admins=%r. Await dir=%s",
        list(getattr(admins, "ADMIN_IDS", getattr(admins, "ADMINS", set()))),
        _AWAIT_DIR,
    )
