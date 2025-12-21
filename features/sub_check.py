# features/sub_check.py
"""
Central subscription gatekeeper for Voxi bot.
Used by ALL features that require EBAI channel subscription.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler

from telegram import Update  # ✅ ADDED (needed for replay)

EBAI_CHANNEL = "@IELTSforeverybody"   # 🔁 change once, everywhere updated


def is_subscribed(bot, user_id: int) -> bool:
    try:
        member = bot.get_chat_member(EBAI_CHANNEL, user_id)
        return member.status in ("member", "administrator", "creator")
    except:
        return False


def require_subscription(update, context) -> bool:
    """
    Universal guard.
    Returns True if user is subscribed.
    Sends block message and returns False otherwise.
    """

    user = update.effective_user
    bot = context.bot

    if user is None:
        return False

    if is_subscribed(bot, user.id):
        return True

    # ================================
    # ✅ ADDED: STORE PENDING ACTION
    # ================================
    try:
        # /start payload (deep links)
        args = getattr(context, "args", None)
        if args:
            context.user_data["pending_start_payload"] = args[0]

        # numeric input (books)
        elif update.message and update.message.text and update.message.text.strip().isdigit():
            context.user_data["pending_numeric"] = update.message.text.strip()
    except Exception:
        pass
    # ================================

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


def check_subscription_callback(update, context):
    """Handles 🔄 Check subscription button"""

    query = update.callback_query
    user_id = query.from_user.id

    if not is_subscribed(context.bot, user_id):
        query.answer("❌ Still not subscribed")
        return

    query.answer("✅ Subscription confirmed!")
    query.message.reply_text("🎉 Access unlocked. Processing your request...")

    # ================================
    # ✅ ADDED: REPLAY PENDING ACTION
    # ================================
    pending_start = context.user_data.pop("pending_start_payload", None)
    pending_numeric = context.user_data.pop("pending_numeric", None)

    # replay /start payload
    if pending_start:
        from handlers import start_handler

        fake_update = Update(
            update.update_id,
            message=query.message
        )
        fake_update.message.text = f"/start {pending_start}"
        fake_update.message.entities = []

        start_handler(fake_update, context)
        return

    # replay numeric input
    if pending_numeric:
        from handlers import numeric_message_handler

        fake_update = Update(
            update.update_id,
            message=query.message
        )
        fake_update.message.text = pending_numeric
        fake_update.message.entities = []

        numeric_message_handler(fake_update, context)
        return
    # ================================
