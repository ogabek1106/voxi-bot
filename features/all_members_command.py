# features/all_members_command.py
"""
Admin broadcast feature with two-step flow:
  1) /all_members -> bot asks for target ids (or send 'ALL')
  2) Admin sends ids (space/comma/newline separated) OR 'ALL'
  3) Bot asks for the message content to broadcast
  4) Admin sends any message -> bot broadcasts only to chosen targets

Persistent state: /data/awaiting_broadcasts/<admin_id>.json
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

# tune these to your needs
PAUSE_BETWEEN_SENDS = 5
PROGRESS_BATCH = 10
LONG_REST_INTERVAL = 100
LONG_REST_SECS = 10

# persistent awaiting storage dir
_AWAIT_DIR = os.getenv("AWAIT_DIR", "/data/awaiting_broadcasts")
os.makedirs(_AWAIT_DIR, exist_ok=True)


def _await_path(admin_id: int) -> str:
    return os.path.join(_AWAIT_DIR, f"{admin_id}.json")


def _persist_state(admin_id: int, state: dict):
    try:
        with open(_await_path(admin_id), "w") as f:
            json.dump(state, f)
        logger.info("Persisted awaiting state for admin %s: %s", admin_id, state.get("stage"))
    except Exception as e:
        logger.exception("Failed to persist awaiting state for %s: %s", admin_id, e)


def _load_persisted_state(admin_id: int) -> Optional[dict]:
    p = _await_path(admin_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r") as f:
            return json.load(f)
    except Exception:
        logger.debug("Bad persisted awaiting file for %s", admin_id)
        return None


def _clear_persist(admin_id: int):
    p = _await_path(admin_id)
    try:
        if os.path.exists(p):
            os.remove(p)
            logger.info("Cleared persisted awaiting for admin %s", admin_id)
    except Exception:
        logger.debug("Failed to clear persisted awaiting file %s", p)


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

    # start flow: awaiting targets
    state = {"stage": "awaiting_targets", "targets": None, "ts": int(time.time())}
    awaiting_states[user.id] = state
    _persist_state(user.id, state)
    update.message.reply_text(
        "📩 Command received!\n\n"
        "Step 1 — Send target user IDs (space/comma/newline separated), or send the single word `ALL` to target everyone.\n\n"
        "Example: `1150875355 12345678 987654321`\n\n"
        "Send /cancel to abort."
    )
    logger.info("Admin %s started all_members flow; awaiting targets.", user.id)


def cmd_cancel(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        return
    awaiting_states.pop(user.id, None)
    _clear_persist(user.id)
    update.message.reply_text("🛑 Broadcast cancelled.")
    logger.info("Admin %s cancelled all_members flow.", user.id)


def _parse_ids_text(text: str) -> List[int]:
    # Accept numbers separated by spaces, commas, newlines
    cleaned = text.replace(",", " ").replace("\n", " ").strip()
    parts = [p.strip() for p in cleaned.split() if p.strip()]
    ids = []
    for p in parts:
        try:
            ids.append(int(p))
        except Exception:
            # skip non-int parts
            continue
    return ids


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
    Try to send the message object to user_id.
    Returns True on success, False on failure (Forbidden/BadRequest or other).
    """
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

        # fallback: forward
        try:
            bot.forward_message(chat_id=user_id, from_chat_id=message.chat.id, message_id=message.message_id)
            return True
        except Exception:
            return False

    except Exception as e:
        if _is_rate_limit_exc(e):
            wait = _get_retry_after(e) + 1
            logger.warning("RetryAfter for user %s: sleeping %s seconds", user_id, wait)
            time.sleep(wait)
            try:
                return _send_to_user(bot, user_id, message)
            except Exception as e2:
                logger.exception("Retry failed for user %s: %s", user_id, e2)
                return False
        if _is_forbidden_exc(e) or _is_badrequest_exc(e):
            logger.debug("Skipping user %s due to %s", user_id, e)
            return False
        logger.exception("Unexpected error when sending to %s: %s", user_id, e)
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

        # update progress every batch or at the end
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
                logger.debug("Status update failed: %s", e)
                status_msg_id = None

        time.sleep(PAUSE_BETWEEN_SENDS)

        if LONG_REST_INTERVAL > 0 and idx % LONG_REST_INTERVAL == 0:
            logger.info("Long rest after %s sends", idx)
            time.sleep(LONG_REST_SECS)

        if idx % 50 == 0:
            logger.info("Progress log: %s/%s (sent=%s failed=%s)", idx, total, sent, failed)

    # final summary
    try:
        bot.send_message(chat_id=admin_chat_id, text=f"🎉 Broadcast finished! ✅ {sent} sent, ❌ {failed} failed.")
    except Exception:
        logger.exception("Could not send final summary to admin %s", admin_chat_id)
    logger.info("Broadcast done. sent=%s failed=%s total=%s", sent, failed, total)


# in-memory states loaded from persisted files on import
awaiting_states = {}  # admin_id -> state dict
for fn in os.listdir(_AWAIT_DIR):
    if fn.endswith(".json"):
        try:
            with open(os.path.join(_AWAIT_DIR, fn), "r") as f:
                st = json.load(f)
            admin_id = int(st.get("admin_id") or os.path.splitext(fn)[0])
            awaiting_states[admin_id] = st
            logger.info("Loaded persisted awaiting for admin %s (stage=%s)", admin_id, st.get("stage"))
        except Exception:
            logger.debug("Bad persisted awaiting file %s", fn)


def message_router(update: Update, context: CallbackContext):
    """
    Handles two things:
      - receiving the targets list when admin is in 'awaiting_targets'
      - receiving the broadcast message when admin is in 'awaiting_message'
    """
    user = update.effective_user
    chat = update.effective_chat
    if not user:
        logger.debug("message_router: no user")
        return

    logger.info("message_router invoked by user=%s chat=%s", getattr(user, "id", None), getattr(chat, "id", None))

    if not _is_admin(user.id):
        logger.debug("message_router: user %s not admin", user.id)
        return

    state = awaiting_states.get(user.id)
    if not state:
        logger.info("message_router: admin %s not in flow", user.id)
        return

    stage = state.get("stage")
    msg = update.message

    # --- stage: awaiting_targets ---
    if stage == "awaiting_targets":
        # accept text only for targets
        if not msg.text:
            context.bot.send_message(chat_id=chat.id, text="Please send target user IDs as plain text (or send ALL).")
            return

        raw = msg.text.strip()
        if raw.upper() == "ALL":
            # fetch all user ids from DB
            try:
                raw_users = get_all_users()
                targets = []
                for r in raw_users:
                    if isinstance(r, (list, tuple)):
                        targets.append(int(r[0]))
                    else:
                        targets.append(int(r))
            except Exception:
                logger.exception("Failed to load all users for admin %s", user.id)
                context.bot.send_message(chat_id=chat.id, text="⚠️ Failed to load user list. Aborting.")
                awaiting_states.pop(user.id, None)
                _clear_persist(user.id)
                return
            if not targets:
                context.bot.send_message(chat_id=chat.id, text="⚠️ No users found in database to send to.")
                awaiting_states.pop(user.id, None)
                _clear_persist(user.id)
                return

            # save targets and move to awaiting_message
            state["targets"] = targets
            state["stage"] = "awaiting_message"
            awaiting_states[user.id] = state
            _persist_state(user.id, state)
            context.bot.send_message(chat_id=chat.id, text=f"✅ Targets set: ALL ({len(targets)} users).\n\nNow send the message you want to broadcast (any type).")
            logger.info("Admin %s selected ALL targets (%s)", user.id, len(targets))
            return

        # parse ids
        ids = _parse_ids_text(raw)
        if not ids:
            context.bot.send_message(chat_id=chat.id, text="Could not parse any valid numeric user ids. Please send integers separated by spaces/commas/newlines, or send ALL.")
            return

        state["targets"] = ids
        state["stage"] = "awaiting_message"
        awaiting_states[user.id] = state
        _persist_state(user.id, state)
        context.bot.send_message(chat_id=chat.id, text=f"✅ Targets set: {len(ids)} user(s).\n\nNow send the message you want to broadcast (any type).")
        logger.info("Admin %s set %s explicit targets", user.id, len(ids))
        return

    # --- stage: awaiting_message ---
    if stage == "awaiting_message":
        # ACK immediately so admin knows we received content
        try:
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
            msg_type = "+".join(types) if types else "unknown"
            context.bot.send_message(chat_id=chat.id, text=f"📨 Broadcast received (type: {msg_type}). Starting send...")
            logger.info("Broadcast content received from admin %s type=%s", user.id, msg_type)
        except Exception:
            logger.exception("Failed to ACK admin %s", user.id)

        # prepare targets from state (defensive)
        raw_targets = state.get("targets") or []
        targets = []
        for r in raw_targets:
            try:
                targets.append(int(r))
            except Exception:
                continue

        total = len(targets)
        if total == 0:
            context.bot.send_message(chat_id=chat.id, text="⚠️ No valid targets to send to. Aborting.")
            awaiting_states.pop(user.id, None)
            _clear_persist(user.id)
            return

        # initial status message
        status_msg = None
        try:
            status_msg = context.bot.send_message(chat_id=chat.id, text=_format_status(0, 0, 0, total))
        except Exception as e:
            logger.debug("Couldn't create initial status message: %s", e)
            status_msg = None

        status_chat_id = status_msg.chat.id if status_msg else chat.id
        status_message_id = status_msg.message_id if status_msg else None

        # start broadcast in background
        t = threading.Thread(
            target=_background_broadcast,
            args=(context.bot, chat.id, status_chat_id, status_message_id, msg, targets),
            daemon=True,
        )
        t.start()

        # clear state
        awaiting_states.pop(user.id, None)
        _clear_persist(user.id)
        return

    # unknown stage
    logger.info("message_router: admin %s has unknown stage=%s, clearing", user.id, stage)
    awaiting_states.pop(user.id, None)
    _clear_persist(user.id)
    context.bot.send_message(chat_id=chat.id, text="Internal: unknown state — aborted. Please run /all_members again.")


def setup(dispatcher):
    # register handlers early to avoid other handlers stealing messages
    dispatcher.add_handler(CommandHandler("all_members", cmd_all_members), group=-10)
    dispatcher.add_handler(CommandHandler("cancel", cmd_cancel), group=-10)
    dispatcher.add_handler(MessageHandler(Filters.all & ~Filters.command, message_router), group=-10)
    logger.info("all_members_command loaded. Admins=%r", sorted(list(_get_admin_ids())))
