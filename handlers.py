# handlers.py
import asyncio
import logging
import time

from aiogram import Router, F
from aiogram.filters import CommandStart, StateFilter
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from books import BOOKS
from database import log_book_request
from features.sub_check import require_subscription
# from features.get_test import get_test
# from features.ielts_checkup_ui import _main_user_keyboard

logger = logging.getLogger(__name__)

router = Router()

DELETE_SECONDS = 15 * 60
PROGRESS_BAR_LENGTH = 12


# ─────────────────────────────
# Utils (unchanged logic)
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
# Book sending (async version)
# ─────────────────────────────

async def send_book_by_code(message: Message, code: str):
    book = BOOKS.get(code)
    if not book:
        return False

    file_id = book.get("file_id")
    caption = book.get("caption", "")

    try:
        sent = await message.bot.send_document(
            chat_id=message.chat.id,
            document=file_id,
            caption=caption,
            parse_mode="Markdown",
        )
        log_book_request(code)
    except Exception as e:
        logger.exception("Failed to send book: %s", e)
        return False

    bar = _build_progress_bar(DELETE_SECONDS, DELETE_SECONDS)
    mmss = _format_mmss(DELETE_SECONDS)
    countdown_text = f"⏳ [{bar}] {mmss} - qolgan vaqt"

    try:
        countdown_msg = await message.bot.send_message(
            chat_id=message.chat.id,
            text=countdown_text,
            disable_web_page_preview=True
        )
    except Exception:
        asyncio.create_task(_delete_later(message.bot, message.chat.id, sent.message_id))
        return True

    asyncio.create_task(
        _countdown_task(
            bot=message.bot,
            chat_id=message.chat.id,
            doc_msg_id=sent.message_id,
            countdown_msg_id=countdown_msg.message_id,
            total_seconds=DELETE_SECONDS,
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
    start = time.time()
    end = start + total_seconds
    current_id = countdown_msg_id

    while True:
        remaining = int(end - time.time())

        if remaining <= 0:
            try:
                await bot.delete_message(chat_id, doc_msg_id)
            except Exception:
                pass
            try:
                await bot.delete_message(chat_id, current_id)
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
                new_msg = await bot.send_message(chat_id, text)
                try:
                    await bot.delete_message(chat_id, current_id)
                except Exception:
                    pass
                current_id = new_msg.message_id
            except Exception:
                await asyncio.sleep(5)
                continue

        await asyncio.sleep(60 if remaining > 60 else remaining)


# ─────────────────────────────
# /start + deep links (FREE only)
# ─────────────────────────────

@router.message(CommandStart(), StateFilter(None))
async def start_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("admin_mode"):
        return

    payload = message.text.split(maxsplit=1)
    payload = payload[1] if len(payload) > 1 else ""

    if payload:
        payload = payload.strip()

        if payload.lower() == "get_test":
            return  # feature handles it

        if payload.isdigit():
            if not await require_subscription(message):
                return
            ok = await send_book_by_code(message, payload)
            if not ok:
                await message.answer("Bu kod bo‘yicha kitob topilmadi.")
            return

        if payload.lower() == "ad_rec":
            from features.ad_reciever import ad_rec_handler
            return await ad_rec_handler(message)

        return  # ignore unknown payloads

    # plain /start
    name = message.from_user.first_name or "do‘st"
    await message.answer(
        f"*Assalomu alaykum*, {name}!\n\n"
        "_⚠️ Voxi ishlash sifatini yaxshilash uchun yuborilgan ayrim matnlar anonim tarzda saqlanishi va tahlil qilinishi mumkin.\n"
        "Hech qanday shaxsiy ma’lumot yig‘ilmaydi.\n"
        "Botdan foydalanish orqali siz bunga rozilik berasiz._\n\n"
        "Menga *kitob kodini* yuboring yoki kerakli *bo'limni* tanlang 👇",
        parse_mode="Markdown",
        # reply_markup=_main_user_keyboard()
    )


# ─────────────────────────────
# Numeric book messages (FREE only)
# ─────────────────────────────

@router.message(StateFilter(None), F.text.regexp(r"^\d+$"))
async def numeric_message_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("admin_mode"):
        return

    if not await require_subscription(message):
        return

    code = message.text.strip()

    if code not in BOOKS:
        await message.answer("Bunday kod topilmadi.")
        return

    ok = await send_book_by_code(message, code)
    if not ok:
        await message.answer("Kitobni yuborishda xatolik yuz berdi.")
