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
from database import clear_user_mode
from database import set_user_mode
from database import get_user_mode
from telegram.ext import (
    CallbackContext,
    MessageHandler,
    Filters,
    CallbackQueryHandler,
    #DispatcherHandlerStop,
)
from features.debug_hard import debug_hard
from telegram.ext import MessageHandler, Filters
IELTS_MODE = "ielts_check_up"

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
            ["⬅️ Back to main menu"],
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

    user = update.effective_user
    if user and get_user_mode(user.id) == "create_test":
        return

    # ✅ SET MODE HERE
    set_user_mode(user.id, IELTS_MODE)

    update.message.reply_text(
        "🎓 *IELTS Check Up*\nChoose the skill you want to check.",
        reply_markup=_ielts_skills_reply_keyboard(),
        parse_mode="Markdown"
    )

def ielts_skill_text_handler(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user:
        return

    # ✅ MODE GATE (FIRST)
    if get_user_mode(user.id) != IELTS_MODE:
        return

    text = update.message.text.strip()

    # ⬅️ Back to main menu (HARD RESET)
    if text == "⬅️ Back to main menu":
        _exit_active_checker_if_any(user.id, context, reason="main menu back")
        clear_user_mode(user.id)

        update.message.reply_text(
            "⬅️ Back to main menu.",
            reply_markup=_main_user_keyboard()
        )
        return


    # ❌ Cancel
    if text == "❌ Cancel":
        # If checker is active → DO NOTHING (ConversationHandler owns it)
        if user and get_checker_mode(user.id):
            return

        # UI-only cancel (no active checker)
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
    # if text == "📝 Writing Task 1":
        # return

    # 🧠 Writing Task 2
    # if text == "🧠 Writing Task 2":
        # return

    # 🗣️ Speaking (READY)
    if text == "🗣️ Speaking":
        update.message.reply_text(
            "🗣️ Speaking bo‘limini tanlang:",
            reply_markup=_speaking_submenu_keyboard(),
            parse_mode="Markdown"
        )
        return

    # ⬅️ Back (SUBMENU BACK → clear INNER ONLY)
    if text == "⬅️ Back":
        _exit_active_checker_if_any(user.id, context, reason="submenu back")

        update.message.reply_text(
            "🎓 *IELTS Check Up*\nChoose the skill you want to check.",
            reply_markup=_ielts_skills_reply_keyboard(),
            parse_mode="Markdown"
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
                "^(✍️ Writing|🗣️ Speaking|🎧 Listening|📖 Reading|⬅️ Back|⬅️ Back to main menu|❌ Cancel)$"
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

def _exit_active_checker_if_any(user_id, context, reason: str):
    """
    UI-safe checker cleanup.
    - Clears inner ConversationHandler state
    - Clears checker_mode
    - Does NOTHING if no checker is active
    """
    from global_cleaner import clean_user
    from database import get_checker_mode, clear_checker_mode

    if not get_checker_mode(user_id):
        return  # ✅ No checker → do not interfere

    clean_user(user_id, reason=reason)
    clear_checker_mode(user_id)
    context.user_data.clear()




def setup(dispatcher):
    # dispatcher.add_handler(
        # MessageHandler(Filters.text, debug_hard),
        # group=0
    # )

    register(dispatcher)


