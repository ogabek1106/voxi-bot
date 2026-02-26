# features/referral.py
from aiogram import Router, Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery
from features.sub_check import is_subscribed
from database import (
    add_user_if_new,
    add_referral,
    get_referral_stats,
    mark_referral_confirmed,
    recheck_all_referrals, 
)
from aiogram.filters import CommandStart, Filter

router = Router()

# ---------- Utils ----------

async def get_referral_link(bot: Bot, user_id: int) -> str:
    me = await bot.get_me()
    return f"https://t.me/{me.username}?start=ref_{user_id}"


def invite_keyboard(ref_link: str) -> InlineKeyboardMarkup:
    text = (
        "\n"
        "🌿 **Assalomu alaykum!**\n"
        "Sizni Voxi AI botiga taklif qilamiz.\n\n"
        "📚 **Bepul testlar**\n"
        "🤖 **AI yordamchi**\n"
        "🏆 **Har oy sovrinli MMT testi**\n\n"
        "**Boshlash uchun shu yerga bosing** 👇\n"
        f"{ref_link}"
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 Taklifnoma yuborish", switch_inline_query=text)]
    ])


# ---------- /referral ----------

@router.message(Command("referral"))
async def referral_screen(message: Message, bot: Bot):
    user_id = message.from_user.id

    # 🔁 LIVE referral recheck (confirmed + not confirmed)
    await recheck_all_referrals(bot, user_id, is_subscribed)

    ref_link = await get_referral_link(bot, user_id)
    stats = get_referral_stats(user_id)
    
    text = (
        "🤝 <b>Do'stingizni taklif qiling</b>\n\n"
        "🔗 <b>Sizning shaxsiy havolangiz</b>\n"
        "<i>(Copy and send to your friends)</i>\n\n"
        f"{ref_link}\n\n"
        "👥 <b>Your progress</b>\n"
        f"• You invited: <b>{stats['invited']}</b>\n"
        f"✅ Confirmed: <b>{stats['confirmed']}</b>\n"
        f"⏳ Not confirmed: <b>{stats['not_confirmed']}</b>\n\n"
        "ℹ️ <b>What does “confirmed” mean?</b>\n"
        "A friend is confirmed when they:\n"
        "– start the bot\n"
        "– join the channel\n\n"
        "🏆 <b>These invites count toward your MMT bonus.</b>"
    )

    await message.answer(
        text,
        reply_markup=invite_keyboard(ref_link),
        parse_mode="HTML",
        disable_web_page_preview=True
    )


# ---------- /start with referral ----------
class RefDeepLink(Filter):
    async def __call__(self, message: Message) -> bool:
        parts = message.text.split(maxsplit=1)
        return len(parts) > 1 and parts[1].startswith("ref_")

@router.message(CommandStart(deep_link=True), RefDeepLink())
async def start_with_referral(message: Message, bot: Bot):
    user_id = message.from_user.id
    payload = message.text.split(maxsplit=1)
    ref_code = payload[1]

    add_user_if_new(
        user_id,
        first_name=message.from_user.first_name,
        username=message.from_user.username,
    )

    try:
        inviter_id = int(ref_code.replace("ref_", ""))
    except Exception:
        return

    if inviter_id == user_id:
        return

    add_referral(inviter_id, user_id)

    text = (
        "🎉 Siz taklifnoma orqali kirdingiz!\n\n"
        "Tasdiqlangan (confirmed) bo‘lish uchun:\n"
        "1️⃣ Kanalga obuna bo‘ling\n"
        "2️⃣ So‘ng <b>Statusni tekshirish</b> tugmasini bosing\n\n"
        "✅ Shundan keyin sizni taklif qilgan do‘stingiz hisobiga yozilasiz."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="📢 Kanalga obuna bo‘lish",
                url="https://t.me/IELTSforeverybody"
            )
        ],
        [
            InlineKeyboardButton(
                text="🔄 Statusni tekshirish",
                callback_data="check_referral_sub"
            )
        ]
    ])

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

@router.callback_query(lambda c: c.data == "check_referral_sub")
async def check_referral_subscription(callback: CallbackQuery):
    user = callback.from_user
    if not user:
        await callback.answer()
        return

    if not await is_subscribed(callback.bot, user.id):
        await callback.answer("❌ Hali kanalga obuna bo‘linmagan", show_alert=True)
        await callback.message.answer("📢 Avval kanalga obuna bo‘ling.")
        return

    ok = mark_referral_confirmed(user.id)

    if ok:
        await callback.answer("✅ Tasdiqlandi!")
        await callback.message.answer(
            "🎉 Ajoyib! Sizning statusingiz tasdiqlandi.\n\n"
            "Endi bu status sizni taklif qilgan do‘stingiz hisobiga yozildi."
        )
    else:
        await callback.answer("ℹ️ Allaqachon tasdiqlangan", show_alert=True)
