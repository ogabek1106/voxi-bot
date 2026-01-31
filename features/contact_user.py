# features/contact_user.py
"""
Admin-only direct contact feature (STATE-ONLY).

Invitation is validated via runtime registry.
Bridge is validated via STATES only.
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
# RUNTIME REGISTRIES
# =========================
pending_invitations = {}   # admin_id -> user_id
active_contacts = {}       # admin_id -> user_id
reverse_contacts = {}      # user_id -> admin_id


# =========================
# /contact <user_id>
# =========================
def cmd_contact(update: Update, context: CallbackContext):
    admin_id = update.effective_user.id

    if admin_id not in ADMIN_IDS:
        return

    if not context.args or not context.args[0].isdigit():
        update.message.reply_text("Usage: /contact <user_id>")
        return

    user_id = int(context.args[0])

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes", callback_data=f"contact_confirm:{user_id}"),
            InlineKeyboardButton("❌ No", callback_data="contact_cancel"),
        ]
    ])

    update.message.reply_text(
        f"👤 User found: {user_id}\n\nSend contact invitation?",
        reply_markup=kb,
    )


# =========================
# ADMIN CONFIRM / CANCEL
# =========================
def contact_confirm(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    admin_id = query.from_user.id
    data = query.data

    if admin_id not in ADMIN_IDS:
        return

    if data == "contact_cancel":
        query.edit_message_text("❌ Contact cancelled.")
        return

    if not data.startswith("contact_confirm:"):
        return

    user_id = int(data.split(":")[1])

    pending_invitations[admin_id] = user_id

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Accept",
                callback_data=f"contact_accept:{admin_id}"
            )
        ]
    ])

    context.bot.send_message(
        chat_id=user_id,
        text=(
            "📩 Admin wants to contact you.\n\n"
            "Press ✅ Accept to start communication."
        ),
        reply_markup=kb,
    )

    query.edit_message_text("📨 Invitation sent to user.")
    context.bot.send_message(
        chat_id=admin_id,
        text="📨 Invitation sent. Waiting for user response.",
    )


# =========================
# USER ACCEPTS
# =========================
def contact_accept(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    user_id = query.from_user.id
    admin_id = int(query.data.split(":")[1])

    expected_user = pending_invitations.get(admin_id)
    if expected_user != user_id:
        query.edit_message_text("❌ Invitation expired.")
        return

    pending_invitations.pop(admin_id, None)

    clear_user_mode(user_id)
    clear_user_mode(admin_id)

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

    mode = get_user_mode(sender_id)

    # ADMIN → USER
    if mode == "contact_admin":
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
    if mode == "contact_user":
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

    user_id = active_contacts.get(admin_id)
    if not user_id:
        update.message.reply_text("❌ No active contact.")
        return

    _force_close(admin_id, user_id)
    update.message.reply_text("✅ Contact closed.")


# =========================
# HARD CLOSE
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
        CallbackQueryHandler(contact_confirm, pattern=r"^contact_(confirm|cancel)")
    )
    dispatcher.add_handler(
        CallbackQueryHandler(contact_accept, pattern=r"^contact_accept:")
    )
    dispatcher.add_handler(
        MessageHandler(Filters.all & ~Filters.command, relay_messages)
    )

    logger.info("contact_user feature loaded")
