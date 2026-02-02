# features/book_upload.py
"""
Feature: /book_upload (admin only)

Flow:
1. Admin sends /book_upload
2. Bot asks for file
3. Admin sends file
4. Bot forwards file to STORAGE_CHAT_ID
5. Bot replies with FILE_ID + storage message_id
"""

import logging
import os

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from admins import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router()

# ─────────────────────────────
# Config
# ─────────────────────────────

STORAGE_CHAT_ID = int(os.getenv("STORAGE_CHAT_ID", "-1002714023986"))


# ─────────────────────────────
# FSM
# ─────────────────────────────

class BookUploadState(StatesGroup):
    waiting_file = State()


# ─────────────────────────────
# Utils
# ─────────────────────────────

def is_admin(user_id: int) -> bool:
    return int(user_id) in set(map(int, ADMIN_IDS))


def extract_file_id(msg: Message) -> str | None:
    if msg.document:
        return msg.document.file_id
    if msg.photo:
        return msg.photo[-1].file_id
    if msg.video:
        return msg.video.file_id
    if msg.audio:
        return msg.audio.file_id
    if msg.voice:
        return msg.voice.file_id
    if msg.animation:
        return msg.animation.file_id
    return None


# ─────────────────────────────
# /book_upload
# ─────────────────────────────

@router.message(Command("book_upload"))
async def book_upload_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("❌ You are not allowed to use this command.")
        return

    await state.clear()
    await state.set_state(BookUploadState.waiting_file)

    await message.answer(
        "📤 Send me the file you want to upload.\n\n"
        "Supported: document / photo / video / audio / voice / animation\n\n"
        "Send /cancel to abort."
    )
    logger.info("Admin %s started book upload flow", message.from_user.id)


# ─────────────────────────────
# /cancel
# ─────────────────────────────

@router.message(Command("cancel"), BookUploadState.waiting_file)
async def book_upload_cancel(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.clear()
    await message.answer("🛑 Upload cancelled.")

# ─────────────────────────────
# File receiver
# ─────────────────────────────

@router.message(
    BookUploadState.waiting_file,
    F.document | F.photo | F.video | F.audio | F.voice | F.animation
)
async def book_upload_receive_file(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    # Forward file to storage channel
    try:
        forwarded = await message.bot.forward_message(
            chat_id=STORAGE_CHAT_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
    except Exception as e:
        logger.exception("Failed to forward file to storage channel")
        await message.answer(
            "❌ Failed to forward file.\n"
            "Check bot access to storage channel."
        )
        return

    # Extract FILE_ID
    file_id = extract_file_id(forwarded) or extract_file_id(message)
    storage_mid = forwarded.message_id

    lines = ["✅ File uploaded."]

    if file_id:
        lines += [
            "",
            "📂 FILE_ID (use this in books.py):",
            file_id,
        ]
    else:
        lines.append("⚠️ Could not automatically extract FILE_ID.")

    lines += [
        "",
        "📨 Storage message_id:",
        str(storage_mid),
    ]

    await message.answer("\n".join(lines))
    logger.info(
        "Book uploaded by admin %s | file_id=%r storage_mid=%s",
        message.from_user.id,
        file_id,
        storage_mid,
    )

    await state.clear()


# ─────────────────────────────
# Guard: wrong content during upload
# ─────────────────────────────

@router.message(BookUploadState.waiting_file)
async def book_upload_wrong_content(message: Message):
    await message.answer(
        "⚠️ Please send a FILE.\n"
        "Supported: document / photo / video / audio / voice / animation\n\n"
        "Send /cancel to abort."
    )
