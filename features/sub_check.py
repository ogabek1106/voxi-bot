# features/sub_check.py
"""
Central subscription gatekeeper for Voxi bot.
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

EBAI_CHANNEL = "@IELTSforeverybody"

router = Router()


# ==========================================================
# LOW-LEVEL CHECK
# ==========================================================

async def is_subscribed(bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(EBAI_CHANNEL, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False


# ==========================================================
# MAIN GUARD (MESSAGE ONLY)
# ==========================================================

async def require_subscription(message: Message, state: FSMContext) -> bool:
    user = message.from_user
    if not user:
        return False

    if await is_subscribed(message.bot, user.id):
        return True

    # ─────────────────────────────
    # STORE USER INTENT
    # ─────────────────────────────

    pending_action = None
    text = message.text or ""

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        if len(parts) > 1:
            pending_action = {
                "type": "start",
                "payload": parts[1].strip()
            }
        else:
            pending_action = {
                "type": "start_plain"
            }

    elif text.isdigit():
        pending_action = {
            "type": "numeric",
            "value": text
        }

    if pending_action:
        await state.update_data(pending_action=pending_action)

    # ─────────────────────────────
    # SUBSCRIBE UI
    # ─────────────────────────────

    text = (
        "🔒 <b>Kirish cheklangan</b>\n\n"
        "<b>Voxi Bot</b>dan foydalanish uchun rasmiy kanalimizga "
        "obuna bo‘lishingiz kerak.\n\n"
        "👇 Avval obuna bo‘ling, so‘ng <b>Tekshirish</b> tugmasini bosing."
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

    await message.answer(text, reply_markup=keyboard)
    return False


# ==========================================================
# CALLBACK: CHECK SUB
# ==========================================================

@router.callback_query(F.data == "check_sub")
async def check_subscription_callback(callback: CallbackQuery, state: FSMContext):
    user = callback.from_user
    if not user:
        await callback.answer()
        return

    if not await is_subscribed(callback.bot, user.id):
        await callback.answer("❌ Hali obuna bo‘linmagan", show_alert=True)
        await callback.message.answer("📢 Avval kanalga obuna bo‘ling.")
        return

    await callback.answer("✅ Obuna tasdiqlandi!")
    await callback.message.answer("🎉 Obuna muvaffaqiyatli!\n⏳ So‘rov bajarilmoqda...")

    data = await state.get_data()
    pending = data.get("pending_action")
    await state.update_data(pending_action=None)

    if not pending:
        return

    message = callback.message

    # ─────────────────────────────
    # REPLAY INTENT
    # ─────────────────────────────

    # 1️⃣ Numeric (book code)
    if pending["type"] == "numeric":
        from handlers import send_book_by_code
        ok = await send_book_by_code(message, pending["value"])
        if not ok:
            await message.answer("Bunday kod topilmadi.")
        return

    # 2️⃣ /start payload
    if pending["type"] == "start":
        payload = pending["payload"]

        if payload.isdigit():
            from handlers import send_book_by_code
            ok = await send_book_by_code(message, payload)
            if not ok:
                await message.answer("Bunday kod topilmadi.")
            return

        if payload == "get_test":
            from features.get_test import get_test
            await get_test(message)
            return

        return

    # 3️⃣ Plain /start
    if pending["type"] == "start_plain":
        from handlers import start_handler
        await start_handler(message, state)
        return
