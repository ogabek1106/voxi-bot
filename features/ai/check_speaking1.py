# features/ai/check_speaking1.py
"""
/ielts_speaking_part1
IELTS Speaking Part 1 AI checker (Aiogram 3)

Rules:
- Triggered only by command
- UI button only sends the command
- Business logic lives here
- Must validate IELTS_MODE
"""

import logging
import os
import io

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext

from database import (
    get_user_mode,
    set_user_mode,
    log_ai_usage,
)

from features.ai.check_limits import can_use_feature
from features.admin_feedback import send_admin_card

import openai

logger = logging.getLogger(__name__)
router = Router()

IELTS_MODE = "ielts_check_up"
CHECKER_MODE = "speaking_part1"

WAITING_FOR_QUESTION = "sp1_question"
WAITING_FOR_VOICE = "sp1_voice"

openai.api_key = os.getenv("OPENAI_API_KEY")

MIN_SECONDS = 10
MAX_SECONDS = 180
RECOMMENDED = "15–30 soniya"

SYSTEM_PROMPT = """
You are an IELTS Speaking Part 1 teacher giving kind, natural, and precise feedback directly to the student.

You will be given:
1) The Speaking Part 1 QUESTION
2) The student's SPOKEN ANSWER (transcribed)

Your task:
- Evaluate according to IELTS Speaking Part 1 public band descriptors.
- Talk directly TO the student using only “siz” (never “sen”).
- This is NOT an official score.
- Keep feedback short and clear (FREE MODE).

STRICT FORMAT RULES:
- Use EXACTLY the structure below.
- Band must be numeric range only.

OUTPUT TEMPLATE:

📊 *Taxminiy band (range):*
<number range>

🌟 *Yaxshi tomonlar:*
<2–3 short sentences>

❗ *Asosiy muammolar:*
<1–3 short points>

🛠 *Yaxshilash bo‘yicha maslahat:*
<1–2 suggestions + encouragement>
"""

# ─────────────────────────────
# Utils
# ─────────────────────────────

def _checker_cancel_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Cancel")]],
        resize_keyboard=True
    )

# ─────────────────────────────
# Entry
# ─────────────────────────────

@router.message(Command("ielts_speaking_part1"))
async def start_check(message: Message, state: FSMContext):
    uid = message.from_user.id

    if get_user_mode(uid) != IELTS_MODE:
        return

    limit_result = can_use_feature(uid, "speaking")
    if not limit_result["allowed"]:
        await message.answer(limit_result["message"], parse_mode="Markdown")
        return

    set_user_mode(uid, CHECKER_MODE)
    await state.set_state(WAITING_FOR_QUESTION)

    await message.answer(
        "🎤 *IELTS Speaking Part 1 savolini yuboring.*\n\n"
        "Masalan:\n"
        "_Where do you live?_\n"
        "_Do you like your job?_",
        parse_mode="Markdown",
        reply_markup=_checker_cancel_keyboard()
    )

# ─────────────────────────────
# Receive Question
# ─────────────────────────────

@router.message(StateFilter(WAITING_FOR_QUESTION), F.text != "❌ Cancel")
async def receive_question(message: Message, state: FSMContext):
    uid = message.from_user.id

    if get_user_mode(uid) != CHECKER_MODE:
        return

    if not message.text or len(message.text.strip()) < 5:
        await message.answer("❗️Iltimos, aniq speaking savolini yuboring.")
        return

    await state.update_data(question=message.text.strip())
    await state.set_state(WAITING_FOR_VOICE)

    await message.answer(
        "✅ *Savol qabul qilindi.*\n\n"
        "🎙 Endi ovozli javob yuboring.\n\n"
        f"📌 Tavsiya etiladi: {RECOMMENDED}\n"
        "⛔️ Juda uzun javob bahoni pasaytiradi.",
        parse_mode="Markdown"
    )

# ─────────────────────────────
# Receive Voice
# ─────────────────────────────

@router.message(StateFilter(WAITING_FOR_VOICE), F.voice)
async def receive_voice(message: Message, state: FSMContext):
    uid = message.from_user.id

    if get_user_mode(uid) != CHECKER_MODE:
        return

    duration = message.voice.duration

    if duration < MIN_SECONDS:
        await message.answer("❗️Javob juda qisqa. Kamida 10 soniya bo‘lsin.")
        return

    if duration > MAX_SECONDS:
        await message.answer("❗️Javob juda uzun. Speaking Part 1 uchun noto‘g‘ri.")

    data = await state.get_data()
    question = data.get("question")

    if not question:
        await message.answer("❗️Avval savolni yuboring.")
        return

    await message.answer("⏳ Ovozli javob tahlil qilinmoqda...")

    try:
        tg_file = await message.bot.get_file(message.voice.file_id)
        audio_bytes = await message.bot.download_file(tg_file.file_path)

        audio_file = io.BytesIO(audio_bytes.read())
        audio_file.name = "speech.ogg"

        transcription_result = await openai.Audio.atranscribe(
            model="whisper-1",
            file=audio_file
        )
        transcription = transcription_result["text"]

        response = await openai.ChatCompletion.acreate(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Question:\n{question}\n\nAnswer:\n{transcription}"},
            ],
            max_tokens=500,
        )

        output_text = response["choices"][0]["message"]["content"].strip()
        await message.answer(output_text, parse_mode="Markdown")

        await send_admin_card(message.bot, uid, "New IELTS Speaking Part 1", output_text)
        log_ai_usage(uid, "speaking")

    except Exception:
        logger.exception("Speaking Part 1 AI error")
        await message.answer("❌ Xatolik yuz berdi. Keyinroq urinib ko‘ring.")

    finally:
        await state.clear()
        set_user_mode(uid, IELTS_MODE)

        from features.ielts_checkup_ui import ielts_skills_reply_keyboard
        await message.answer("✅ Tekshiruv yakunlandi.", reply_markup=ielts_skills_reply_keyboard())

# ─────────────────────────────
# Cancel
# ─────────────────────────────

@router.message(F.text == "❌ Cancel", StateFilter(WAITING_FOR_QUESTION))
@router.message(F.text == "❌ Cancel", StateFilter(WAITING_FOR_VOICE))
async def cancel_anytime(message: Message, state: FSMContext):
    uid = message.from_user.id

    if get_user_mode(uid) != CHECKER_MODE:
        return

    await state.clear()
    set_user_mode(uid, IELTS_MODE)

    from features.ielts_checkup_ui import ielts_skills_reply_keyboard
    await message.answer("❌ Tekshiruv bekor qilindi.", reply_markup=ielts_skills_reply_keyboard())
