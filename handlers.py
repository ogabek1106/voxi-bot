# handlers.py
import asyncio
import logging
import time

from aiogram import Router, F
from aiogram.filters import CommandStart, StateFilter
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from features.sub_check import require_subscription
from database import log_command_use
from admins import ADMIN_IDS
from books import BOOKS
from database import log_book_request
#from features.ielts_checkup_ui import main_user_keyboard

logger = logging.getLogger(__name__)

router = Router()

DELETE_SECONDS = 15 * 60
PROGRESS_BAR_LENGTH = 12


# ─────────────────────────────
# Utils
# ─────────────────────────────

def _format_mmss(seconds: int) -> str:
    if seconds < 0:
        seconds = 0
    m = seconds // 60
    s = seconds % 60
    return f"{m:02d}:{s:02d}"


def _build_progress_bar(remaining: int, total: int, length: int = PROGRESS_BAR_LENGTH) -> str:
    if total <= 0:
        return "─" * length
    frac = max(0.0, min(1.0, remaining / total))
    filled = int(round(frac * length))
    filled = max(0, min(length, filled))
    return "█" * filled + "─" * (length - filled)


# ─────────────────────────────
# Book sending
# ─────────────────────────────

async def send_book_by_code(message: Message, code: str) -> bool:
    book = BOOKS.get(code)
    if not book:
        return False

    try:
        sent = await message.bot.send_document(
            chat_id=message.chat.id,
            document=book["file_id"],
            caption=book.get("caption", ""),
            parse_mode="Markdown",
        )
        if message.from_user.id not in ADMIN_IDS:
            log_book_request(code)
    except Exception as e:
        logger.exception("Failed to send book: %s", e)
        return False

    bar = _build_progress_bar(DELETE_SECONDS, DELETE_SECONDS)
    mmss = _format_mmss(DELETE_SECONDS)
    text = f"⏳ [{bar}] {mmss} - qolgan vaqt"

    try:
        countdown = await message.bot.send_message(
            message.chat.id,
            text,
            disable_web_page_preview=True
        )
    except Exception:
        asyncio.create_task(_delete_later(message.bot, message.chat.id, sent.message_id))
        return True

    asyncio.create_task(
        _countdown_task(
            message.bot,
            message.chat.id,
            sent.message_id,
            countdown.message_id,
            DELETE_SECONDS
        )
    )
    return True


async def _delete_later(bot, chat_id, msg_id):
    await asyncio.sleep(DELETE_SECONDS)
    try:
        await bot.delete_message(chat_id, msg_id)
    except Exception:
        pass


async def _countdown_task(bot, chat_id, doc_msg_id, countdown_msg_id, total_seconds):
    end = time.time() + total_seconds
    current_id = countdown_msg_id

    while True:
        remaining = int(end - time.time())

        if remaining <= 0:
            for mid in (doc_msg_id, current_id):
                try:
                    await bot.delete_message(chat_id, mid)
                except Exception:
                    pass
            break

        bar = _build_progress_bar(remaining, total_seconds)
        mmss = _format_mmss(remaining)
        text = f"⏳ [{bar}] {mmss} - qolgan vaqt"

        try:
            await bot.edit_message_text(text, chat_id, current_id)
        except Exception:
            try:
                new = await bot.send_message(chat_id, text)
                try:
                    await bot.delete_message(chat_id, current_id)
                except Exception:
                    pass
                current_id = new.message_id
            except Exception:
                await asyncio.sleep(5)
                continue

        await asyncio.sleep(60 if remaining > 60 else remaining)


# ─────────────────────────────
# /start + deep links (FREE)
# ─────────────────────────────

@router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    if not await require_subscription(message, state):
        return

    parts = message.text.split(maxsplit=1)
    payload = parts[1].strip() if len(parts) > 1 else ""

    # 🔹 Deep-link: AD
    if payload == "ad_rec":
        from features.ad_reciever import emit_ad
        await emit_ad(message, state)
        return

    # 🔹 Deep-link: GET TEST  
    if payload == "get_test":
        from features.get_test import get_test
        await get_test(message, state)
        return
    
    # 🔹 Deep-link: BOOK by code
    if payload.isdigit():
        ok = await send_book_by_code(message, payload)
        if not ok:
            await message.answer("Bu kod bo‘yicha kitob topilmadi.")
        return

    # 🔹 Normal /start  ✅ COUNT HERE
    if message.from_user.id not in ADMIN_IDS:
        log_command_use("start")
    # 🔹 Normal /start
    name = message.from_user.first_name or "do‘st"
    await message.answer(
        f"*Assalomu alaykum*, {name}!\n\n"
        "_⚠️ Voxi ishlash sifatini yaxshilash uchun yuborilgan ayrim matnlar "
        "anonim tarzda saqlanishi va tahlil qilinishi mumkin._\n\n"
        "Menga *kitob kodini* yuboring 👇",
        parse_mode="Markdown",
        reply_markup=main_user_keyboard(),
    )


# ─────────────────────────────
# Numeric messages (FREE)
# ─────────────────────────────

@router.message(F.text.regexp(r"^\d+$"))
async def numeric_message_handler(message: Message, state: FSMContext):
    if not await require_subscription(message, state):
        return
    code = message.text.strip()

    if code not in BOOKS:
        await message.answer("Bunday kod topilmadi.")
        return

    ok = await send_book_by_code(message, code)
    if not ok:
        await message.answer("Kitobni yuborishda xatolik yuz berdi.")
