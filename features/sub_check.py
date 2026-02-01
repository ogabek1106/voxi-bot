# features/sub_check.py
"""
Central subscription gatekeeper for Voxi bot.
Used by ALL features that require EBAI channel subscription.
Aiogram 3 version.
"""

from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.fsm.context import FSMContext

EBAI_CHANNEL = "@IELTSforeverybody"   # 🔁 change once, everywhere updated

router = Router()


# ==========================================================
# SUBSCRIPTION CHECK (LOW LEVEL)
# ==========================================================

async def is_subscribed(bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(EBAI_CHANNEL, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False


# ==========================================================
# MAIN GATE (USED BY FEATURES)
# ==========================================================

async def require_subscription(message: Message, state: FSMContext) -> bool:
    """
    Universal guard.
    Returns True if user is subscribed.
    Otherwise:
      - stores user intent (FSM data)
      - shows Uzbek subscribe UI
      - returns False
    """

    user = message.from_user
    if not user:
        return False

    if await is_subscribed(message.bot, user.id):
        return True

    # ==================================================
    # STORE USER INTENT (SAFE, INTENT-BASED)
    # ==================================================

    pending_action = None
    text = message.text or ""

    # /start <payload>
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        if len(parts) > 1:
            pending_action = {
                "type": "start",
                "payload": parts[1]
            }
        else:
            pending_action = {
                "type": "start_plain"
            }

    # numeric message (book code)
    elif text.isdigit():
        pending_action = {
            "type": "numeric",
            "value": text
        }

    if pending_action:
        await state.update_data(pending_action=pending_action)

    # ==================================================
    # SUBSCRIBE UI
    # ==================================================

    text = (
        "🔒 *Kirish cheklangan*\n\n"
        "*Voxi Bot*dan foydalanish uchun rasmiy kanalimizga "
        "obuna bo‘lishingiz kerak.\n\n"
        "👇 Avval obuna bo‘ling, so‘ng qaytib kelib *Tekshirish* tugmasini bosing."
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📢 Kanalga obuna bo‘lish",
                    url="https://t.me/IELTSforeverybody"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Obunani tekshirish",
                    callback_data="check_sub"
                )
            ]
        ]
    )

    await message.answer(
        text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

    return False


# ==========================================================
# CALLBACK: CHECK SUBSCRIPTION
# ==========================================================

@router.callback_query(F.data == "check_sub")
async def check_subscription_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id

    if not await is_subscribed(callback.bot, user_id):
        await callback.answer("❌ Hali obuna bo‘linmagan", show_alert=True)
        return

    await callback.answer("✅ Obuna tasdiqlandi!")
    await callback.message.answer(
        "🎉 Obuna muvaffaqiyatli!\n"
        "⏳ So‘rov bajarilmoqda..."
    )

    data = await state.get_data()
    pending = data.pop("pending_action", None)
    await state.set_data(data)

    if not pending:
        return

    chat_id = callback.message.chat.id

    # ==================================================
    # REPLAY STORED INTENT
    # ==================================================

    # 🔹 PRIORITY 1: numeric message
    if pending["type"] == "numeric":
        from handlers import send_book_by_code
        await send_book_by_code(callback.message, pending["value"])
        return

    # 🔹 PRIORITY 2: /start payload
    if pending["type"] == "start":
        payload = pending["payload"].lower()

        if payload.isdigit():
            from handlers import send_book_by_code
            await send_book_by_code(callback.message, payload)
            return

        if payload == "ad_rec":
            from features.ad_reciever import ad_rec_handler
            await ad_rec_handler(callback.message)
            return

        if payload == "get_test":
            from features.get_test import get_test
            await get_test(callback.message)
            return

        return

    # 🔹 PRIORITY 3: plain /start
    if pending["type"] == "start_plain":
        from handlers import start_handler
        await start_handler(callback.message, state)
        return
