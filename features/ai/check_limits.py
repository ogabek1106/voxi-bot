"""
AI usage limiter / gatekeeper.

Responsibilities:
- determine user tariff (currently FREE only)
- check last 24h usage
- calculate remaining attempts
- return structured decision + warning text

This file is FUTURE-PROOF:
- tariff lists can be added later
- limits can be expanded without refactor
"""

import time
from typing import Dict

# ==============================
# TEMPORARY TARIFF LISTS
# (empty for now)
# ==============================

SILVER_USERS = set()
GOLD_USERS = set()
PREMIUM_USERS = set()


# ==============================
# LIMIT CONFIG (FREE ONLY FOR NOW)
# ==============================

LIMITS = {
    "FREE": {
        "writing": 1,
        "speaking": 1,
        "reading": 1,
        "listening": 1,
    }
}

WINDOW_SECONDS = 24 * 60 * 60  # 24 hours


# ==============================
# DB FUNCTIONS (YOU ALREADY HAVE THESE)
# ==============================
# You already use SQLite.
# These function names are EXPECTED to exist.
# Adjust import path if needed.

from database import (
    count_feature_usage_since,
    get_last_feature_usage_time,
)


# ==============================
# TARIFF RESOLUTION
# ==============================

def get_user_tariff(user_id: int) -> str:
    """
    Resolve user tariff by priority.
    """
    if user_id in PREMIUM_USERS:
        return "PREMIUM"
    if user_id in GOLD_USERS:
        return "GOLD"
    if user_id in SILVER_USERS:
        return "SILVER"
    return "FREE"


# ==============================
# CORE LIMIT CHECK
# ==============================

def can_use_feature(user_id: int, feature: str) -> Dict:
    """
    Main limiter function.
    Returns a structured decision dict.
    """

    tariff = get_user_tariff(user_id)

    # Future-ready: if tariff not defined yet
    if tariff not in LIMITS:
        return {
            "allowed": True,
            "tariff": tariff,
            "message": None,
        }

    limit = LIMITS[tariff].get(feature, 0)

    # Feature not allowed at all
    if limit <= 0:
        return {
            "allowed": False,
            "tariff": tariff,
            "used": 0,
            "limit": 0,
            "remaining": 0,
            "retry_after_seconds": None,
            "message": "⛔ Bu tekshiruv sizning tarifingizda mavjud emas.",
        }

    now = int(time.time())
    since = now - WINDOW_SECONDS

    used = count_feature_usage_since(
        user_id=user_id,
        feature=feature,
        since_timestamp=since,
    )

    if used < limit:
        return {
            "allowed": True,
            "tariff": tariff,
            "used": used,
            "limit": limit,
            "remaining": limit - used,
            "message": None,
        }

    # Blocked → calculate remaining time
    last_used = get_last_feature_usage_time(user_id, feature)

    retry_after = None
    if last_used:
        retry_after = (last_used + WINDOW_SECONDS) - now
        if retry_after < 0:
            retry_after = 0

    hours = retry_after // 3600
    minutes = (retry_after % 3600) // 60

    message = (
        "⛔ *Kunlik limit tugadi*\n\n"
        f"✍️ {feature.capitalize()}: {used} / {limit}\n"
        f"⏳ Qayta urinish: {hours} soat {minutes} daqiqa\n\n"
        "💎 Pullik tariflar bilan ko‘proq imkoniyatlar mavjud."
    )

    return {
        "allowed": False,
        "tariff": tariff,
        "used": used,
        "limit": limit,
        "remaining": 0,
        "retry_after_seconds": retry_after,
        "message": message,
    }
