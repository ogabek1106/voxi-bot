# features/checker_state.py
"""
Global AI checker HARD gate.

Blocks EVERYTHING when checker mode is active.
Allows ONLY:
- /cancel
- valid checker input
"""

import logging
from typing import Optional

from telegram import Update
from telegram.ext import CallbackContext, MessageHandler, Filters
from telegram.ext import DispatcherHandlerStop

from database import get_checker_mode, clear_checker_mode  # ✅ ADDED (DO NOT REMOVE get_checker_mode)

logger = logging.getLogger(__name__)

# ---------------- CONFIG ----------------

MIN_TEXT_LEN = 20

BLOCK_MESSAGE = (
    "✋ Siz hozir AI tekshiruv rejimidasiz.\n\n"
    "✍️ Iltimos, faqat insho matnini yuboring yoki /cancel buyrug‘idan foydalaning."
)

# ---------------- CORE ----------------

def _is_checker_active(user_id: Optional[int]) -> Optional[str]:
    if user_id is None:
        return None
    return get_checker_mode(user_id)


def checker_gate(update: Update, context: CallbackContext):
    """
    HARD global interceptor.
    Runs BEFORE everything else.
    """
    message = update.effective_message
    if not message:
        return

    user = update.effective_user
    user_id = user.id if user else None

    mode = _is_checker_active(user_id)

    # Not in checker mode → allow everything
    if not mode:
        return

    text = message.text.strip() if message.text else ""

    # ✅ HANDLE /cancel HERE (FIX)
    if text.startswith("/cancel"):
        clear_checker_mode(user_id)
        message.reply_text("❌ AI tekshiruv rejimi bekor qilindi.")
        raise DispatcherHandlerStop()

    # ❌ Block ALL other commands
    if text.startswith("/"):
        message.reply_text(BLOCK_MESSAGE)
        raise DispatcherHandlerStop()

    # ❌ Block non-text (photos, pdfs, voice, etc.)
    if not message.text:
        message.reply_text(BLOCK_MESSAGE)
        raise DispatcherHandlerStop()

    # ❌ Block short text
    if len(text) < MIN_TEXT_LEN:
        message.reply_text(
            "❗️Matn juda qisqa.\n\n"
            "Iltimos, to‘liq javob yuboring yoki /cancel ni bosing."
        )
        raise DispatcherHandlerStop()

    # ✅ Valid checker input → allow ONLY checker handlers
    logger.debug("checker_gate: passing to checker (%s)", mode)
    return


# ---------------- REGISTRATION ----------------

def setup(dispatcher):
    """
    MUST be registered before EVERYTHING.
    """
    dispatcher.add_handler(
        MessageHandler(Filters.all, checker_gate),
        group=-1000
    )
