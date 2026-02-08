# features/ai/check_speaking2.py
import logging
import os
import io
import base64

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
CHECKER_MODE = "speaking_part2"

WAITING_FOR_CUE_CARD = "sp2_cue_card"
WAITING_FOR_VOICE = "sp2_voice"

openai.api_key = os.getenv("OPENAI_API_KEY")

MIN_SECONDS = 30
MAX_SECONDS = 150
RECOMMENDED = "1–2 daqiqa"

SYSTEM_PROMPT = """
You are an IELTS Speaking Part 2 teacher giving kind, natural, and precise feedback directly to the student.

You will be given:
1) The Speaking Part 2 CUE CARD
2) The student's SPOKEN ANSWER (transcribed)

Your task:
- Evaluate according to IELTS Speaking Part 2 (long turn) public band descriptors.
- Talk directly TO the student using only “siz” (never “sen” or “senga”).
- NEVER write as if talking to another examiner.
- Be 100% accurate in spelling and grammar — especially for Uzbek words like “Yaxshilash”, “muammolar”, “maslahat”, etc.
- This is NOT an official score.
- Keep feedback short and simple (FREE MODE).

Assessment focus:
- Fluency and Coherence (structure, flow)
- Vocabulary (Lexical Resource)
- Grammar (range and accuracy)
- Pronunciation (clarity and natural rhythm)

Language rules:
- The entire feedback must be in Uzbek.
- English is allowed ONLY for short examples or corrections inside quotes.
- Be natural, warm, and supportive — like a real teacher guiding the student.
- Avoid robotic or examiner-like phrasing.

STRICT FORMAT RULES:
- Use EXACTLY the structure below.
- NEVER write explanations in the band section.
- In the band section, write ONLY a numeric range like “5.0–6.0” or “6.5–7.0”.

OUTPUT TEMPLATE (USE VERBATIM):

📊 *Taxminiy band (range):*
<number range only, e.g. 6.0–6.5>

🌟 *Yaxshi tomonlar:*
<content>

❗ *Asosiy muammolar:*
<content>

🛠 *Yaxshilash bo‘yicha maslahat:*
<content>

Tone:
- Warm and respectful (teacher → student)
- Always use “siz”
- Add small motivation at the end (e.g. “Shunday davom eting!”, “Sizda yaxshi potentsial bor.”)
- Be ULTRA PRECISE in Uzbek spelling and tone.
"""

"""
/ielts_speaking_part2
IELTS Speaking Part 2 AI checker (Aiogram 3)

Rules:
- Triggered only by command
- UI button only calls start_check()
- Business logic lives here
- Must validate IELTS_MODE
"""

# ─────────────────────────────
# Utils
# ─────────────────────────────

def _checker_cancel_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Cancel")]],
        resize_keyboard=True
    )

async def _ocr_image_to_text(bot, photos):
    try:
        photo = photos[-1]
        file = await bot.get_file(photo.file_id)
        image_bytes = await bot.download_file(file.file_path)

        image_b64 = base64.b64encode(image_bytes.read()).decode("utf-8")
        image_data_url = f"data:image/jpeg;base64,{image_b64}"

        response = await openai.ChatCompletion.acreate(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract IELTS Speaking Part 2 cue card text."},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            }],
            max_tokens=400,
        )
        return response["choices"][0]["message"]["content"].strip()
    except Exception:
        logger.exception("OCR failed")
        return ""

# ─────────────────────────────
# Entry
# ─────────────────────────────

@router.message(Command("ielts_speaking_part2"))
async def start_check(message: Message, state: FSMContext):
    uid = message.from_user.id

    if get_user_mode(uid) != IELTS_MODE:
        return

    limit_result = can_use_feature(uid, "speaking")
    if not limit_result["allowed"]:
        await message.answer(limit_result["message"], parse_mode="Markdown")
        return

    set_user_mode(uid, CHECKER_MODE)
    await state.set_state(WAITING_FOR_CUE_CARD)

    await message.answer(
        "📝 *IELTS Speaking Part 2 cue cardni yuboring.*\n\n"
        "Matn / rasm / ovoz yuborishingiz mumkin.",
        parse_mode="Markdown",
        reply_markup=_checker_cancel_keyboard()
    )

# ─────────────────────────────
# Receive Cue Card
# ─────────────────────────────

@router.message(StateFilter(WAITING_FOR_CUE_CARD), F.text != "❌ Cancel")
@router.message(StateFilter(WAITING_FOR_CUE_CARD), F.photo)
@router.message(StateFilter(WAITING_FOR_CUE_CARD), F.voice)
async def receive_cue_card(message: Message, state: FSMContext):
    uid = message.from_user.id

    if get_user_mode(uid) != CHECKER_MODE:
        return

    cue_text = None

    if message.text:
        cue_text = message.text.strip()
    elif message.voice:
        tg_file = await message.bot.get_file(message.voice.file_id)
        audio_bytes = await message.bot.download_file(tg_file.file_path)
        audio_file = io.BytesIO(audio_bytes.read())
        audio_file.name = "cue_card.ogg"

        result = await openai.Audio.atranscribe(model="whisper-1", file=audio_file)
        cue_text = result["text"].strip()
    elif message.photo:
        await message.answer("🖼️ Cue card rasmdan o‘qilmoqda...")
        cue_text = await _ocr_image_to_text(message.bot, message.photo)

    if not cue_text or len(cue_text.split()) < 10:
        await message.answer("❗️Cue card juda qisqa yoki noto‘g‘ri o‘qildi.")
        return

    await state.update_data(cue_card=cue_text)
    await state.set_state(WAITING_FOR_VOICE)

    await message.answer(
        "✅ *Cue card qabul qilindi.*\n\n"
        "🎙 Endi FAqat ovozli javob yuboring.\n"
        f"📌 Tavsiya: {RECOMMENDED}",
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
        await message.answer("❗️Javob juda qisqa (kamida 30 soniya).")
        return

    if duration > MAX_SECONDS:
        await message.answer("⚠️ Javob juda uzun, ammo tekshiriladi.")

    data = await state.get_data()
    cue_card = data.get("cue_card")

    await message.answer("⏳ Ovozli javob tahlil qilinmoqda...")

    try:
        tg_file = await message.bot.get_file(message.voice.file_id)
        audio_bytes = await message.bot.download_file(tg_file.file_path)
        audio_file = io.BytesIO(audio_bytes.read())
        audio_file.name = "speech.ogg"

        transcription = await openai.Audio.atranscribe(model="whisper-1", file=audio_file)

        response = await openai.ChatCompletion.acreate(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Cue Card:\n{cue_card}\n\nAnswer:\n{transcription['text']}"},
            ],
            max_tokens=600,
        )

        output_text = response["choices"][0]["message"]["content"].strip()
        await message.answer(output_text, parse_mode="Markdown")

        await send_admin_card(message.bot, uid, "New IELTS Speaking Part 2", output_text)
        log_ai_usage(uid, "speaking")

    except Exception:
        logger.exception("Speaking Part 2 AI error")
        await message.answer("❌ Xatolik yuz berdi. Keyinroq urinib ko‘ring.")

    finally:
        await state.clear()
        set_user_mode(uid, IELTS_MODE)

        from features.ielts_checkup_ui import ielts_skills_reply_keyboard
        await message.answer("✅ Tekshiruv yakunlandi.", reply_markup=ielts_skills_reply_keyboard())

# ─────────────────────────────
# Cancel
# ─────────────────────────────

@router.message(F.text == "❌ Cancel", StateFilter(WAITING_FOR_CUE_CARD))
@router.message(F.text == "❌ Cancel", StateFilter(WAITING_FOR_VOICE))
async def cancel_anytime(message: Message, state: FSMContext):
    uid = message.from_user.id

    if get_user_mode(uid) != CHECKER_MODE:
        return

    await state.clear()
    set_user_mode(uid, IELTS_MODE)

    from features.ielts_checkup_ui import ielts_skills_reply_keyboard
    await message.answer("❌ Tekshiruv bekor qilindi.", reply_markup=ielts_skills_reply_keyboard())
