# features/contact_user.py
"""
Admin-only direct contact feature (STATE-ONLY).

Rules:
- Admin MUST be free/none to start
- User can be in ANY state (will be cleared)
- ONLY states control everything
- NO order, NO groups, NO timers
- Every forward re-validates states
- Admin ends manually with /end_contact

States used:
- None / free / none
- contact_admin_pending
- contact_admin
- contact_user
"""

import logging
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    CallbackContext,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    Filters,
)

from admins import ADMIN_IDS
from database import (
    get_user_mode,
    set_user_mode,
    clear_user_mode,
)

logger = logging.getLogger(__name__)

# =========================
# RUNTIME BRIDGE REGISTRY
# =========================
active_contacts = {}   # admin_id -> user_id
reverse_contacts = {}  # user_id -> admin_id


# =========================
# /contact <user_id | token>
# =========================
def cmd_contact(update: Update, context: CallbackContext):
    admin_id = update.effective_user.id

    if admin_id not in ADMIN_IDS:
        return

    admin_mode = get_user_mode(admin_id)

    # Admin MUST be free
    if admin_mode not in (None, "free", "none"):
        if admin_mode == "contact_admin_pending":
            update.message.reply_text("⏳ Waiting for user response.")
        else:
            update.message.reply_text("❌ Finish your current action first.")
        return

    if not context.args:
        update.message.reply_text("Usage: /contact <user_id>")
        return

    raw = context.args[0]

    # ✅ ONLY numeric user_id (SAFE)
    if not raw.isdigit():
        update.message.reply_text("❌ Token support not enabled. Use numeric user_id.")
        return

    user_id = int(raw)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Accept",
                callback_data=f"contact_accept:{admin_id}"
            )
        ]
    ])

    try:
        context.bot.send_message(
            chat_id=user_id,
            text=(
                "📩 Admin wants to contact you.\n\n"
                "Press ✅ Accept to start communication."
            ),
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.exception("Failed to send contact invite")
        update.message.reply_text("❌ Failed to send invitation.")
        return

    set_user_mode(admin_id, "contact_admin_pending", {"user_id": user_id})
    update.message.reply_text("📨 Invitation sent.")


# =========================
# USER ACCEPTS INVITATION
# =========================
def contact_accept(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    user_id = query.from_user.id
    data = query.data

    if not data.startswith("contact_accept:"):
        return

    admin_id = int(data.split(":")[1])

    if get_user_mode(admin_id) != "contact_admin_pending":
        query.edit_message_text("❌ Invitation expired.")
        return

    clear_user_mode(user_id)

    set_user_mode(user_id, "contact_user", {"admin_id": admin_id})
    set_user_mode(admin_id, "contact_admin", {"user_id": user_id})

    active_contacts[admin_id] = user_id
    reverse_contacts[user_id] = admin_id

    query.edit_message_text("✅ Contact started.")

    context.bot.send_message(
        chat_id=admin_id,
        text="✅ User accepted. Direct contact is open.\nUse /end_contact to close.",
    )


# =========================
# MESSAGE RELAY
# =========================
def relay_messages(update: Update, context: CallbackContext):
    sender_id = update.effective_user.id
    msg = update.message
    if not msg:
        return

    sender_mode = get_user_mode(sender_id)

    # ADMIN → USER
    if sender_mode == "contact_admin":
        user_id = active_contacts.get(sender_id)
        if not user_id or get_user_mode(user_id) != "contact_user":
            _force_close(sender_id, user_id)
            return

        context.bot.copy_message(
            chat_id=user_id,
            from_chat_id=sender_id,
            message_id=msg.message_id,
        )
        return

    # USER → ADMIN
    if sender_mode == "contact_user":
        admin_id = reverse_contacts.get(sender_id)
        if not admin_id or get_user_mode(admin_id) != "contact_admin":
            _force_close(admin_id, sender_id)
            return

        context.bot.copy_message(
            chat_id=admin_id,
            from_chat_id=sender_id,
            message_id=msg.message_id,
        )
        return


# =========================
# /end_contact
# =========================
def cmd_end_contact(update: Update, context: CallbackContext):
    admin_id = update.effective_user.id

    if admin_id not in ADMIN_IDS:
        return

    if get_user_mode(admin_id) != "contact_admin":
        update.message.reply_text("❌ No active contact.")
        return

    user_id = active_contacts.get(admin_id)
    _force_close(admin_id, user_id)
    update.message.reply_text("✅ Contact closed.")


# =========================
# INTERNAL CLOSE
# =========================
def _force_close(admin_id, user_id):
    clear_user_mode(admin_id)
    if user_id:
        clear_user_mode(user_id)

    active_contacts.pop(admin_id, None)
    reverse_contacts.pop(user_id, None)

    logger.info("Contact closed admin=%s user=%s", admin_id, user_id)


# =========================
# SETUP
# =========================
def setup(dispatcher):
    dispatcher.add_handler(CommandHandler("contact", cmd_contact))
    dispatcher.add_handler(CommandHandler("end_contact", cmd_end_contact))
    dispatcher.add_handler(
        CallbackQueryHandler(contact_accept, pattern=r"^contact_accept:")
    )
    dispatcher.add_handler(
        MessageHandler(Filters.all & ~Filters.command, relay_messages)
    )

    logger.info("contact_user feature loaded (STATE-ONLY)")
