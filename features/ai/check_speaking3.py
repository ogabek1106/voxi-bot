# features/ai/check_speaking3.py
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
CHECKER_MODE = "speaking_part3"

WAITING_FOR_QUESTION = "sp3_question"
WAITING_FOR_VOICE = "sp3_voice"

openai.api_key = os.getenv("OPENAI_API_KEY")

MIN_SECONDS = 20
MAX_SECONDS = 120
RECOMMENDED = "30–60 soniya"

SYSTEM_PROMPT = """
You are an IELTS Speaking Part 3 teacher giving precise and supportive feedback directly to the student.

You will be given:
1) The full set of IELTS Speaking Part 3 QUESTIONS (may include several discussion topics)
2) The student's SPOKEN ANSWER (transcribed)

Your task:
- Carefully read ALL the questions — even if there are multiple topics (e.g. “School rules” and “Working in the legal profession”).
- For EACH question, check if the student answered it or not:
    • If answered → give short feedback (1–2 sentences) in Uzbek.
    • If NOT answered → write exactly: “<number>-savolga siz javob bermadingiz.”
- Never skip or merge questions, even if the student didn’t mention the topic.
- Detect and list all questions in order (1, 2, 3, 4, etc.).
- Talk directly TO the student using only “siz” (never “sen” or “senga”).
- Keep spelling and grammar 100% correct — be ULTRA PRECISE.
- This is NOT an official score.

Assessment focus:
- Fluency and Coherence (connected ideas)
- Vocabulary (range and accuracy)
- Grammar (range and correctness)
- Pronunciation (clarity and natural rhythm)

Language rules:
- Feedback must be entirely in Uzbek.
- English allowed only for short examples or corrections inside quotes.
- Use short, natural sentences and a warm teacher-like tone.
- Do not use robotic or examiner-like phrasing.

STRICT FORMAT RULES:
- Use EXACTLY the structure below.
- In the band section, write ONLY a numeric range (e.g. “6.0–6.5”).
- In “Savollar bo‘yicha kuzatuvlar”, give feedback for EVERY question in the uploaded text/image, including unanswered ones.

OUTPUT TEMPLATE (USE VERBATIM):

📊 *Taxminiy band (range):*
<number range only, e.g. 6.0–6.5>

🌟 *Yaxshi tomonlar:*
<general strengths in 2–4 short sentences>

❗ *Savollar bo‘yicha kuzatuvlar:*
- <feedback or “1-savolga siz javob bermadingiz.”>
- <feedback or “2-savolga siz javob bermadingiz.”>
- <feedback or “3-savolga siz javob bermadingiz.”>
- <feedback or “4-savolga siz javob bermadingiz.”>
- <feedback or “5-savolga siz javob bermadingiz.”>
- <feedback or “6-savolga siz javob bermadingiz.”>
(Add more automatically if the question set has more.)

🛠 *Yaxshilash bo‘yicha maslahat:*
<1–2 sentences of advice + motivational ending>

Tone:
- Warm and respectful (teacher → student)
- Always use “siz”
- Each feedback line must be short, clear, and natural.
- End with a motivating sentence (e.g. “Shunday davom eting!”, “Sizda yaxshi potentsial bor.”)
"""


"""
/ielts_speaking_part3
IELTS Speaking Part 3 AI checker (Aiogram 3)

Rules:
- Triggered only by command
- UI button calls start_check()
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
                    {"type": "text", "text": "Extract IELTS Speaking Part 3 questions."},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            }],
            max_tokens=300,
        )
        return response["choices"][0]["message"]["content"].strip()
    except Exception:
        logger.exception("OCR failed")
        return ""

# ─────────────────────────────
# Entry
# ─────────────────────────────

@router.message(Command("ielts_speaking_part3"))
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
        "🧠 *IELTS Speaking Part 3 savollarini yuboring.*\n\n"
        "Matn / rasm / ovoz yuborishingiz mumkin.",
        parse_mode="Markdown",
        reply_markup=_checker_cancel_keyboard()
    )

# ─────────────────────────────
# Receive Questions
# ─────────────────────────────

@router.message(StateFilter(WAITING_FOR_QUESTION), F.text != "❌ Cancel")
@router.message(StateFilter(WAITING_FOR_QUESTION), F.photo)
@router.message(StateFilter(WAITING_FOR_QUESTION), F.voice)
async def receive_questions(message: Message, state: FSMContext):
    uid = message.from_user.id

    if get_user_mode(uid) != CHECKER_MODE:
        return

    questions = None

    if message.text:
        questions = message.text.strip()
    elif message.voice:
        tg_file = await message.bot.get_file(message.voice.file_id)
        audio_bytes = await message.bot.download_file(tg_file.file_path)
        audio_file = io.BytesIO(audio_bytes.read())
        audio_file.name = "questions.ogg"

        result = await openai.Audio.atranscribe(model="whisper-1", file=audio_file)
        questions = result["text"].strip()
    elif message.photo:
        await message.answer("🖼️ Savollar rasmdan o‘qilmoqda...")
        questions = await _ocr_image_to_text(message.bot, message.photo)

    if not questions or len(questions.split()) < 10:
        await message.answer("❗️Savollar juda qisqa yoki noto‘g‘ri o‘qildi.")
        return

    await state.update_data(questions=questions)
    await state.set_state(WAITING_FOR_VOICE)

    await message.answer(
        "✅ *Savollar qabul qilindi.*\n\n"
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
        await message.answer("❗️Javob juda qisqa (kamida 20 soniya).")
        return

    if duration > MAX_SECONDS:
        await message.answer("⚠️ Javob juda uzun, ammo tekshiriladi.")

    data = await state.get_data()
    questions = data.get("questions")

    await message.answer("⏳ Ovozli javob tahlil qilinmoqda...")

    try:
        tg_file = await message.bot.get_file(message.voice.file_id)
        audio_bytes = await message.bot.download_file(tg_file.file_path)
        audio_file = io.BytesIO(audio_bytes.read())
        audio_file.name = "answer.ogg"

        transcription = await openai.Audio.atranscribe(model="whisper-1", file=audio_file)

        response = await openai.ChatCompletion.acreate(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Questions:\n{questions}\n\nAnswer:\n{transcription['text']}"},
            ],
            max_tokens=700,
        )

        output_text = response["choices"][0]["message"]["content"].strip()
        await message.answer(output_text, parse_mode="Markdown")

        await send_admin_card(message.bot, uid, "New IELTS Speaking Part 3", output_text)
        log_ai_usage(uid, "speaking")

    except Exception:
        logger.exception("Speaking Part 3 AI error")
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
