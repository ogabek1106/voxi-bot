# features/ad_reciever.py
"""
/ad_rec handler.

Purpose:
- Handles Telegram ads traffic
- Works for:
    • /ad_rec command
    • /start ad_rec deep link
- Checks channel subscription BEFORE showing details
"""

import logging
from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

from features.sub_check import require_subscription

logger = logging.getLogger(__name__)


# ================== CORE MESSAGE ==================

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


# ================== HANDLER ==================

def ad_rec_handler(update: Update, context: CallbackContext):
    # 🔒 Subscription gate
    if not require_subscription(update, context):
        return

    if update.message:
        update.message.reply_text(
            AD_TEXT,
            parse_mode="Markdown"
        )


# ================== ENTRYPOINT (IMPORTANT) ==================

def setup(dispatcher):
    """
    Required by feature loader
    """
    dispatcher.add_handler(CommandHandler("ad_rec", ad_rec_handler))
