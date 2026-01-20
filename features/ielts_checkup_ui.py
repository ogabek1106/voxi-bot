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
#from features.sub_check import require_subscription
from database import set_checker_mode, clear_checker_mode
from database import get_checker_mode
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
    #DispatcherHandlerStop,
)

logger = logging.getLogger(__name__)

# ---------- UI builders ----------

def _main_user_keyboard():
    return ReplyKeyboardMarkup(
        [["🧠 IELTS Check Up"]],
        resize_keyboard=True
    )


def _ielts_skills_reply_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["✍️ Writing", "🗣️ Speaking"],
            ["🎧 Listening", "📖 Reading"],
            ["⬅️ Back"],
        ],
        resize_keyboard=True
    )

def _writing_submenu_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["📝 Writing Task 1"],
            ["🧠 Writing Task 2"],
            ["⬅️ Back"],
        ],
        resize_keyboard=True
    )


def _checker_cancel_keyboard():
    return ReplyKeyboardMarkup(
        [["❌ Cancel"]],
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

def _speaking_submenu_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["🗣️ Part 1 – Introduction"],
            ["🗣️ Part 2 – Cue Card"],
            ["🗣️ Part 3 – Discussion"],
            ["⬅️ Back"],
        ],
        resize_keyboard=True
    )

# ---------- Handlers ----------

def open_ielts_checkup(update: Update, context: CallbackContext):
    if not update.message:
        return

    #if not require_subscription(update, context):
        #raise DispatcherHandlerStop  # ⬅️ THIS IS THE KEY

    update.message.reply_text(
        "🎓 *IELTS Check Up*\nChoose the skill you want to check.",
        reply_markup=_ielts_skills_reply_keyboard(),
        parse_mode="Markdown"
    )


def ielts_skill_text_handler(update: Update, context: CallbackContext):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    user = update.effective_user
    logger.error(
        "🧱 UI HANDLER HIT | text=%r | checker_mode=%s",
        update.message.text,
        get_checker_mode(user.id) if user else None
    )

    # 🚫 If any checker is active, DO NOT intercept messages
    #if user and get_checker_mode(user.id):
        # return

    # ❌ Cancel (UI-level only, NOT checker-level)
    if text == "❌ Cancel":
        # If a checker is active, let ConversationHandler handle it
        if user and get_checker_mode(user.id):
            return

        if user:
            clear_checker_mode(user.id)

        update.message.reply_text(
            "❌ Tekshiruv bekor qilindi.",
            reply_markup=_ielts_skills_reply_keyboard()
        )
        return

    # ✍️ Writing main button
    if text == "✍️ Writing":
        update.message.reply_text(
            "✍️ Writing bo‘limini tanlang:",
            reply_markup=_writing_submenu_keyboard(),
            parse_mode="Markdown"
        )
        return

    # 📝 Writing Task 1
    if text == "📝 Writing Task 1":
        return

    # 🧠 Writing Task 2
    if text == "🧠 Writing Task 2":
        return

    # 🗣️ Speaking (READY)
    if text == "🗣️ Speaking":
        update.message.reply_text(
            "🗣️ Speaking bo‘limini tanlang:",
            reply_markup=_speaking_submenu_keyboard(),
            parse_mode="Markdown"
        )
        return

    # 🚧 Coming soon
    if text in {"📖 Reaing"}:
        update.message.reply_text("🚧 This section is coming soon.")
        return

    # ⬅️ Back
    if text == "⬅️ Back":
        update.message.reply_text(
            "⬅️ Back to main menu.",
            reply_markup=_main_user_keyboard()
        )
        return



def ielts_callbacks(update: Update, context: CallbackContext):
    query = update.callback_query
    if not query:
        return

    query.answer()
    data = query.data
    update.message = query.message

    if data == "ielts_writing":
        query.message.reply_text(
            "✍️ Writing bo‘limini tanlang:",
            reply_markup=_writing_submenu_keyboard()
        )

    elif data in {"ielts_speaking", "ielts_listening", "ielts_reading"}:
        query.message.reply_text("🚧 This section is coming soon.")

    elif data == "ielts_back":
        query.message.reply_text(
            "⬅️ Back to main menu.",
            reply_markup=_main_user_keyboard()
        )


def register(dispatcher):
    dispatcher.add_handler(
        MessageHandler(
            Filters.text & Filters.regex("^🧠 IELTS Check Up$"),
            open_ielts_checkup
        ),
        group=1
    )

    dispatcher.add_handler(
        MessageHandler(
            Filters.regex(
                "^(✍️ Writing|🗣️ Speaking|🎧 Listening|📖 Reading|⬅️ Back|❌ Cancel)$"
            ),
            ielts_skill_text_handler
        ),
        group=1
    )

    dispatcher.add_handler(
        CallbackQueryHandler(
            ielts_callbacks,
            pattern="^ielts_"
        ),
        group=1
    )



def setup(dispatcher):
    register(dispatcher)


