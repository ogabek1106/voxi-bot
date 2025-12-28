# features/sub_check.py
"""
Central subscription gatekeeper for Voxi bot.
Used by ALL features that require EBAI channel subscription.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler
from telegram import Update

EBAI_CHANNEL = "@IELTSforeverybody"   # 🔁 change once, everywhere updated


# ==========================================================
# SUBSCRIPTION CHECK
# ==========================================================

def is_subscribed(bot, user_id: int) -> bool:
    try:
        member = bot.get_chat_member(EBAI_CHANNEL, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False


# ==========================================================
# MAIN GATE
# ==========================================================

def require_subscription(update, context) -> bool:
    """
    Universal guard.
    Returns True if user is subscribed.
    Otherwise stores intent, shows subscribe UI, returns False.
    """

    user = update.effective_user
    bot = context.bot

    if user is None:
        return False

    if is_subscribed(bot, user.id):
        return True

    # ==================================================
    # STORE USER INTENT (NO TEXT, NO FAKE COMMANDS)
    # ==================================================
    try:
        # /start payload (deep links)
        args = getattr(context, "args", None)
        if args:
            context.user_data["pending_action"] = {
                "type": "start",
                "payload": args[0]
            }

        # numeric input (book code)
        elif update.message and update.message.text and update.message.text.strip().isdigit():
            context.user_data["pending_action"] = {
                "type": "numeric",
                "value": update.message.text.strip()
            }
    except Exception:
        pass
    # ==================================================

    text = (
        "🔒 *Access restricted*\n\n"
        "To use *Voxi Bot*, you must subscribe to our official channel.\n\n"
        "👇 Join first, then press *Check subscription*"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Subscribe", url="https://t.me/IELTSforeverybody")],
        [InlineKeyboardButton("🔄 Check subscription", callback_data="check_sub")]
    ])

    if update.message:
        update.message.reply_text(
            text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    elif update.callback_query:
        update.callback_query.answer()
        update.callback_query.message.reply_text(
            text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

    return False


# ==========================================================
# CALLBACK: CHECK SUBSCRIPTION
# ==========================================================

def check_subscription_callback(update, context):
    """Handles 🔄 Check subscription button"""

    query = update.callback_query
    user_id = query.from_user.id

    if not is_subscribed(context.bot, user_id):
        query.answer("❌ Still not subscribed")
        return

    query.answer("✅ Subscription confirmed!")
    query.message.reply_text("🎉 Access unlocked. Processing your request...")

    # ==================================================
    # REPLAY STORED INTENT (NO FAKE UPDATES)
    # ==================================================
    pending = context.user_data.pop("pending_action", None)
    if not pending:
        return

    chat_id = query.message.chat_id

    # 🔹 PRIORITY 1: numeric (book)
    if pending["type"] == "numeric":
        from handlers import send_book_by_code
        send_book_by_code(chat_id, pending["value"], context)
        return

    # 🔹 PRIORITY 2: start payload
    if pending["type"] == "start":
        payload = pending["payload"].lower()

        if payload == "ad_rec":
            from features.ad_reciever import ad_rec_handler
            ad_rec_handler(update, context)
            return

        if payload == "get_test":
            from features.get_test import get_test
            get_test(update, context)
            return

        # Unknown payload → ignore safely
        return
    # ==================================================


# ==========================================================
# HANDLER REGISTRATION
# ==========================================================

def setup(dispatcher):
    dispatcher.add_handler(
        CallbackQueryHandler(check_subscription_callback, pattern="^check_sub$")
    )
