# features/sub_check.py
"""
Central subscription gatekeeper for Voxi bot.
Used by ALL features that require EBAI channel subscription.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler
from telegram import Update
#from telegram.ext import DispatcherHandlerStop

EBAI_CHANNEL = "@IELTSforeverybody"   # 🔁 change once, everywhere updated


# ==========================================================
# DEBUG HELPER (TEMPORARY)
# ==========================================================

#def _debug(update, context, text: str):
    #try:
        #msg = update.effective_message
        #if msg:
            #msg.reply_text(f"🧪 DEBUG:\n{text}")
    #except Exception:
        #pass


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
    Otherwise:
      - stores user intent
      - shows Uzbek subscribe UI
      - returns False
    """

    user = update.effective_user
    bot = context.bot

    if user is None:
        return False

    if is_subscribed(bot, user.id):
        #_debug(update, context, "User IS subscribed → allow")
        return True

    # ==================================================
    # STORE USER INTENT (INTENT-BASED, SAFE)
    # ==================================================
    try:
        args = getattr(context, "args", None)

        # /start <payload>
        if update.message and update.message.text.startswith("/start") and args:
            context.user_data["pending_action"] = {
                "type": "start",
                "payload": args[0]
            }

        # plain /start
        elif update.message and update.message.text == "/start":
            context.user_data["pending_action"] = {
                "type": "start_plain"
            }

        # numeric message (book code)
        elif update.message and update.message.text and update.message.text.strip().isdigit():
            context.user_data["pending_action"] = {
                "type": "numeric",
                "value": update.message.text.strip()
            }

    except Exception:
        pass
    # ==================================================

    #_debug(
        #update,
        #context,
        #f"BLOCKED by subscription\n"
        #f"Stored pending_action = {context.user_data.get('pending_action')}"
    #)

    text = (
        "🔒 *Kirish cheklangan*\n\n"
        "*Voxi Bot*dan foydalanish uchun rasmiy kanalimizga "
        "obuna bo‘lishingiz kerak.\n\n"
        "👇 Avval obuna bo‘ling, so‘ng qaytib kelib *Tekshirish* tugmasini bosing."
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Kanalga obuna bo‘lish", url="https://t.me/IELTSforeverybody")],
        [InlineKeyboardButton("🔄 Obunani tekshirish", callback_data="check_sub")]
    ])

    if update.effective_message:
        update.effective_message.reply_text(
            text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

    return False


# ==========================================================
# CALLBACK: CHECK SUBSCRIPTION
# ==========================================================

def check_subscription_callback(update, context):
    """Handles 🔄 Obunani tekshirish tugmasi"""

    #_debug(update, context, "Entered check_subscription_callback")

    query = update.callback_query
    user_id = query.from_user.id

    if not is_subscribed(context.bot, user_id):
        query.answer("❌ Hali obuna bo‘linmagan")
        #_debug(update, context, "User is STILL NOT subscribed")
        return

    query.answer("✅ Obuna tasdiqlandi!")
    query.message.reply_text(
        "🎉 Obuna muvaffaqiyatli!\n"
        "⏳ So‘rov bajarilmoqda..."
    )

    #_debug(update, context, "User IS subscribed — replaying intent")

    # ==================================================
    # NORMALIZE UPDATE (CRITICAL FIX)
    # ==================================================
    if not update.message and query and query.message:
        update.message = query.message

    # ==================================================
    # REPLAY STORED INTENT (AUTO-RUN)
    # ==================================================
    pending = context.user_data.pop("pending_action", None)

    #_debug(update, context, f"Popped pending_action = {pending}")

    if not pending:
        return

    chat_id = query.message.chat_id

    # 🔹 PRIORITY 1: numeric (message)
    if pending["type"] == "numeric":
        #_debug(update, context, "Replaying NUMERIC action")
        from handlers import send_book_by_code
        send_book_by_code(chat_id, pending["value"], context)
        return

    # 🔹 PRIORITY 2: /start payload
    if pending["type"] == "start":
        payload = pending["payload"].lower()
        #_debug(update, context, f"Replaying START payload = {payload}")

        # ✅ FIX: numeric deep-link (/start 39)
        if payload.isdigit():
            from handlers import send_book_by_code
            send_book_by_code(chat_id, payload, context)
            return

        if payload == "ad_rec":
            from features.ad_reciever import ad_rec_handler
            ad_rec_handler(update, context)
            return

        if payload == "get_test":
            from features.get_test import get_test
            get_test(update, context)
            return

        return

    # 🔹 PRIORITY 3: plain /start
    if pending["type"] == "start_plain":
        #_debug(update, context, "Replaying PLAIN /start")
        from handlers import _send_start_menu
        _send_start_menu(update, context)
        return
    # ==================================================


# ==========================================================
# HANDLER REGISTRATION
# ==========================================================

def setup(dispatcher):
    dispatcher.add_handler(
        CallbackQueryHandler(check_subscription_callback, pattern="^check_sub$")
    )
