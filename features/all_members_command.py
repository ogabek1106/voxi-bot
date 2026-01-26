# features/all_members_command.py
"""
Admin broadcast feature with two-step flow:
  1) /all_members -> bot asks for target ids (or send 'ALL')
  2) Admin sends ids (space/comma/newline separated) OR 'ALL'
  3) Bot asks for the message content to broadcast
  4) Admin sends any message -> bot broadcasts only to chosen targets

Persistent state stored in files: /data/awaiting_broadcasts/<admin_id>.json
"""

import logging
import os
import json
import time
import threading
from typing import List, Optional
from global_checker import allow
from global_cleaner import clean_user
from database import set_user_mode
from telegram import Update, Message
from telegram.ext import CallbackContext, CommandHandler, MessageHandler, Filters
from telegram.error import TelegramError

import admins
from database import get_all_users

logger = logging.getLogger(__name__)

# ================== TUNING ==================
PAUSE_BETWEEN_SENDS = 2          # ✅ 2 seconds pause
PROGRESS_BATCH = 10              # ✅ update every 10 processed
LONG_REST_INTERVAL = 100
LONG_REST_SECS = 10
# ============================================

# admin_id -> stop flag
broadcast_stop_flags = {}

# persistent awaiting storage dir
_AWAIT_DIR = os.getenv("AWAIT_DIR", "/data/awaiting_broadcasts")
try:
    os.makedirs(_AWAIT_DIR, exist_ok=True)
except Exception:
    logger.debug("Could not create await dir %s", _AWAIT_DIR, exc_info=True)


def _await_path(admin_id: int) -> str:
    return os.path.join(_AWAIT_DIR, f"{int(admin_id)}.json")


def _persist_state(admin_id: int, state: dict):
    try:
        with open(_await_path(admin_id), "w", encoding="utf-8") as f:
            json.dump(state, f)
        logger.info("Persisted awaiting state for admin %s: %s", admin_id, state.get("stage"))
    except Exception as e:
        logger.exception("Failed to persist awaiting state for %s: %s", admin_id, e)


def _load_persisted_state(admin_id: int) -> Optional[dict]:
    p = _await_path(admin_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            s = json.load(f)
        s.setdefault("admin_id", int(admin_id))
        return s
    except Exception:
        logger.debug("Bad persisted awaiting file for %s", admin_id, exc_info=True)
        return None


def _clear_persist(admin_id: int):
    p = _await_path(admin_id)
    try:
        if os.path.exists(p):
            os.remove(p)
            logger.info("Cleared persisted awaiting for admin %s", admin_id)
    except Exception:
        logger.debug("Failed to clear persisted awaiting file %s", p, exc_info=True)


def _get_admin_ids() -> set:
    raw = getattr(admins, "ADMIN_IDS", None) or getattr(admins, "ADMINS", None) or []
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

    # 🔐 FREE-STATE REQUIRED
    if not allow(user.id, mode=None):
        return

    if not _is_admin(user.id):
        update.message.reply_text("❌ You are not authorized to use this command.")
        return

    # 🔒 ENTER TEMP MODAL STATE
    set_user_mode(user.id, "broadcast_setup")

    state = {
        "admin_id": int(user.id),
        "stage": "awaiting_targets",
        "targets": None,
        "ts": int(time.time()),
    }
    awaiting_states[user.id] = state
    _persist_state(user.id, state)

    update.message.reply_text(
        "📩 Command received!\n\n"
        "Step 1 — Send target user IDs (space/comma/newline separated), or send the single word `ALL`.\n\n"
        "Send /cancel to abort."
    )

def cmd_cancel(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        return

    clean_user(user.id, reason="broadcast_cancelled")
    awaiting_states.pop(user.id, None)
    _clear_persist(user.id)

    update.message.reply_text("🛑 Broadcast cancelled.")

def cmd_cancel_broadcast(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        return

    broadcast_stop_flags[user.id] = True
    update.message.reply_text("🛑 Broadcast stopping...")


def _parse_ids_text(text: str) -> List[int]:
    cleaned = text.replace(",", " ").replace("\n", " ").strip()
    ids = []
    for p in cleaned.split():
        try:
            ids.append(int(p))
        except Exception:
            continue
    return ids


# 🔥🔥🔥 THIS IS THE ONLY FUNCTION THAT CHANGED 🔥🔥🔥
def _send_to_user(bot, user_id: int, message: Message) -> bool:
    try:
        bot.copy_message(
            chat_id=user_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
        logger.info("BROADCAST_OK user_id=%s", user_id)
        return True
    except TelegramError as e:
        logger.warning("BROADCAST_FAIL user_id=%s reason=%s", user_id, e)
        return False


def _format_status(sent: int, failed: int, processed: int, total: int) -> str:
    return f"Progress: ✅ {sent} sent  •  ❌ {failed} failed  •  {processed}/{total} processed"


def _background_broadcast(bot, admin_id: int, chat_id: int, status_message_id: int, message: Message, targets: List[int]):
    sent = failed = processed = 0
    total = len(targets)

    for uid in targets:
        if broadcast_stop_flags.get(admin_id):
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message_id,
                text=f"🛑 Broadcast stopped.\n\n{_format_status(sent, failed, processed, total)}",
            )
            logger.info("Broadcast stopped by admin %s", admin_id)
            return

        if _send_to_user(bot, uid, message):
            sent += 1
        else:
            failed += 1

        processed += 1

        if processed % PROGRESS_BATCH == 0 or processed == total:
            try:
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_message_id,
                    text=_format_status(sent, failed, processed, total),
                )
            except Exception:
                pass

        time.sleep(PAUSE_BETWEEN_SENDS)

        if processed % LONG_REST_INTERVAL == 0:
            time.sleep(LONG_REST_SECS)

    bot.edit_message_text(
        chat_id=chat_id,
        message_id=status_message_id,
        text=f"🎉 Broadcast finished!\n\n{_format_status(sent, failed, processed, total)}",
    )
    broadcast_stop_flags.pop(admin_id, None)


# load persisted states
awaiting_states = {}
for fn in os.listdir(_AWAIT_DIR):
    if fn.endswith(".json"):
        try:
            with open(os.path.join(_AWAIT_DIR, fn), "r", encoding="utf-8") as f:
                st = json.load(f)
            awaiting_states[int(st["admin_id"])] = st
        except Exception:
            pass


def message_router(update: Update, context: CallbackContext):
    user = update.effective_user
    chat = update.effective_chat

    if not user or not _is_admin(user.id):
        return
    # 🔐 OWNERSHIP CHECK
    if not allow(user.id, mode="broadcast_setup"):
        return
    
    state = awaiting_states.get(user.id)
    if not state:
        return

    msg = update.message
    stage = state.get("stage")

    if stage == "awaiting_targets":
        if not msg or not msg.text:
            context.bot.send_message(chat_id=chat.id, text="Send target IDs or ALL.")
            return

        if msg.text.upper() == "ALL":
            users = get_all_users()
            state["targets"] = [int(u[0] if isinstance(u, (list, tuple)) else u) for u in users]
        else:
            state["targets"] = _parse_ids_text(msg.text)

        state["stage"] = "awaiting_message"
        awaiting_states[user.id] = state
        _persist_state(user.id, state)
        context.bot.send_message(chat_id=chat.id, text="✅ Targets set. Now send the message.")
        return

    if stage == "awaiting_message":
        targets = state.get("targets", [])
        if not targets:
            context.bot.send_message(chat_id=chat.id, text="⚠️ No targets.")
            return

        status_msg = context.bot.send_message(
            chat_id=chat.id,
            text=_format_status(0, 0, 0, len(targets)),
        )

        broadcast_stop_flags[user.id] = False

        # 🔓 CLEAR MODE BEFORE BACKGROUND WORK
        clean_user(user.id, reason="broadcast_started")
      
        t = threading.Thread(
            target=_background_broadcast,
            args=(context.bot, user.id, chat.id, status_msg.message_id, msg, targets),
            daemon=True,
        )
        t.start()

        awaiting_states.pop(user.id, None)
        _clear_persist(user.id)


def setup(dispatcher):
    dispatcher.add_handler(CommandHandler("all_members", cmd_all_members), group=-10)
    dispatcher.add_handler(CommandHandler("cancel", cmd_cancel), group=-10)
    dispatcher.add_handler(CommandHandler("cancel_broadcast", cmd_cancel_broadcast), group=-10)
    dispatcher.add_handler(MessageHandler(Filters.all & ~Filters.command, message_router), group=-10)
    logger.info("all_members_command loaded. Admins=%r", sorted(list(_get_admin_ids())))
