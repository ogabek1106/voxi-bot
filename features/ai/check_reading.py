    # features/ai/check_reading.py
import logging
import os
import base64
import json
import re

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
CHECKER_MODE = "reading"

WAITING_FOR_PASSAGE = "reading_passage"
WAITING_FOR_ANSWERS = "reading_answers"

openai.api_key = os.getenv("OPENAI_API_KEY")

MAX_TELEGRAM_LEN = 4000

SYSTEM_PROMPT = """
You are an IELTS Reading teacher evaluating a student's performance.

You will be given:
1) IELTS Reading PASSAGE
2) Reading QUESTIONS
3) Student ANSWERS (typed or OCR)

Your task:
- Reconstruct the most likely correct answers USING the passage and questions.
- Evaluate answers according to IELTS Reading rules.
- Normalize student answers:
  T/t → TRUE
  F/f → FALSE
  NG/ng/Notgiven → NOT GIVEN
- Accept reasonable synonyms.
- Spelling is NOT strict unless meaning changes.

FREE MODE RULES:
- Do NOT explain reasons.
- Do NOT justify answers.
- Mention ONLY incorrect answers.
- NEVER list correct answers.

LANGUAGE RULES:
- Use ONLY Uzbek (Latin).
- Clear teacher tone.

OUTPUT FORMAT (STRICT JSON ONLY):

{
  "apr_band": "<band range, e.g. 5.5–6.5>",
  "raw_score": "<estimated correct answers from 0 to 40>",
  "overall": "<short overall feedback>",
  "mistakes": "<ONLY wrong answers list>",
  "advice": "<ONE short practical advice>"
}

Rules:
- No extra text.
- No markdown.
- Exact key names only.
"""

"""
/ielts_reading
IELTS Reading AI checker (Aiogram 3)

Flow (BUTTON-GATED):
1) UI starts checker
2) User sends PASSAGE + QUESTIONS (text/image, multiple)
3) User presses ➡️ Davom etish
4) User sends ANSWERS (text/image, multiple)
5) User presses ➡️ Davom etish
6) Bot evaluates and replies in Uzbek
"""

# ─────────────────────────────
# UI helpers
# ─────────────────────────────

def _reading_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="➡️ Davom etish"), KeyboardButton(text="❌ Cancel")]],
        resize_keyboard=True
    )

async def _split_and_send(message: Message, text: str):
    for i in range(0, len(text), MAX_TELEGRAM_LEN):
        await message.answer(text[i:i + MAX_TELEGRAM_LEN], parse_mode="HTML")

async def _ocr_image_to_text(bot, photos):
    try:
        photo = photos[-1]
        file = await bot.get_file(photo.file_id)
        image_bytes = await bot.download_file(file.file_path)

        image_b64 = base64.b64encode(image_bytes.read()).decode("utf-8")
        image_url = f"data:image/jpeg;base64,{image_b64}"

        response = await openai.ChatCompletion.acreate(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract ALL readable text from this image. Return ONLY text."},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }],
            max_tokens=900,
        )

        return response["choices"][0]["message"]["content"].strip()
    except Exception:
        logger.exception("OCR failed")
        return ""

async def _should_confirm_album_safe(message: Message, state: FSMContext, key: str) -> bool:
    album_id = message.media_group_id
    if not album_id:
        return True

    data = await state.get_data()
    confirmed = set(data.get(key, []))

    if album_id in confirmed:
        return False

    confirmed.add(album_id)
    await state.update_data(**{key: list(confirmed)})
    return True

def _split_passage_and_questions(text: str):
    lines = text.splitlines()
    passage, questions = [], []
    found_questions = False

    q_pattern = re.compile(
        r"^\s*(\d+[\.\)]|\bTRUE\b|\bFALSE\b|\bNOT GIVEN\b|A\.|B\.|C\.|D\.|_{3,})",
        re.IGNORECASE
    )

    for line in lines:
        if not found_questions and q_pattern.search(line):
            found_questions = True
        (questions if found_questions else passage).append(line)

    return "\n".join(passage).strip(), "\n".join(questions).strip()

def _normalize_answers(text: str) -> str:
    text = text.upper()
    text = re.sub(r"\bN\s*G\b", "NOT GIVEN", text)
    text = re.sub(r"\bNOTGIVEN\b", "NOT GIVEN", text)
    text = re.sub(r"\bT\b", "TRUE", text)
    text = re.sub(r"\bF\b", "FALSE", text)
    return text

def _format_reading_feedback(data: dict) -> str:
    return (
        f"<b>📊 Taxminiy natija:</b> {data.get('apr_band','—')} ({data.get('raw_score','—')}/40)\n\n"
        f"<b>🧠 Umumiy fikr</b>\n{data.get('overall','—')}\n\n"
        f"<b>❌ Xatolar</b>\n{data.get('mistakes','—')}\n\n"
        f"<b>🎯 Amaliy maslahat</b>\n{data.get('advice','—')}"
    )

# ─────────────────────────────
# Entry
# ─────────────────────────────

@router.message(Command("ielts_reading"))
async def start_check(message: Message, state: FSMContext):
    uid = message.from_user.id

    if get_user_mode(uid) != IELTS_MODE:
        return

    limit = can_use_feature(uid, "reading")
    if not limit["allowed"]:
        await message.answer(limit["message"], parse_mode="Markdown")
        return

    set_user_mode(uid, CHECKER_MODE)
    await state.set_state(WAITING_FOR_PASSAGE)
    await state.update_data(texts=[], answers=[], passage=None, questions=None)

    await message.answer(
        "📘 *Reading matni va savollarni yuboring.*\nMatn yoki rasm bo‘lishi mumkin.",
        parse_mode="Markdown",
        reply_markup=_reading_keyboard()
    )

# ─────────────────────────────
# Collect Passage + Questions
# ─────────────────────────────

@router.message(StateFilter(WAITING_FOR_PASSAGE), F.text.not_in({"➡️ Davom etish", "❌ Cancel"}))
@router.message(StateFilter(WAITING_FOR_PASSAGE), F.photo)
async def collect_passage(message: Message, state: FSMContext):
    uid = message.from_user.id
    if get_user_mode(uid) != CHECKER_MODE:
        return

    data = await state.get_data()
    texts = list(data.get("texts", []))  # 👈 safe copy

    if message.text:
        texts.append(message.text)

    elif message.photo:
        text = await _ocr_image_to_text(message.bot, message.photo)
        if text.strip():
            texts.append(text)

    await state.update_data(texts=texts)  # 👈 atomic update

    confirmed = await _should_confirm_album_safe(message, state, "confirmed_passage_albums")

    if confirmed:
        await message.answer(
            "📄 Qabul qilindi. Tugatgach ➡️ *Davom etish* ni bosing.",
            parse_mode="Markdown"
        )

@router.message(StateFilter(WAITING_FOR_PASSAGE), F.text == "➡️ Davom etish")
async def proceed_to_answers(message: Message, state: FSMContext):
    uid = message.from_user.id
    if get_user_mode(uid) != CHECKER_MODE:
        return

    data = await state.get_data()
    if not data.get("texts"):
        await message.answer("⚠️ Avval matn yoki rasm yuboring.")
        return

    full_text = "\n".join(data["texts"])
    passage, questions = _split_passage_and_questions(full_text)

    if not questions.strip():
        await message.answer("⚠️ Savollar aniqlanmadi. Yaxshi ko‘rinadigan savollar yuboring.")
        return

    await state.update_data(passage=passage, questions=questions)
    await state.set_state(WAITING_FOR_ANSWERS)

    await message.answer(
        "✍️ *Javoblaringizni yuboring.*",
        parse_mode="Markdown",
        reply_markup=_reading_keyboard()
    )

# ─────────────────────────────
# Collect Answers
# ─────────────────────────────

@router.message(StateFilter(WAITING_FOR_ANSWERS), F.text.not_in({"➡️ Davom etish", "❌ Cancel"}))
@router.message(StateFilter(WAITING_FOR_ANSWERS), F.photo)
async def collect_answers(message: Message, state: FSMContext):
    uid = message.from_user.id
    if get_user_mode(uid) != CHECKER_MODE:
        return

    data = await state.get_data()
    answers = list(data.get("answers", []))  # 👈 safe copy

    if message.text:
        answers.append(message.text)

    elif message.photo:
        text = await _ocr_image_to_text(message.bot, message.photo)
        if text.strip():
            answers.append(text)

    await state.update_data(answers=answers)  # 👈 atomic update

    confirmed = await _should_confirm_album_safe(message, state, "confirmed_answers_albums")

    if confirmed:
        await message.answer(
            "✍️ Qabul qilindi. Tugatgach ➡️ *Davom etish* ni bosing.",
            parse_mode="Markdown"
        )

@router.message(StateFilter(WAITING_FOR_ANSWERS), F.text == "➡️ Davom etish")
async def finalize_reading(message: Message, state: FSMContext):
    uid = message.from_user.id
    if get_user_mode(uid) != CHECKER_MODE:
        return

    data = await state.get_data()
    if not data.get("answers"):
        await message.answer("⚠️ Avval javoblarni yuboring.")
        return

    passage = data.get("passage", "")
    questions = data.get("questions", "")
    answers_raw = "\n".join(data.get("answers", []))
    answers = _normalize_answers(answers_raw)

    await message.answer("⏳ Reading tahlil qilinmoqda...")

    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"PASSAGE:\n{passage}\n\nQUESTIONS:\n{questions}\n\nSTUDENT ANSWERS:\n{answers}"},
            ],
            max_tokens=700,
        )

        raw = response["choices"][0]["message"]["content"]
        ai_data = json.loads(raw)

        output = _format_reading_feedback(ai_data)
        await _split_and_send(message, output)

        await send_admin_card(message.bot, uid, "New IELTS Reading", output)
        log_ai_usage(uid, "reading")

    except Exception:
        logger.exception("Reading AI error")
        await message.answer("❌ Xatolik yuz berdi. Keyinroq urinib ko‘ring.")

    finally:
        await state.clear()
        set_user_mode(uid, IELTS_MODE)

        from features.ielts_checkup_ui import ielts_skills_reply_keyboard
        await message.answer("✅ Tekshiruv yakunlandi.", reply_markup=ielts_skills_reply_keyboard())

# ─────────────────────────────
# Cancel
# ─────────────────────────────

@router.message(F.text == "❌ Cancel", StateFilter(WAITING_FOR_PASSAGE))
@router.message(F.text == "❌ Cancel", StateFilter(WAITING_FOR_ANSWERS))
async def cancel_anytime(message: Message, state: FSMContext):
    uid = message.from_user.id
    if get_user_mode(uid) != CHECKER_MODE:
        return

    await state.clear()
    set_user_mode(uid, IELTS_MODE)

    from features.ielts_checkup_ui import ielts_skills_reply_keyboard
    await message.answer("❌ Tekshiruv bekor qilindi.", reply_markup=ielts_skills_reply_keyboard())
