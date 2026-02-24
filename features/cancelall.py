# features/cancelall.py
"""
User self-reset command.

Command:
- /cancelall

Behavior:
- Clears ONLY the caller's FSM state
- Clears ONLY the caller's user_mode in DB
- Does NOT affect other users
- Safe to expose to everyone
"""

import logging
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from database import clear_user_mode

logger = logging.getLogger(__name__)

router = Router()

@router.message(Command("cancelall"))
async def cancel_self_only(message: Message, state: FSMContext):
    user = message.from_user
    if not user:
        return

    # Clear ONLY this user's DB mode + FSM state
    clear_user_mode(user.id)
    await state.clear()

    await message.answer("✅ Your session was reset. You can start again.")
    logger.info("User self-reset | user_id=%s", user.id)
