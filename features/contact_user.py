# features/contact_user.py
"""
Admin-only user contact feature.

Flow:
1) /contact <user_id>
2) Bot asks confirmation to send winner message
3) Admin confirms YES / NO
4) If YES -> bot sends winner message with contact button to user
5) User presses button -> bridge opens (admin <-> user)
6) Messages are relayed both ways
7) Admin ends with /end_contact
8) Auto-timeout closes bridge if forgotten

Extras added:
- Prevent multiple active bridges per admin
- Auto-close after timeout
- Block user messages before bridge opens
"""

import logging
import time
import threading
from typing import Dict, Optional

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    CallbackContext,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    Filters,
)

import admins

logger = logging.getLogger(__name__)

# ================= CONFIG =================
BRIDGE_TIMEOUT_SECONDS = 24 * 60 * 60  # 24 hours
# =========================================

# admin_id -> contact state
pending_contacts: Dict[int, Dict] = {}

# active bridges
# admin_id -> { user_id, started_ts }
active_bridges: Dict[int, Dict] = {}

# user_id warned before bridge
pre_bridge_warned = set()


# ---------- helpers ----------

def _get_admin_ids():
    raw = getattr(admins, "ADMIN_IDS", None) or getattr(admins, "ADMINS", None) or []
    return {int(x) for x in raw if str(x).isdigit()}


def _is_admin(user_id: Optional[int]) -> bool:
    try:
        return int(user_id) in _get_admin_ids()
    except Exception:
        return False


def _auto_close_bridge(bot, admin_id: int):
    time.sleep(BRIDGE_TIMEOUT_SECONDS)

    bridge = active_bridges.get(admin_id)
    if not bridge:
        return

    user_id = bridge["user_id"]
    active_bridges.pop(admin_id, None)

    try:
        bot.send_message(chat_id=admin_id, text="⏱ Contact auto-closed (timeout).")
        bot.send_message(chat_id=user_id, text="ℹ️ Admin bilan aloqa muddati tugadi.")
    except Exception:
        pass

    logger.info("Auto-closed contact bridge admin=%s user=%s", admin_id, user_id)


# ---------- commands ----------

def cmd_contact(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        return

    if user.id in active_bridges:
        update.message.reply_text("⚠️ Finish current contact first using /end_contact.")
        return

    if not context.args or not context.args[0].isdigit():
        update.message.reply_text("Usage: /contact <user_id>")
        return

    target_user_id = int(context.args[0])

    pending_contacts[user.id] = {
        "user_id": target_user_id,
        "ts": int(time.time()),
    }

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes", callback_data=f"contact_yes:{user.id}"),
            InlineKeyboardButton("❌ No", callback_data=f"contact_no:{user.id}"),
        ]
    ])

    update.message.reply_text(
        f"✅ User found: {target_user_id}\n\n"
        "Do you want to send a winner message?",
        reply_markup=kb,
    )


def contact_decision(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    data = query.data
    admin_id = query.from_user.id

    if admin_id not in pending_contacts:
        query.edit_message_text("⚠️ This request expired.")
        return

    state = pending_contacts.pop(admin_id)
    user_id = state["user_id"]

    if data.startswith("contact_no"):
        query.edit_message_text("❌ Contact aborted.")
        return

    winner_text = (
        "Siz MMT testda eng yuqori ballni qo'lga kiritdingiz va g'olib bo'ldingiz.\n\n"
        "Yutuqni qo'lga kiritish uchun Admin bilan bog'lanish tugmasini bosing."
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📞 Admin bilan bog‘lanish", callback_data=f"bridge_open:{admin_id}")]
    ])

    try:
        context.bot.send_message(chat_id=user_id, text=winner_text, reply_markup=kb)
        query.edit_message_text("✅ Winner message sent to user.")
        logger.info("Winner message sent admin=%s user=%s", admin_id, user_id)
    except Exception as e:
        query.edit_message_text("❌ Failed to send message to user.")
        logger.warning("Failed to send winner msg admin=%s user=%s err=%s", admin_id, user_id, e)


def open_bridge(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    user_id = query.from_user.id
    data = query.data

    if not data.startswith("bridge_open:"):
        return

    admin_id = int(data.split(":")[1])

    if admin_id in active_bridges:
        query.edit_message_text("⚠️ Admin hozir boshqa suhbatda.")
        return

    active_bridges[admin_id] = {
        "user_id": user_id,
        "started_ts": int(time.time()),
    }

    pre_bridge_warned.discard(user_id)

    query.edit_message_text("✅ Siz admin bilan bog‘landingiz. Xabar yozishingiz mumkin.")

    context.bot.send_message(
        chat_id=admin_id,
        text=(
            f"📩 User {user_id} contacted you.\n\n"
            "You can reply now.\n"
            "Use /end_contact to close the conversation."
        ),
    )

    t = threading.Thread(
        target=_auto_close_bridge,
        args=(context.bot, admin_id),
        daemon=True,
    )
    t.start()


def cmd_end_contact(update: Update, context: CallbackContext):
    admin = update.effective_user
    if not admin or not _is_admin(admin.id):
        return

    bridge = active_bridges.pop(admin.id, None)
    if not bridge:
        update.message.reply_text("ℹ️ No active contact.")
        return

    user_id = bridge["user_id"]

    update.message.reply_text("✅ Contact closed.")
    try:
        context.bot.send_message(chat_id=user_id, text="ℹ️ Admin bilan aloqa yakunlandi. Rahmat.")
    except Exception:
        pass

    logger.info("Contact closed admin=%s user=%s", admin.id, user_id)


# ---------- message relay ----------

def relay_messages(update: Update, context: CallbackContext):
    user = update.effective_user
    msg = update.message
    if not user or not msg:
        return

    # admin -> user
    if _is_admin(user.id) and user.id in active_bridges:
        target = active_bridges[user.id]["user_id"]
        context.bot.forward_message(
            chat_id=target,
            from_chat_id=update.effective_chat.id,
            message_id=msg.message_id,
        )
        logger.info("RELAY admin=%s -> user=%s msg_id=%s", user.id, target, msg.message_id)
        return

    # user -> admin
    for admin_id, bridge in active_bridges.items():
        if bridge["user_id"] == user.id:
            context.bot.forward_message(
                chat_id=admin_id,
                from_chat_id=update.effective_chat.id,
                message_id=msg.message_id,
            )
            logger.info("RELAY user=%s -> admin=%s msg_id=%s", user.id, admin_id, msg.message_id)
            return

    # Extra 4 — user talks before bridge (warn once)
    if not _is_admin(user.id) and user.id not in pre_bridge_warned:
        update.message.reply_text("❗ Admin hali bog‘lanmadi. Tugmani bosing.")
        pre_bridge_warned.add(user.id)


# ---------- setup ----------

def setup(dispatcher):
    dispatcher.add_handler(CommandHandler("contact", cmd_contact))
    dispatcher.add_handler(CommandHandler("end_contact", cmd_end_contact))
    dispatcher.add_handler(CallbackQueryHandler(contact_decision, pattern=r"^contact_"))
    dispatcher.add_handler(CallbackQueryHandler(open_bridge, pattern=r"^bridge_open:"))
    dispatcher.add_handler(
        MessageHandler(Filters.all & ~Filters.command, relay_messages),
        group=-250  # 🔥 highest priority to avoid shadowing
    )

    logger.info("contact_user feature loaded")
