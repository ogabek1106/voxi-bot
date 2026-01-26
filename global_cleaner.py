# global_cleaner.py
"""
Global cleaner for Voxi bot.

Purpose:
- Safely reset a user to FREE state
- Clear ALL modal / exclusive states
- Called explicitly by features on:
    - /cancel
    - /exit
    - successful completion
    - abort / timeout / fatal error

Design rules:
- Features NEVER touch DB directly for cleanup
- Cleaner performs FULL reset (no partial clean)
- Safe to call multiple times
- Never raises exceptions to caller
"""

import logging
from typing import Optional

from database import (
    clear_user_mode,
    clear_checker_mode,
)

logger = logging.getLogger(__name__)


# -------------------------------
# Public API (ONLY ONE FUNCTION)
# -------------------------------

def clean_user(user_id: int, reason: Optional[str] = None) -> bool:
    """
    Fully reset user to FREE mode.

    What this clears:
    - user_modes      (exclusive feature ownership)
    - checker_state   (IELTS / AI checker context)

    What this DOES NOT touch:
    - users table
    - tests, answers, scores
    - any persistent business data

    Parameters:
    - user_id: Telegram user id
    - reason: optional string for logging/debugging

    Returns:
    - True if cleanup executed (even if nothing existed)
    - False only if something unexpected happened
    """

    ok = True

    try:
        # Clear exclusive user mode
        clear_user_mode(user_id)
    except Exception as e:
        ok = False
        logger.exception(
            "global_cleaner: failed to clear user_mode for %s (%s): %s",
            user_id,
            reason,
            e,
        )

    try:
        # Clear AI / checker mode (IELTS, etc.)
        clear_checker_mode(user_id)
    except Exception as e:
        ok = False
        logger.exception(
            "global_cleaner: failed to clear checker_mode for %s (%s): %s",
            user_id,
            reason,
            e,
        )

    logger.info(
        "global_cleaner: user %s reset to FREE state%s",
        user_id,
        f" | reason={reason}" if reason else "",
    )

    return ok
