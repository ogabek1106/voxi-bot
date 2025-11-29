# features/user_tracker.py
"""
Feature: record every unique user into database.py.

- Registers lightweight handlers that call database.add_user_if_new(...)
- Handlers are registered with a low-priority group so core handlers run first.
- Logs what it does so you can verify in Railway logs.

Place in features/ and it will be auto-loaded by your feature loader.
"""

import logging
from typing import Optional

from telegram import Update
from telegram.ext import (
    CallbackContext,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackQueryHandler,
    InlineQueryHandler,
    ChosenInlineResultHandler,
)

from database import add_user_if_new

logger = logging.getLogger(__name__)

# Dispatcher group used for tracking (low priority so core handlers act first)
TRACKER_GROUP = 50


def _record_user_from_update(update: Update) -> Optional[int]:
    """
    Extract user from Update (works for messages, callback queries, inline queries, etc.)
    Returns user_id when present, else None.
    """
    user = update.effective_user
    if not user:
        return None

    try:
        uid = int(user.id)
    except Exception:
        logger.debug("user_tracker: non-int user id: %r", getattr(user, "id", None))
        return None

    first_name = getattr(user, "first_name", None)
    username = getattr(user, "username", None)

    try:
        added = add_user_if_new(uid, first_name, username)
        if added:
            logger.info("user_tracker: added new user %s (@%s) name=%r", uid, username, first_name)
        else:
            logger.debug("user_tracker: user already exists %s", uid)
    except Exception as e:
        logger.exception("user_tracker: failed to add/check user %s: %s", uid, e)

    return uid


def start_handler(update: Update, context: CallbackContext):
    """Record user when they send /start (including deep links)."""
    _record_user_from_update(update)
    # Do not reply here — core start handler will handle greet


def message_handler(update: Update, context: CallbackContext):
    """Record user for any normal message (text/photo/etc)."""
    _record_user_from_update(update)


def edited_message_handler(update: Update, context: CallbackContext):
    """Record user for edited messages (if applicable)."""
    _record_user_from_update(update)


def callback_query_handler(update: Update, context: CallbackContext):
    """Record user for callback queries (button presses)."""
    _record_user_from_update(update)


def inline_query_handler(update: Update, context: CallbackContext):
    """Record user for inline queries (if your bot supports inline mode)."""
    _record_user_from_update(update)


def chosen_inline_result_handler(update: Update, context: CallbackContext):
    """Record user when an inline result is chosen."""
    _record_user_from_update(update)


def setup(dispatcher, bot=None):
    """
    Register handlers. Use group=TRACKER_GROUP so core handlers load before tracker.
    """
    # /start (and deep-link starts)
    dispatcher.add_handler(CommandHandler("start", start_handler), group=TRACKER_GROUP)

    # Normal messages — record but allow core handlers to process first
    dispatcher.add_handler(MessageHandler(Filters.all & ~Filters.command, message_handler), group=TRACKER_GROUP)

    # Edited messages (some PTB setups deliver edited messages via update.edited_message)
    try:
        dispatcher.add_handler(MessageHandler(Filters.update.edited_message, edited_message_handler), group=TRACKER_GROUP)
    except Exception:
        # if Filters.update.edited_message not available in environment, skip safely
        logger.debug("user_tracker: Filters.update.edited_message not available; skipping edited_message handler")

    # Callback queries (inline keyboards)
    dispatcher.add_handler(CallbackQueryHandler(callback_query_handler), group=TRACKER_GROUP)

    # Inline mode handlers (if used)
    try:
        dispatcher.add_handler(InlineQueryHandler(inline_query_handler), group=TRACKER_GROUP)
        dispatcher.add_handler(ChosenInlineResultHandler(chosen_inline_result_handler), group=TRACKER_GROUP)
    except Exception:
        logger.debug("user_tracker: Inline handlers not available in this PTB version; skipping them")

    logger.info("user_tracker feature loaded (group=%s).", TRACKER_GROUP)
