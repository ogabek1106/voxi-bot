# features/ai/writing_task1.py
"""
/ielts_writing_task1
IELTS Writing Task 1 AI checker (Aiogram 3)

Rules:
- Triggered only by command
- UI button only sends the command
- Business logic lives here
- Must validate IELTS_MODE
"""

import logging
import os
import base64
import asyncio
from aiogram.filters import StateFilter
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

from database import (
    get_user_mode,
    set_user_mode,
    clear_user_mode,
    log_ai_usage,
)

from features.ai.check_limits import can_use_feature
from features.admin_feedback import send_admin_card, store_writing_essay

import openai

logger = logging.getLogger(__name__)
router = Router()

IELTS_MODE = "ielts_check_up"
CHECKER_MODE = "writing_task1"

WAITING_FOR_TOPIC = "wt1_topic"
WAITING_FOR_REPORT = "wt1_report"

openai.api_key = os.getenv("OPENAI_API_KEY")

SYSTEM_PROMPT = """
You are an IELTS Writing Task 1 evaluator.

You will be given:
1) The IELTS Writing Task 1 QUESTION (graph, table, process, or map)
2) The student's REPORT

Your task:
- Evaluate the report STRICTLY based on the given Task 1 question.
- Follow ONLY official public IELTS Writing Task 1 band descriptors.
- Do NOT invent criteria.
- Do NOT claim this is an official IELTS score.

Assessment focus (internal only):
1) Task Achievement
2) Coherence and Cohesion
3) Lexical Resource
4) Grammatical Range and Accuracy

Task 1 rules:
- Check if an OVERVIEW is present.
- Check key features and comparisons.
- No opinions or conclusions required.

Language rules:
- ALL explanations must be in Uzbek.
- English is allowed ONLY for:
  - Quoting incorrect sentences
  - Showing corrected examples
- Do NOT translate the whole report.

IMPORTANT OUTPUT RULES (STRICT):
- You MUST use EXACTLY the structure below.
- Do NOT add or remove sections.
- Do NOT add text outside sections.

EXACT OUTPUT TEMPLATE:

📊 *Umumiy taxminiy band (range):*
<content>

🌟 *Sizning ustun tarafingiz:*
<content>

❗ *Muhim xatolar:*
<content>

📝 *So‘z yozilishidagi / tanlashdagi xatolar:*
<content>

🔎 *Grammatik xatolar:*
<content>

FREE MODE LIMITS (MANDATORY):
- Band: range only (e.g. 5.5–6.0)
- Strength: max 1–2 short sentences
- Muhim xatolar: max 2 points
- Vocabulary: max 2 examples (wrong → correct)
- Grammar: error TYPES only
- Do NOT rewrite the report

Tone:
- Calm, teacher-like
- No exaggeration
- No unnecessary praise

IMPORTANT:
- This is an ESTIMATED band score, not official.
"""


MAX_TELEGRAM_LEN = 4000


def _checker_cancel_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Cancel")]],
        resize_keyboard=True
    )

async def _split_and_send(message: Message, text: str):
    for i in range(0, len(text), MAX_TELEGRAM_LEN):
        await message.answer(text[i:i + MAX_TELEGRAM_LEN], parse_mode="Markdown")


async def _ocr_image_to_text(bot, photos):
    try:
        photo = photos[-1]
        file = await bot.get_file(photo.file_id)
        image_bytes = await bot.download_file(file.file_path)

        image_b64 = base64.b64encode(image_bytes.read()).decode("utf-8")
        image_data_url = f"data:image/jpeg;base64,{image_b64}"

        response = await openai.ChatCompletion.acreate(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract ALL readable text. Return ONLY text."},
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                }
            ],
            max_tokens=800,
        )

        return response["choices"][0]["message"]["content"].strip()

    except Exception:
        logger.exception("OCR failed")
        return ""


# ─────────────────────────────
# Entry
# ─────────────────────────────

@router.message(Command("ielts_writing_task1"))
async def start_check(message: Message, state: FSMContext):
    uid = message.from_user.id

    # 🔒 MODE GUARD
    if get_user_mode(uid) != IELTS_MODE:
        return

    # 🔒 USAGE LIMIT
    limit_result = can_use_feature(uid, "writing")
    if not limit_result["allowed"]:
        await message.answer(limit_result["message"], parse_mode="Markdown")
        return

    set_user_mode(uid, CHECKER_MODE)
    await state.set_state(WAITING_FOR_TOPIC)

    await message.answer(
        "📝 *IELTS Writing Task 1 SAVOLINI yuboring.*\n\n"
        "Grafik, jadval, jarayon yoki xarita bo‘lishi mumkin.\n"
        "Matn yoki rasm yuboring.",
        parse_mode="Markdown",
        reply_markup=_checker_cancel_keyboard()
    )


# ─────────────────────────────
# Receive Topic
# ─────────────────────────────

@router.message(StateFilter(WAITING_FOR_TOPIC), F.text != "❌ Cancel")
async def receive_topic(message: Message, state: FSMContext):
    uid = message.from_user.id

    if get_user_mode(uid) != CHECKER_MODE:
        return

    if message.text:
        topic = message.text.strip()
    elif message.photo:
        await message.answer("🖼️ Savol rasmdan o‘qilmoqda...")
        topic = await _ocr_image_to_text(message.bot, message.photo)
    else:
        await message.answer("❗️Savolni matn yoki rasm sifatida yuboring.")
        return

    if len(topic.split()) < 5:
        await message.answer("❗️Savol juda qisqa yoki noto‘g‘ri o‘qildi.")
        return

    await state.update_data(topic=topic)
    await state.set_state(WAITING_FOR_REPORT)

    await message.answer(
        "✅ *Savol qabul qilindi.*\n\n"
        "Endi ushbu savol bo‘yicha javobingizni yuboring.\n"
        "❗️Kamida ~80 so‘z.",
        parse_mode="Markdown"
    )


# ─────────────────────────────
# Receive Report
# ─────────────────────────────

@router.message(StateFilter(WAITING_FOR_REPORT), F.text != "❌ Cancel")
async def receive_report(message: Message, state: FSMContext):
    uid = message.from_user.id

    if get_user_mode(uid) != CHECKER_MODE:
        return

    data = await state.get_data()
    topic = data.get("topic")

    if not topic:
        await message.answer("❗️Avval savolni yuboring.")
        return

    if message.text:
        report = message.text.strip()
    elif message.photo:
        await message.answer("🖼️ Javob rasmdan o‘qilmoqda...")
        report = await _ocr_image_to_text(message.bot, message.photo)
    else:
        await message.answer("❗️Javobni matn yoki rasm sifatida yuboring.")
        return

    if len(report.split()) < 80:
        await message.answer("❗️Matn juda qisqa.")
        return

    await message.answer("⏳ Tekshirilmoqda, iltimos kuting...")

    await store_writing_essay(message.bot, report, "#writing1")

    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Question:\n{topic}\n\nReport:\n{report}"},
            ],
            max_tokens=600,
        )

        output_text = response["choices"][0]["message"]["content"].strip()
        await _split_and_send(message, output_text)
        await send_admin_card(message.bot, uid, "New IELTS Writing Task 1", output_text)
        log_ai_usage(uid, "writing")

    except Exception:
        logger.exception("AI error")
        await message.answer("❌ Xatolik yuz berdi. Keyinroq urinib ko‘ring.")

    finally:
        await state.clear()
        set_user_mode(uid, IELTS_MODE)
        from features.ielts_checkup_ui import ielts_skills_reply_keyboard
        await message.answer("✅ Tekshiruv yakunlandi.", reply_markup=ielts_skills_reply_keyboard())


# ─────────────────────────────
# Cancel
# ─────────────────────────────

@router.message(
    F.text == "❌ Cancel",
    StateFilter(WAITING_FOR_TOPIC) | StateFilter(WAITING_FOR_REPORT)
)
async def cancel_anytime(message: Message, state: FSMContext):
    uid = message.from_user.id

    if get_user_mode(uid) != CHECKER_MODE:
        return

    await state.clear()
    set_user_mode(uid, IELTS_MODE)

    from features.ielts_checkup_ui import ielts_skills_reply_keyboard
    await message.answer(
        "❌ Tekshiruv bekor qilindi.",
        reply_markup=ielts_skills_reply_keyboard()
    )
