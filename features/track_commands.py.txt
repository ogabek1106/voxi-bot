"""
Global command tracker.
Counts EVERY /command before it is handled anywhere else.
"""

import logging
from telegram import Update
from telegram.ext import CallbackContext

from database import log_command_use

logger = logging.getLogger(__name__)


def track_command(update: Update, context: CallbackContext):
    message = update.message
    if not message or not message.text:
        return

    text = message.text.strip()

    # Only commands
    if not text.startswith("/"):
        return

    # Extract command safely: "/start@bot arg1" -> "/start"
    command = text.split()[0].split("@")[0]

    try:
        log_command_use(command)
    except Exception:
        logger.exception("Failed to log command usage")
