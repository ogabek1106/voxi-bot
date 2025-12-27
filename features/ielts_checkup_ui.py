# features/ielts_checkup_ui.py
"""
IELTS Check Up UI (User-facing buttons only)

Flow:
1) User presses "🧠 IELTS Check Up" (reply keyboard button)
2) Bot shows skill selection (REPLY KEYBOARD – bottom bar)
3) User selects:
   - ✍️ Writing -> internally starts Writing checker
   - Others -> "Coming soon"
4) ⬅️ Back -> returns to main menu (no state changes)

IMPORTANT:
- NO commands are shown to user
- Writing logic is reused from writing_task2.py
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

logger = logging.getLogger(__name__)

# ---------- UI builders ----------

def _main_user_keyboard():
    return ReplyKeyboardMarkup(
        [["🧠 IELTS Check Up"]],
        resize_keyboard=True
    )


# ✅ NEW: IELTS SKILLS — REPLY KEYBOARD (BOTTOM BAR)
def _ielts_skills_reply_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["✍️ Writing", "🗣️ Speaking"],
            ["🎧 Listening", "📖 Reading"],
            ["⬅️ Back"],
        ],
        resize_keyboard=True
    )


# 🔒 OLD INLINE KEYBOARD (KEPT, NOT USED — DO NOT REMOVE)
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
        reply_markup=_ielts_skills_reply_keyboard(),  # ✅ REPLY KEYBOARD
        parse_mode="Markdown"
    )


# ✅ NEW: HANDLE REPLY KEYBOARD BUTTONS
def ielts_skill_text_handler(update: Update, context: CallbackContext):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if text == "✍️ Writing":
        from features.ai.writing_task2 import start_check
        start_check(update, context)

    elif text in {"🗣️ Speaking", "🎧 Listening", "📖 Reading"}:
        update.message.reply_text("🚧 This section is coming soon.")

    elif text == "⬅️ Back":
        update.message.reply_text(
            "⬅️ Back to main menu.",
            reply_markup=_main_user_keyboard()
        )


# 🔒 OLD INLINE CALLBACK HANDLER (KEPT, NOT USED — DO NOT REMOVE)
def ielts_callbacks(update: Update, context: CallbackContext):
    query = update.callback_query
    if not query:
        return

    query.answer()
    data = query.data
    update.message = query.message

    if data == "ielts_writing":
        from features.ai.writing_task2 import start_check
        start_check(update, context)

    elif data in {"ielts_speaking", "ielts_listening", "ielts_reading"}:
        query.message.reply_text("🚧 This section is coming soon.")

    elif data == "ielts_back":
        query.message.reply_text(
            "⬅️ Back to main menu.",
            reply_markup=_main_user_keyboard()
        )


# ---------- Registration ----------

def register(dispatcher):
    # Open IELTS Check Up
    dispatcher.add_handler(
        MessageHandler(
            Filters.text & Filters.regex("^🧠 IELTS Check Up$"),
            open_ielts_checkup
        ),
        group=1
    )

    # ✅ NEW: ReplyKeyboard skill handler
    dispatcher.add_handler(
        MessageHandler(
            Filters.text & Filters.regex(
                "^(✍️ Writing|🗣️ Speaking|🎧 Listening|📖 Reading|⬅️ Back)$"
            ),
            ielts_skill_text_handler
        ),
        group=1
    )

    # 🔒 OLD inline handler (kept, not active unless inline used)
    dispatcher.add_handler(
        CallbackQueryHandler(
            ielts_callbacks,
            pattern="^ielts_"
        ),
        group=1
    )


def setup(dispatcher):
    register(dispatcher)

