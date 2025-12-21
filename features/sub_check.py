# features/sub_check.py
"""
Central subscription gatekeeper for Voxi bot.
Used by ALL features that require EBAI channel subscription.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler

EBAI_CHANNEL = "@ebai_channel"   # 🔁 change once, everywhere updated


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

    text = (
        "🔒 *Access restricted*\n\n"
        "To use *Voxi Bot*, you must subscribe to our official channel.\n\n"
        "👇 Join first, then press *Check subscription*"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Subscribe", url="https://t.me/ebai_channel")],
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

    if is_subscribed(context.bot, user_id):
        query.answer("✅ Subscription confirmed!")
        query.message.reply_text("🎉 Access unlocked. You can now use Voxi Bot.")
    else:
        query.answer("❌ Still not subscribed")
