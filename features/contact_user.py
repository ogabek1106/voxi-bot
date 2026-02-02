# features/contact_user.py
"""
Admin ↔ User contact feature (Aiogram 3)

Safe, state-isolated, async.
"""

import asyncio
import logging
from typing import Optional

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from admins import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router()

BRIDGE_TIMEOUT = 24 * 60 * 60  # 24 hours


# ─────────────────────────────
# FSM
# ─────────────────────────────

class ContactState(StatesGroup):
    admin_confirm = State()      # admin: waiting YES/NO
    user_invited = State()       # user: invited, not connected
    bridge_active = State()      # both sides: relay allowed


# ─────────────────────────────
# Utils
# ─────────────────────────────

def is_admin(uid: int) -> bool:
    return int(uid) in set(map(int, ADMIN_IDS))


# ─────────────────────────────
# /contact <user_id>
# ─────────────────────────────

@router.message(Command("contact"))
async def contact_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) != 2 or not args[1].isdigit():
        await message.answer("Usage: /contact <user_id>")
        return

    target_user = int(args[1])

    # admin must be free
    if await state.get_state() is not None:
        await message.answer("⚠️ Finish current contact first.")
        return

    await state.set_state(ContactState.admin_confirm)
    await state.update_data(target_user=target_user)

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Yes", callback_data="contact_yes"),
        InlineKeyboardButton(text="❌ No", callback_data="contact_no"),
    ]])

    await message.answer(
        f"User found: {target_user}\n\nSend contact invitation?",
        reply_markup=kb
    )


# ─────────────────────────────
# Admin confirms YES / NO
# ─────────────────────────────

@router.callback_query(ContactState.admin_confirm, F.data.in_({"contact_yes", "contact_no"}))
async def contact_decision(cb: CallbackQuery, state: FSMContext):
    await cb.answer()

    data = await state.get_data()
    target_user = data["target_user"]

    if cb.data == "contact_no":
        await state.clear()
        await cb.message.edit_text("❌ Contact cancelled.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="📞 Contact admin",
            callback_data=f"bridge_open:{cb.from_user.id}"
        )
    ]])

    try:
        await cb.bot.send_message(
            chat_id=target_user,
            text=(
                "Admin wants to contact you.\n\n"
                "Press the button below to accept."
            ),
            reply_markup=kb
        )
    except Exception:
        await cb.message.edit_text("❌ Failed to contact user.")
        await state.clear()
        return

    await cb.message.edit_text("✅ Invitation sent.")
    await state.clear()


# ─────────────────────────────
# User presses contact button
# ─────────────────────────────

@router.callback_query(F.data.startswith("bridge_open:"))
async def open_bridge(cb: CallbackQuery, state: FSMContext):
    await cb.answer()

    admin_id = int(cb.data.split(":")[1])
    user_id = cb.from_user.id

    if is_admin(user_id):
        return

    # lock both sides
    await state.set_state(ContactState.bridge_active)

    admin_state = state.bot.fsm.get_context(
        bot=cb.bot,
        chat_id=admin_id,
        user_id=admin_id,
    )
    await admin_state.set_state(ContactState.bridge_active)
    await admin_state.update_data(peer=user_id)

    await state.update_data(peer=admin_id)

    await cb.message.edit_text("✅ You are now connected to admin.")
    await cb.bot.send_message(
        chat_id=admin_id,
        text=f"📩 User {user_id} connected.\nUse /end_contact to close."
    )

    asyncio.create_task(auto_close(cb.bot, admin_id, user_id))


# ─────────────────────────────
# /end_contact (admin)
# ─────────────────────────────

@router.message(Command("end_contact"), ContactState.bridge_active)
async def end_contact(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    peer = data.get("peer")

    await state.clear()

    if peer:
        peer_state = state.bot.fsm.get_context(
            bot=message.bot,
            chat_id=peer,
            user_id=peer,
        )
        await peer_state.clear()

        try:
            await message.bot.send_message(peer, "ℹ️ Contact closed by admin.")
        except Exception:
            pass

    await message.answer("✅ Contact closed.")


# ─────────────────────────────
# Message relay (ACTIVE ONLY)
# ─────────────────────────────

@router.message(ContactState.bridge_active)
async def relay(message: Message, state: FSMContext):
    data = await state.get_data()
    peer = data.get("peer")
    if not peer:
        return

    await message.bot.forward_message(
        chat_id=peer,
        from_chat_id=message.chat.id,
        message_id=message.message_id
    )


# ─────────────────────────────
# Auto-close timeout
# ─────────────────────────────

async def auto_close(bot, admin_id: int, user_id: int):
    await asyncio.sleep(BRIDGE_TIMEOUT)

    admin_state = bot.fsm.get_context(bot, admin_id, admin_id)
    user_state = bot.fsm.get_context(bot, user_id, user_id)

    if await admin_state.get_state() == ContactState.bridge_active:
        await admin_state.clear()
        await user_state.clear()
        try:
            await bot.send_message(admin_id, "⏱ Contact auto-closed (timeout).")
            await bot.send_message(user_id, "⏱ Contact expired.")
        except Exception:
            pass
