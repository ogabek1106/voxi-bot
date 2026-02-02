# features/ad_reciever.py
"""
/ad_rec handler (Aiogram 3).
"""

import logging

from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext

from features.sub_check import require_subscription

logger = logging.getLogger(__name__)

router = Router()


AD_TEXT = (
    "🏆 *MMT (Monthly Mastery Test)* - Ingliz tili daraja testi\n\n"
    "📆 *30-dekabr*\n"
    "⏰ *20:00 da*\n\n"
    "❗️ *Eslatib o'taman bu qanday test:*\n"
    "— 20 ta savol\n"
    "— 20 daqiqa vaqt\n\n"
    "Kim tez va to‘g‘ri topshirsa — o‘sha *WINNER!* 🏆\n\n"
    "💰 *Priz:* 300 000 so‘m 🤑\n\n"
    "📃 Cho‘chimang, o‘zingizni sinab ko‘ring!"
)


# /ad_rec command
@router.message(Command("ad_rec"))
async def ad_rec_command(message: Message, state: FSMContext):
    if not await require_subscription(message, state):
        return
    await message.answer(AD_TEXT, parse_mode="Markdown")

async def emit_ad(message: Message, state: FSMContext):
    if not await require_subscription(message, state):
        return
    await message.answer(AD_TEXT, parse_mode="Markdown")
