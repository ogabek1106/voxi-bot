# features/referral.py
from aiogram import Router, Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandStart

from database import (
    add_user_if_new,
    add_referral,
    get_referral_stats,
    mark_referral_confirmed,
)

router = Router()

# ---------- Utils ----------

async def get_referral_link(bot: Bot, user_id: int) -> str:
    me = await bot.get_me()
    return f"https://t.me/{me.username}?start=ref_{user_id}"


def invite_keyboard(ref_link: str) -> InlineKeyboardMarkup:
    text = (
        "\n"
        "<b>🌿 Assalomu alaykum!</b>\n"
        "Sizni Voxi AI botiga taklif qilamiz.\n\n"
        "📚 <b>Bepul testlar</b>\n"
        "🤖 <b>AI yordamchi</b>\n"
        "🏆 <b>Har oy sovrunli MMT testi</b>\n\n"
        "<b>Boshlash uchun shu yerga bosing</b> 👇\n"
        f"{ref_link}"
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 Taklifnoma yuborish", switch_inline_query=text)]
    ])


# ---------- /referral ----------

@router.message(Command("referral"))
async def referral_screen(message: Message, bot: Bot):
    user_id = message.from_user.id

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

@router.message(CommandStart(deep_link=True))
async def start_with_referral(message: Message, bot: Bot):
    user_id = message.from_user.id
    payload = message.text.split(maxsplit=1)
    ref_code = payload[1] if len(payload) > 1 else None

    is_new = add_user_if_new(
        user_id,
        first_name=message.from_user.first_name,
        username=message.from_user.username,
    )

    if ref_code and ref_code.startswith("ref_") and is_new:
        try:
            inviter_id = int(ref_code.replace("ref_", ""))
        except Exception:
            inviter_id = None

        if inviter_id and inviter_id != user_id:
            add_referral(inviter_id, user_id)
            await message.answer(
                "🎉 You joined via a referral link!\n\n"
                "To be counted as confirmed:\n"
                "• just press /start\n"
                "• join the channel"
            )

    # mark as confirmed (basic version: confirmed when user starts bot)
    mark_referral_confirmed(user_id)

    await message.answer("👋 Welcome to Voxi!")
