# features/remove_token.py
import logging
from telegram import Update
from telegram.ext import (
    Dispatcher,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
)

import database  # your existing database.py

logger = logging.getLogger(__name__)

ASK_ID = 1

#   IMPORTANT:
#   Your TEST TOKEN table must have something like:
#   tokens(user_id INTEGER PRIMARY KEY, token TEXT)
#   If different name → tell me and I will adjust.


# ---- CHECK ADMIN ----
def is_admin(user_id: int) -> bool:
    # Put your real admin ID here
    ADMIN_ID = 123456789
    return user_id == ADMIN_ID


# ---- ENTRY COMMAND ----
def remove_token_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id

    if not is_admin(user_id):
        update.message.reply_text("⛔ Bu buyruq faqat admin uchun.")
        return ConversationHandler.END

    update.message.reply_text(
        "🧹 Qaysi tokenlarni o‘chiramiz?\n\n"
        "👉 *ALL* deb yuboring — barcha foydalanuvchilarning tokenlari o‘chiriladi\n"
        "👉 Yoki *foydalanuvchi ID* yuboring",
        parse_mode="Markdown",
    )
    return ASK_ID


# ---- PROCESS ADMIN INPUT ----
def process_token_removal(update: Update, context: CallbackContext):
    admin_id = update.effective_user.id
    text = update.message.text.strip()

    if not is_admin(admin_id):
        update.message.reply_text("⛔ Sizga ruxsat yo‘q.")
        return ConversationHandler.END

    # ---- REMOVE ALL TOKENS ----
    if text.upper() == "ALL":
        try:
            database.clear_all_tokens()  # <-- YOU MUST HAVE THIS FUNCTION
            update.message.reply_text("✅ Barcha tokenlar muvaffaqiyatli o‘chirildi.")
        except Exception as e:
            logger.exception(e)
            update.message.reply_text("❌ Tokenlarni o‘chirishda xatolik.")
        return ConversationHandler.END

    # ---- REMOVE SPECIFIC USER TOKEN ----
    if not text.isdigit():
        update.message.reply_text("❗ Iltimos, faqat ID yoki 'ALL' yuboring.")
        return ASK_ID

    target_id = int(text)

    try:
        ok = database.clear_user_token(target_id)  # <-- YOU MUST HAVE THIS FUNCTION
        if ok:
            update.message.reply_text(f"✅ Foydalanuvchi {target_id} tokeni o‘chirildi.")
        else:
            update.message.reply_text(f"ℹ️ Bu foydalanuvchi uchun token topilmadi.")
    except Exception as e:
        logger.exception(e)
        update.message.reply_text("❌ Tokenni o‘chirishda xatolik.")

    return ConversationHandler.END


# ---- CANCEL ----
def cancel(update: Update, context: CallbackContext):
    update.message.reply_text("Bekor qilindi.")
    return ConversationHandler.END


# ---- SETUP ----
def setup(dispatcher: Dispatcher):

    conv = ConversationHandler(
        entry_points=[CommandHandler("remove_token", remove_token_command)],
        states={
            ASK_ID: [
                MessageHandler(Filters.text & ~Filters.command, process_token_removal)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="remove_token_conv",
        persistent=False,
    )

    dispatcher.add_handler(conv)

    logger.info("Feature loaded: remove_token")
