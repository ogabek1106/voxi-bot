"""
Global AI checker state gate.

Purpose:
- Intercepts messages when user is in AI checker mode
- Allows ONLY checker-related input
- Blocks other commands politely

Modes supported (expandable):
- writing_task2
- speaking (future)
"""

import logging
from typing import Optional

from telegram import Update
from telegram.ext import CallbackContext, MessageHandler, Filters

from database import get_checker_mode

logger = logging.getLogger(__name__)

# ---------------- CONFIG ----------------

# Allowed text length safety (anti-spam / anti-empty)
MIN_TEXT_LEN = 20

# Message shown when user tries other actions
BLOCK_MESSAGE = (
    "✋ Siz hozir AI tekshiruv rejimidasiz.\n\n"
    "✍️ Iltimos, faqat insho matnini yuboring yoki /cancel buyrug‘idan foydalaning."
)

# ---------------- CORE LOGIC ----------------

def _is_checker_active(user_id: Optional[int]) -> Optional[str]:
    if user_id is None:
        return None
    return get_checker_mode(user_id)


def checker_gate(update: Update, context: CallbackContext):
    """
    Intercepts ALL text messages.
    If user is in checker mode → allow or block accordingly.
    """
    message = update.message
    if not message or not message.text:
        return

    user_id = message.from_user.id if message.from_user else None
    mode = _is_checker_active(user_id)

    # Not in checker mode → ignore completely
    if not mode:
        return

    text = message.text.strip()

    # Allow /cancel always
    if text.startswith("/cancel"):
        return

    # Block other commands
    if text.startswith("/"):
        message.reply_text(BLOCK_MESSAGE)
        return

    # Too short → block
    if len(text) < MIN_TEXT_LEN:
        message.reply_text(
            "❗️Matn juda qisqa.\n\n"
            "Iltimos, to‘liq javob yuboring yoki /cancel ni bosing."
        )
        return

    # ✅ Valid checker input → DO NOTHING
    # Let the actual checker handler process it
    logger.debug("checker_state: passing text to active checker (%s)", mode)
    return


# ---------------- REGISTRATION ----------------

def setup(dispatcher):
    """
    Auto-loaded by Voxi feature loader.
    LOW priority so it doesn't override real handlers.
    """
    dispatcher.add_handler(
        MessageHandler(Filters.text & ~Filters.command, checker_gate),
        group=0
    )
