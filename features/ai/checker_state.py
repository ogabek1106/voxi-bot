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
from telegram.ext import (
    CallbackContext,
    MessageHandler,
    Filters,
    DispatcherHandlerStop,
)

from database import (
    get_checker_mode,
    clear_checker_mode,
    get_user_mode,
)

from features.ielts_checkup_ui import _main_user_keyboard

logger = logging.getLogger(__name__)

# ---------------- CONFIG ----------------

MIN_TEXT_LEN = 20

BLOCK_MESSAGE = (
    "✋ Siz hozir AI tekshiruv rejimidasiz.\n\n"
    "Iltimos, to‘g‘ri formatdagi javobni yuboring yoki /cancel buyrug‘idan foydalaning."
)

# ---------------- CORE ----------------

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

    # ✅ ABSOLUTE BYPASS FOR TEST CREATION
    if user_id and get_user_mode(user_id) == "create_test":
        return

    mode = get_checker_mode(user_id)

    # Not in checker mode → allow everything
    if not mode:
        return

    text = message.text.strip() if message.text else ""

    # ✅ ALWAYS ALLOW CANCEL
    if text.startswith("/cancel") or text == "❌ Cancel":
        clear_checker_mode(user_id)
        message.reply_text(
            "❌ AI tekshiruv rejimi bekor qilindi.",
            reply_markup=_main_user_keyboard()
        )
        raise DispatcherHandlerStop()

    # ❌ Block ALL other commands
    if text.startswith("/"):
        message.reply_text(BLOCK_MESSAGE)
        raise DispatcherHandlerStop()

    checker_step = context.user_data.get("checker_step")

    # ======================================================
    # ✍️ WRITING MODES → TEXT / PHOTO ONLY
    # ======================================================
    if mode in ("writing_task1", "writing_task2"):

        if message.voice:
            message.reply_text(
                "✋ Siz hozir Writing tekshiruvdasiz.\n\n"
                "✍️ Iltimos, inshoni MATN yoki RASM sifatida yuboring.\n"
                "🎙 Ovozli javob Speaking bo‘limi uchun.\n\n"
                "Agar xato bosgan bo‘lsangiz, /cancel."
            )
            raise DispatcherHandlerStop()

        if not message.text and not message.photo:
            message.reply_text(BLOCK_MESSAGE)
            raise DispatcherHandlerStop()

        if message.text and len(text) < MIN_TEXT_LEN:
            message.reply_text(
                "❗️Matn juda qisqa.\n\n"
                "Iltimos, to‘liq javob yuboring yoki /cancel ni bosing."
            )
            raise DispatcherHandlerStop()

    # ======================================================
    # 🎤 SPEAKING MODES → STEP-AWARE
    # ======================================================
    if mode in ("speaking_part1", "speaking_part2", "speaking_part3"):

        if checker_step == "speaking_topic":
            if not (message.text or message.photo or message.voice):
                message.reply_text(
                    "❗️Iltimos, Speaking savolini MATN, RASM yoki OVOZ orqali yuboring.\n\n"
                    "Yoki /cancel."
                )
                raise DispatcherHandlerStop()

        elif checker_step == "speaking_answer":
            if not message.voice:
                message.reply_text(
                    "🎙 Endi faqat OVOZLI javob yuboring yoki /cancel."
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
