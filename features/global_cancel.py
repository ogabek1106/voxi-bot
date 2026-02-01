import logging
from typing import Optional

from telegram import Update
from telegram.ext import CallbackContext, CommandHandler
from global_cleaner import clean_user

from database import clear_all_user_modes
import admins

logger = logging.getLogger(__name__)


# ---------- helpers ----------

def _is_admin(user_id: Optional[int]) -> bool:
    raw = getattr(admins, "ADMIN_IDS", []) or []
    return user_id is not None and int(user_id) in {int(x) for x in raw}


# ---------- /cancel (ANY USER) ----------

def global_cancel(update: Update, context: CallbackContext):
    """
    Universal cancel.
    - Works for ANY user
    - Works from ANY state
    - Resets user to free/none
    """
    user = update.effective_user
    if not user:
        return

    # 🔥 HARD RESET USER STATE
    clean_user(user.id, reason="global_cancel")

    # Clear local session data
    context.user_data.clear()

    update.message.reply_text(
        "❌ Cancelled.\n"
        "Your current action was stopped and state reset."
    )

    logger.info(
        "GLOBAL CANCEL | user_id=%s",
        user.id,
    )


# ---------- /cancel_all (ADMIN ONLY, GLOBAL RESET) ----------

def global_cancel_all(update: Update, context: CallbackContext):
    """
    Emergency global reset.
    - Clears ALL user modes
    - Admin-only
    """
    user = update.effective_user
    if not user:
        return

    if not _is_admin(user.id):
        update.message.reply_text("⛔ Admins only.")
        return

    removed = clear_all_user_modes()

    context.user_data.clear()

    update.message.reply_text(
        "🚨 GLOBAL RESET\n\n"
        "All user states were cleared.\n"
        f"Rows removed: {removed}"
    )

    logger.critical(
        "GLOBAL CANCEL ALL | admin_id=%s | rows_removed=%s",
        user.id,
        removed,
    )


# ---------- setup ----------

def setup(dispatcher):
    dispatcher.add_handler(CommandHandler("cancel", global_cancel))
    dispatcher.add_handler(CommandHandler("cancel_all", global_cancel_all))

    logger.info("Feature loaded: global_cancel (/cancel, /cancel_all)")

