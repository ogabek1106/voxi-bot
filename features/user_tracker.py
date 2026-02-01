# features/user_tracker.py
"""
Feature: record every unique user exactly once (Aiogram 3).

- Uses middleware (NOT handlers)
- Tracks users from ANY update type
- Calls database.add_user_if_new(...)
- Zero interference with business logic
"""

import logging
from typing import Optional, Callable, Awaitable, Dict, Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from database import add_user_if_new

logger = logging.getLogger(__name__)


# ─────────────────────────────
# Middleware
# ─────────────────────────────

class UserTrackerMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = self._extract_user(event)
        if user:
            self._record_user(user)

        return await handler(event, data)

    # ─────────────────────────

    @staticmethod
    def _extract_user(event: TelegramObject) -> Optional[User]:
        """
        Extract user from ANY Telegram update.
        """
        for attr in (
            "from_user",
            "user",
            "effective_user",  # safety
        ):
            user = getattr(event, attr, None)
            if user:
                return user
        return None

    # ─────────────────────────

    @staticmethod
    def _record_user(user: User) -> None:
        try:
            uid = int(user.id)
        except Exception:
            logger.debug("user_tracker: invalid user id: %r", getattr(user, "id", None))
            return

        first_name = user.first_name
        username = user.username

        try:
            added = add_user_if_new(uid, first_name, username)
            if added:
                logger.info(
                    "user_tracker: new user %s (@%s) name=%r",
                    uid,
                    username,
                    first_name,
                )
        except Exception as e:
            logger.exception(
                "user_tracker: failed to record user %s: %s",
                uid,
                e,
            )


# ─────────────────────────────
# Loader entry (Aiogram 3 style)
# ─────────────────────────────

def setup_middleware(dp):
    dp.update.middleware(UserTrackerMiddleware())
