# features/all_members_command.py
"""
Admin broadcast feature (Aiogram 3)

Flow:
1) /all_members
2) Admin sends target IDs or ALL
3) Admin sends message
4) Bot broadcasts with progress + cancel
"""

import asyncio
import logging
from typing import List

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from database import get_all_users
from admins import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router()

# ─────────────── tuning ───────────────
PAUSE_BETWEEN_SENDS = 2
PROGRESS_BATCH = 10
LONG_REST_INTERVAL = 100
LONG_REST_SECS = 10
# ──────────────────────────────────────


# ─────────────── FSM ───────────────
class BroadcastState(StatesGroup):
    awaiting_targets = State()
    awaiting_message = State()
    broadcasting = State()


# ─────────────── utils ───────────────
def is_admin(user_id: int) -> bool:
    return int(user_id) in set(map(int, ADMIN_IDS))


def parse_ids(text: str) -> List[int]:
    cleaned = text.replace(",", " ").replace("\n", " ")
    out = []
    for part in cleaned.split():
        try:
            out.append(int(part))
        except Exception:
            pass
    return out


def format_status(sent, failed, processed, total):
    return f"Progress: ✅ {sent} sent • ❌ {failed} failed • {processed}/{total}"


# ─────────────── commands ───────────────
@router.message(Command("all_members"))
async def cmd_all_members(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("❌ You are not authorized.")
        return

    await state.clear()
    await state.set_state(BroadcastState.awaiting_targets)

    await message.answer(
        "📩 Broadcast started.\n\n"
        "Step 1 — Send target user IDs (space/comma/newline separated)\n"
        "or send `ALL`.\n\n"
        "Send /cancel to abort."
    )


@router.message(Command("cancel"), BroadcastState.awaiting_targets)
@router.message(Command("cancel"), BroadcastState.awaiting_message)
@router.message(Command("cancel"), BroadcastState.broadcasting)
async def cmd_cancel(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.clear()
    await message.answer("🛑 Broadcast cancelled.")


@router.message(Command("cancel_broadcast"))
async def cmd_cancel_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    data["stop"] = True
    await state.update_data(**data)
    await message.answer("🛑 Broadcast stopping...")


# ─────────────── stages ───────────────
@router.message(BroadcastState.awaiting_targets)
async def receive_targets(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    if not message.text:
        await message.answer("Send IDs or ALL.")
        return

    if message.text.upper() == "ALL":
        users = get_all_users()
        targets = [int(u[0] if isinstance(u, (list, tuple)) else u) for u in users]
    else:
        targets = parse_ids(message.text)

    if not targets:
        await message.answer("⚠️ No valid targets.")
        return

    await state.update_data(targets=targets)
    await state.set_state(BroadcastState.awaiting_message)

    await message.answer("✅ Targets set. Now send the message to broadcast.")


@router.message(BroadcastState.awaiting_message)
async def receive_message(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    targets = data.get("targets", [])

    if not targets:
        await message.answer("⚠️ No targets.")
        return

    status = await message.answer(format_status(0, 0, 0, len(targets)))
    await state.set_state(BroadcastState.broadcasting)
    await state.update_data(stop=False)

    asyncio.create_task(
        broadcast_task(
            message.bot,
            message,
            status.message_id,
            targets,
            state,
        )
    )


# ─────────────── worker ───────────────
async def broadcast_task(bot, source_msg: Message, status_id: int, targets: List[int], state: FSMContext):
    sent = failed = processed = 0
    total = len(targets)

    for uid in targets:
        data = await state.get_data()
        if data.get("stop"):
            await bot.edit_message_text(
                chat_id=source_msg.chat.id,
                message_id=status_id,
                text=f"🛑 Broadcast stopped.\n\n{format_status(sent, failed, processed, total)}",
            )
            await state.clear()
            return

        try:
            await bot.copy_message(
                chat_id=uid,
                from_chat_id=source_msg.chat.id,
                message_id=source_msg.message_id,
            )
            sent += 1
        except Exception:
            failed += 1

        processed += 1

        if processed % PROGRESS_BATCH == 0 or processed == total:
            try:
                await bot.edit_message_text(
                    chat_id=source_msg.chat.id,
                    message_id=status_id,
                    text=format_status(sent, failed, processed, total),
                )
            except Exception:
                pass

        await asyncio.sleep(PAUSE_BETWEEN_SENDS)

        if processed % LONG_REST_INTERVAL == 0:
            await asyncio.sleep(LONG_REST_SECS)

    await bot.edit_message_text(
        chat_id=source_msg.chat.id,
        message_id=status_id,
        text=f"🎉 Broadcast finished!\n\n{format_status(sent, failed, processed, total)}",
    )
    await state.clear()
