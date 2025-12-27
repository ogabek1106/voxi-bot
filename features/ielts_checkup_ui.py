# features/ielts_checkup_ui.py
"""
IELTS Check Up UI (User-facing buttons only)

Flow:
1) User presses "🧠 IELTS Check Up" (reply keyboard button)
2) Bot shows skill selection (inline buttons)
3) User selects:
   - ✍️ Writing -> internally starts Writing checker
   - Others -> "Coming soon"
4) ⬅️ Back -> returns to main menu (no state changes)

IMPORTANT:
- NO commands are shown to user
- Writing logic is reused from check_writing2.py
- This file contains UI ONLY
"""

import logging

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    CallbackContext,
    MessageHandler,
    Filters,
    CallbackQueryHandler,
)

# 🔗 Reuse existing Writing checker entry point
# from features.ai.import start_check

logger = logging.getLogger(__name__)

# ---------- UI builders ----------

def _main_user_keyboard():
    return ReplyKeyboardMarkup(
        [["🧠 IELTS Check Up"]],
        resize_keyboard=True
    )


def _ielts_skills_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ Writing", callback_data="ielts_writing")],
        [InlineKeyboardButton("🗣️ Speaking", callback_data="ielts_speaking")],
        [InlineKeyboardButton("🎧 Listening", callback_data="ielts_listening")],
        [InlineKeyboardButton("📖 Reading", callback_data="ielts_reading")],
        [InlineKeyboardButton("⬅️ Back", callback_data="ielts_back")],
    ])


# ---------- Handlers ----------

def open_ielts_checkup(update: Update, context: CallbackContext):
    """
    Triggered when user presses "🧠 IELTS Check Up"
    """
    if not update.message:
        return

    update.message.reply_text(
        "🎓 *IELTS Check Up*\n"
        "Choose the skill you want to check.",
        reply_markup=_ielts_skills_keyboard(),
        parse_mode="Markdown"
    )


def ielts_callbacks(update: Update, context: CallbackContext):
    """
    Handles inline button clicks inside IELTS Check Up
    """
    query = update.callback_query
    if not query:
        return

    query.answer()
    data = query.data

    # Make update.message available for reused handlers
    update.message = query.message

    if data == "ielts_writing":
        from features.ai.check_writing2 import start_check
        start_check(update, context)

    elif data in {"ielts_speaking", "ielts_listening", "ielts_reading"}:
        query.message.reply_text(
            "🚧 This section is coming soon."
        )

    elif data == "ielts_back":
        query.message.reply_text(
            "⬅️ Back to main menu.",
            reply_markup=_main_user_keyboard()
        )


# ---------- Registration ----------

def register(dispatcher):
    # Open IELTS Check Up (user UI)
    dispatcher.add_handler(
        MessageHandler(
            Filters.text & Filters.regex("^🧠 IELTS Check Up$"),
            open_ielts_checkup
        ),
        group=1
    )

    # Handle inline buttons
    dispatcher.add_handler(
        CallbackQueryHandler(
            ielts_callbacks,
            pattern="^ielts_"
        ),
        group=1
    )


def setup(dispatcher):
    register(dispatcher)

