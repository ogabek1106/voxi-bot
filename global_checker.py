# global_checker.py
"""
Global mode checker for Voxi bot.

Purpose:
- Centralized, READ-ONLY access control for handlers
- Ensures only the owning feature processes a user's input
- Prevents handler cross-catching

Rules:
- Free mode == no row in user_modes table
- Each handler must call this BEFORE doing anything
- This file MUST NOT modify DB state

Usage patterns are documented at the bottom.
"""

import logging
from typing import Optional, Iterable

from database import get_user_mode

logger = logging.getLogger(__name__)


# -------------------------------
# Core checkers
# -------------------------------

def get_mode(user_id: int) -> Optional[str]:
    """
    Return current user mode or None (free mode).
    Thin wrapper for clarity and future-proofing.
    """
    try:
        return get_user_mode(user_id)
    except Exception as e:
        logger.exception("global_checker.get_mode failed for %s: %s", user_id, e)
        return None


def is_free(user_id: int) -> bool:
    """
    True if user is NOT in any exclusive mode.
    """
    return get_mode(user_id) is None


def owns(user_id: int, mode: str) -> bool:
    """
    True if user is currently in the given mode.
    """
    if not mode:
        return False
    return get_mode(user_id) == mode


# -------------------------------
# Generic gate (MOST IMPORTANT)
# -------------------------------

def allow(
    user_id: int,
    *,
    mode: Optional[str] = None,
    allow_free: bool = False,
) -> bool:
    """
    Universal gatekeeper for handlers.

    Parameters:
    - user_id: Telegram user id
    - mode:
        - None  -> handler is FREE-MODE only
        - str   -> handler owns this exclusive mode
    - allow_free:
        - False (default): free users are NOT allowed unless mode=None
        - True: handler may accept free users AND matching mode users

    Returns:
    - True  -> handler may continue
    - False -> handler MUST return immediately

    Decision matrix:

    1) mode=None, allow_free=False
       - allow ONLY free users

    2) mode=None, allow_free=True
       - allow ALL users (use carefully)

    3) mode="create_test", allow_free=False
       - allow ONLY users in create_test

    4) mode="create_test", allow_free=True
       - allow users in create_test OR free users
    """

    current = get_mode(user_id)

    # --- Case 1: handler is free-mode only ---
    if mode is None:
        if current is None:
            return True
        return bool(allow_free)

    # --- Case 2: handler owns an exclusive mode ---
    if current == mode:
        return True

    # --- Case 3: allow_free fallback ---
    if allow_free and current is None:
        return True

    return False


# -------------------------------
# Debug helper (optional)
# -------------------------------

def explain(
    user_id: int,
    *,
    mode: Optional[str] = None,
    allow_free: bool = False,
) -> str:
    """
    Human-readable explanation of allow() decision.
    NEVER use in production replies. Debug/logging only.
    """
    current = get_mode(user_id)

    if allow(user_id, mode=mode, allow_free=allow_free):
        return f"ALLOW (user_mode={current}, handler_mode={mode}, allow_free={allow_free})"
    else:
        return f"DENY (user_mode={current}, handler_mode={mode}, allow_free={allow_free})"
