# features/all_members_command.py
"""
Robust admin broadcast feature with immediate ACK and detailed debug logging.

Flow:
1) Admin /all_members -> bot replies "Command received..."
2) Admin sends any message (text/photo/video/document/...)
3) Bot ACKs immediately "Broadcast received..." and starts background sending.
4) Bot edits a status message every PROGRESS_BATCH processed (10).
5) Bot sends final summary.

This file is defensive:
 - Persists awaiting flags to /data/awaiting_broadcasts (so restarts won't lose state)
 - Logs every invocation so you can read Railway logs
 - If the handler doesn't fire, the logs will show it.
"""

import logging
import os
import json
import time
import threading
from typing import List, Optional

from telegram import Update, Message
from telegram.ext import CallbackContext, CommandHandler, MessageHandler, Filters

import admins
from database import get_all_users

logger = logging.getLogger(__name__)

# pause and batching
PAUSE_BETWEEN_SENDS = 5
PROGRESS_BATCH = 10
LONG_REST_INTERVAL = 100
LONG_REST_SECS = 10

# persistent awaiting storage
_AWAIT_DIR = os.getenv("AWAIT_DIR", "/data/awaiting_broadcasts")
os.makedirs(_AWAIT_DIR, exist_ok=True)


def _await_path(admin_id: int) -> str:
    return os.path.join(_AWAIT_DIR, f"{admin_id}.json")


def _persist_await(admin_id: int):
    try:
        with open(_await_path(admin_id), "w") as f:
            json.dump({"admin_id": int(admin_id), "ts": int(time.time())}, f)
        logger.info("Persisted awaiting flag for admin %s", admin_id)
    except Exception as e:
        logger.exception("Failed to persist awaiting for %s: %s", admin_id, e)


def _clear_persist(admin_id: int):
    p = _await_path(admin_id)
    try:
        if os.path.exists(p):
            os.remove(p)
            logger.info("Removed persisted awaiting for admin %s", admin_id)
    except Exception:
        logger.debug("Failed to remove persisted awaiting file %s", p)


def _load_persisted() -> set:
    ids = set()
    try:
        for fn in os.listdir(_AWAIT_DIR):
            if not fn.endswith(".json"):
                continue
            try:
                p = os.path.join(_AWAIT_DIR, fn)
                with open(p, "r") as f:
                    d = json.load(f)
                ids.add(int(d.get("admin_id")))
                logger.info("Loaded persisted awaiting for admin %s", d.get("admin_id"))
            except Exception:
                logger.debug("Bad awaiting file %s", fn)
    except Exception as e:
        logger.debug("Could not list awaiting dir: %s", e)
    return ids


# in-memory awaiting flags (fast) - populated from persisted files at import
awaiting_broadcast = {aid: True for aid in _load_persisted()}


def _get_admin_ids() -> set:
    raw = getattr(admins, "ADMIN_IDS", None) or getattr(admins, "ADMINS", None) or []
    try:
        return {int(x) for x in raw}
    except Exception:
        out = set()
        for x in raw:
            try:
                out.add(int(x))
            except Exception:
                logger.debug("Ignoring bad admin id %r", x)
        return out


def _is_admin(user_id: int) -> bool:
    try:
        return int(user_id) in _get_admin_ids()
    except Exception:
        return False


def cmd_all_members(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user:
        return
    if not _is_admin(user.id):
        update.message.reply_text("❌ You are not authorized to use this command.")
        logger.info("Unauthorized /all_members attempt by %s", user.id)
        return

    awaiting_broadcast[user.id] = True
    _persist_await(user.id)
    update.message.reply_text(
        "📩 Command received! Send the message (text/photo/video/document/voice/audio/animation/sticker) "
        "you want to broadcast to ALL users.\n\nSend /cancel to abort."
    )
    logger.info("Admin %s started all_members flow; awaiting content.", user.id)


def cmd_cancel(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user:
        return
    if not _is_admin(user.id):
        return
    awaiting_broadcast.pop(user.id, None)
    _clear_persist(user.id)
    update.message.reply_text("🛑 Broadcast cancelled.")
    logger.info("Admin %s cancelled all_members flow.", user.id)


# low-level send helpers
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
        # text/caption-only
        if (message.text and not (message.photo or message.video or message.document or message.audio or message.voice or message.animation or message.sticker)) or (
            not message.text and message.caption and not (message.photo or message.video or message.document or message.audio or message.voice or message.animation)
        ):
            text = message.text if message.text else message.caption
            bot.send_message(chat_id=user_id, text=text)
            return True

        if message.photo:
            bot.send_photo(chat_id=user_id, photo=message.photo[-1].file_id, caption=message.caption)
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
            bot.send_voice(chat_id=user_id, voice=message.voice.file_id)
            return True

        if message.animation:
            bot.send_animation(chat_id=user_id, animation=message.animation.file_id, caption=message.caption)
            return True

        if message.sticker:
            bot.send_sticker(chat_id=user_id, sticker=message.sticker.file_id)
            return True

        # fallback: forward original
        try:
            bot.forward_message(chat_id=user_id, from_chat_id=message.chat.id, message_id=message.message_id)
            return True
        except Exception:
            return False

    except Exception as e:
        # handle rate limit
        if _is_rate_limit_exc(e):
            wait = _get_retry_after(e) + 1
            logger.warning("RetryAfter for user %s: sleeping %s", user_id, wait)
            time.sleep(wait)
            try:
                return _send_to_user(bot, user_id, message)
            except Exception as e2:
                logger.exception("Retry failed for user %s: %s", user_id, e2)
                return False

        if _is_forbidden_exc(e) or _is_badrequest_exc(e):
            logger.debug("Skipping user %s due to %s", user_id, e)
            return False

        logger.exception("Error sending to %s: %s", user_id, e)
        return False


def _format_status(sent: int, failed: int, processed: int, total: int) -> str:
    return f"Progress: ✅ {sent} sent  •  ❌ {failed} failed  •  {processed}/{total} processed"


def _background_broadcast(bot, admin_chat_id: int, status_chat_id: int, status_message_id: Optional[int], message: Message, targets: List[int]):
    total = len(targets)
    sent = 0
    failed = 0
    processed = 0
    status_msg_id = status_message_id
    status_chat = status_chat_id

    logger.info("Background broadcast started by admin %s; total=%s", admin_chat_id, total)

    for idx, uid in enumerate(targets, start=1):
        ok = _send_to_user(bot, uid, message)
        if ok:
            sent += 1
        else:
            failed += 1
        processed += 1

        if (processed % PROGRESS_BATCH == 0) or (processed == total):
            text = _format_status(sent, failed, processed, total)
            try:
                if status_msg_id:
                    bot.edit_message_text(text=text, chat_id=status_chat, message_id=status_msg_id)
                else:
                    m = bot.send_message(chat_id=admin_chat_id, text=text)
                    status_msg_id = m.message_id
                    status_chat = m.chat.id
            except Exception as e:
                logger.debug("Status edit/send failed: %s", e)
                status_msg_id = None

        time.sleep(PAUSE_BETWEEN_SENDS)

        if LONG_REST_INTERVAL > 0 and idx % LONG_REST_INTERVAL == 0:
            logger.info("Long rest after %s sends", idx)
            time.sleep(LONG_REST_SECS)

        if idx % 50 == 0:
            logger.info("Progress log: %s/%s (sent=%s failed=%s)", idx, total, sent, failed)

    try:
        bot.send_message(chat_id=admin_chat_id, text=f"🎉 Broadcast finished! ✅ {sent} sent, ❌ {failed} failed.")
    except Exception:
        logger.exception("Could not send final summary to admin %s", admin_chat_id)

    logger.info("Broadcast done. sent=%s failed=%s total=%s", sent, failed, total)


def message_router(update: Update, context: CallbackContext):
    # debug - always log and ack when admin sends content while awaiting
    user = update.effective_user
    chat = update.effective_chat
    if not user:
        logger.debug("message_router: no user")
        return

    logger.info("message_router invoked by user=%s chat=%s", getattr(user, "id", None), getattr(chat, "id", None))

    if not _is_admin(user.id):
        logger.debug("message_router: user %s not admin", user.id)
        return

    # check in-memory awaiting first
    waiting = awaiting_broadcast.pop(user.id, False)
    # if not set in memory, check persisted file
    if not waiting:
        p = _await_path(user.id)
        if os.path.exists(p):
            waiting = True
            try:
                os.remove(p)
            except Exception:
                pass
            logger.info("message_router: found persisted awaiting for admin %s", user.id)

    if not waiting:
        logger.info("message_router: admin %s is not awaiting broadcast", user.id)
        return

    # immediate ACK so admin can't be left wondering
    try:
        types = []
        msg = update.message
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
        msg_type = "+".join(types) if types else "unknown"
        context.bot.send_message(chat_id=chat.id, text=f"📨 Broadcast received (type: {msg_type}). Starting send...")
        logger.info("Broadcast received from admin %s type=%s", user.id, msg_type)
    except Exception:
        logger.exception("Failed to ACK admin %s", user.id)

    # prepare targets
    targets = []
    try:
        raw_targets = get_all_users()
        for r in raw_targets:
            if isinstance(r, (list, tuple)):
                targets.append(int(r[0]))
            else:
                targets.append(int(r))
    except Exception:
        logger.exception("Failed to load targets")
        targets = []

    total = len(targets)
    if total == 0:
        context.bot.send_message(chat_id=chat.id, text="⚠️ No users found to send to.")
        logger.info("No target users for broadcast")
        return

    # initial status
    status_msg = None
    try:
        status_msg = context.bot.send_message(chat_id=chat.id, text=_format_status(0, 0, 0, total))
    except Exception as e:
        logger.debug("Couldn't create initial status message: %s", e)
        status_msg = None

    status_chat_id = status_msg.chat.id if status_msg else chat.id
    status_message_id = status_msg.message_id if status_msg else None

    # start background sender
    t = threading.Thread(
        target=_background_broadcast,
        args=(context.bot, chat.id, status_chat_id, status_message_id, update.message, targets),
        daemon=True,
    )
    t.start()


def setup(dispatcher, bot=None):
    dispatcher.add_handler(CommandHandler("all_members", cmd_all_members))
    dispatcher.add_handler(CommandHandler("cancel", cmd_cancel))
    dispatcher.add_handler(MessageHandler(Filters.all & ~Filters.command, message_router))
    logger.info("all_members_command loaded. Admins=%r", sorted(list(_get_admin_ids())))
