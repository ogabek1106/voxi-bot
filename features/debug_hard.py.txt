# features/debug_hard.py

from telegram import Update
from telegram.ext import CallbackContext
import logging

logger = logging.getLogger(__name__)

def debug_hard(update: Update, context: CallbackContext):
    if not update.message or not update.message.text:
        return

    uid = update.effective_user.id if update.effective_user else None
    text = update.message.text

    msg = (
        "🟥 DEBUG_HARD HIT\n"
        f"text: {text!r}\n"
        f"user_data: {dict(context.user_data)}"
    )

    # HARD signal: both log AND reply
    logger.error(msg)
    update.message.reply_text(msg)
