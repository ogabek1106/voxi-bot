import logging
from typing import Optional

from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

from database import (
    clear_user_mode,
    clear_all_user_modes,
)
import admins

logger = logging.getLogger(__name__)


# ---------- helpers ----------

def _is_admin(user_id: Optional[int]) -> bool:
    raw = getattr(admins, "ADMIN_IDS", []) or []
    return user_id is not None and int(user_id) in {int(x) for x in raw}


# ---------- /cancel ----------

def global_cancel(update: Update, context: CallbackContext):
    """
    Admin-only global cancel.
    Clears current admin's DB mode and conversation data.
    Works from ANY state.
    """
    user = update.effective_user
    if not user:
        return

    if not _is_admin(user.id):
        update.message.reply_text("⛔ Admins only.")
        return

    cleared = clear_user_mode(user.id)

    # Clear any leftover conversation/user data
    context.user_data.clear()

    update.message.reply_text(
        "❌ Cancelled.\n"
        "Your active admin mode has been cleared."
    )

    logger.warning(
        "GLOBAL CANCEL | admin_id=%s | cleared_db_mode=%s",
        user.id,
        cleared,
    )


# ---------- /cancel_all ----------

def global_cancel_all(update: Update, context: CallbackContext):
    """
    Admin-only emergency reset.
    Clears ALL rows from user_modes table.
    """
    user = update.effective_user
    if not user:
        return

    if not _is_admin(user.id):
        update.message.reply_text("⛔ Admins only.")
        return

    removed = clear_all_user_modes()

    # Clear local data as well
    context.user_data.clear()

    update.message.reply_text(
        "🚨 GLOBAL RESET\n\n"
        "All active admin modes have been cleared.\n"
        f"Rows removed: {removed}"
    )

    logger.critical(
        "GLOBAL CANCEL ALL | admin_id=%s | rows_removed=%s",
        user.id,
        removed,
    )


# ---------- setup ----------

def setup(dispatcher):
    # High priority, but NOT extreme
    dispatcher.add_handler(
        CommandHandler("cancel", global_cancel),
        group=-10
    )
    dispatcher.add_handler(
        CommandHandler("cancel_all", global_cancel_all),
        group=-10
    )

    logger.info("Feature loaded: global_cancel (/cancel, /cancel_all)")
