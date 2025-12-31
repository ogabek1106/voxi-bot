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
   from features.sub_check import require_subscription
   from database import set_checker_mode, clear_checker_mode
   
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
   
   
   # IELTS skills (bottom bar)
   def _ielts_skills_reply_keyboard():
       return ReplyKeyboardMarkup(
           [
               ["✍️ Writing", "🗣️ Speaking (Coming soon)"],
               ["🎧 Listening (Coming soon)", "📖 Reading (Coming soon)"],
               ["⬅️ Back"],
           ],
           resize_keyboard=True
       )
   
   
   # Cancel-only keyboard (checker mode)
   def _checker_cancel_keyboard():
       return ReplyKeyboardMarkup(
           [["❌ Cancel"]],
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
   
       # 🔒 SINGLE ENTRY GATE
       if not require_subscription(update, context):
           return
   
       update.message.reply_text(
           "🎓 *IELTS Check Up*\n"
           "Choose the skill you want to check.",
           reply_markup=_ielts_skills_reply_keyboard(),
           parse_mode="Markdown"
       )
   
   def ielts_skill_text_handler(update: Update, context: CallbackContext):
       """
       Handles ALL reply-keyboard actions for IELTS Check Up
       """
       if not update.message or not update.message.text:
           return
   
       text = update.message.text.strip()
       user = update.effective_user
   
       # ❌ Cancel button (EXACTLY like /cancel)
       if text == "❌ Cancel":
           if user:
               clear_checker_mode(user.id)
   
           update.message.reply_text(
               "❌ Tekshiruv bekor qilindi.",
               reply_markup=_main_user_keyboard()
           )
           return
   
       # ✍️ Writing — ENTER CHECKER MODE (same as /check_writing2)
       if text == "✍️ Writing":
           if not user:
               return
   
           # 1) Explicitly enter checker mode (GLOBAL truth)
           # set_checker_mode(user.id, "writing_task2")
   
           # 2) Lock UI to Cancel-only (UI responsibility ONLY)
           update.message.reply_text(
               "✍️ Writing",
               reply_markup=_checker_cancel_keyboard()
           )
   
           # 3) Start the real Writing checker
           # from features.ai.writing_task2 import start_check
           # start_check(update, context)
           return
   
       # Other skills (future)
       if text in {"🗣️ Speaking", "🎧 Listening", "📖 Reading"}:
           update.message.reply_text("🚧 This section is coming soon.")
           return
   
       # Back to main menu
       if text == "⬅️ Back":
           update.message.reply_text(
               "⬅️ Back to main menu.",
               reply_markup=_main_user_keyboard()
           )
           return
   
   
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
   
       # ReplyKeyboard skill handler
       dispatcher.add_handler(
           MessageHandler(
               Filters.text & Filters.regex(
                   "^(✍️ Writing|🗣️ Speaking|🎧 Listening|📖 Reading|⬅️ Back|❌ Cancel)$"
               ),
               ielts_skill_text_handler
           ),
           group=1
       )
   
       # Old inline handler (kept for compatibility)
       dispatcher.add_handler(
           CallbackQueryHandler(
               ielts_callbacks,
               pattern="^ielts_"
           ),
           group=1
       )
   
   
   def setup(dispatcher):
       register(dispatcher)
   
   
   
   
   
   
   
   
