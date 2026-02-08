# features/ai/check_listening.py
import logging
import os
import io
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
CHECKER_MODE = "listening"

WAITING_FOR_AUDIO = "listening_audio"
WAITING_FOR_QUESTIONS = "listening_questions"
WAITING_FOR_ANSWERS = "listening_answers"

openai.api_key = os.getenv("OPENAI_API_KEY")
MAX_TELEGRAM_LEN = 4000


SYSTEM_PROMPT = """
You are an IELTS Listening teacher evaluating a student's performance.

You will be given:
1) The Listening AUDIO transcription
2) Listening QUESTIONS (text extracted from images)
3) The student's ANSWERS (typed or OCR)

Your task:
- Reconstruct the most likely correct answers from the audio USING the questions.
- Evaluate the student's answers strictly according to IELTS Listening rules.
- If the audio or question is unclear, DO NOT invent explanations.
  Say clearly that evaluation is limited or unclear.
- This is NOT an official IELTS score.

IELTS Listening rules:
- Spelling matters.
- Singular / plural matters.
- Word limits matter.
- Articles are usually ignored unless meaning changes.
- Numbers must be exact.
- Accept only reasonable IELTS variants.

LANGUAGE RULES:
- Use ONLY correct Uzbek (Latin).
- Simple, natural teacher language.
- No awkward or literal translations.

FREE MODE RULE:
- Do NOT explain reasons.
- Do NOT justify corrections.
- Only list incorrect answers briefly.

ERROR RULES:
- Mention ONLY wrong or problematic answers.
- NEVER list correct answers.
- NEVER explain why a correct answer is correct.

CRITICAL LOGIC RULE (LISTENING):
- If the estimated band is BELOW 7.0, at least ONE problem MUST be reported.
- It is NOT allowed to say “no mistakes” for band < 7.
- If confirmation is impossible due to unclear audio or OCR, say so explicitly.

OUTPUT FORMAT (STRICT):

Return ONLY a valid JSON object with EXACTLY these keys:

{
  "apr_band": "<band range, e.g. 5.0–6.0>",
  "raw_score": "<estimated correct answers from 0 to 40>",
  "overall": "<short overall feedback>",
  "mistakes": "<ONLY a list of wrong answer numbers and student answers. NO explanations.>",
  "spelling": "<spelling or form issues OR 'Yo‘q'>",
  "traps": "<listening traps OR 'Aniqlanmadi'>",
  "advice": "<ONE short practical advice>"
}

Rules:
- Do NOT add any extra text.
- Do NOT change key names.
- Keep feedback short.
"""

# ─────────────────────────────
# UI helpers
# ─────────────────────────────

def _listening_keyboard():
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


async def _transcribe_audio(bot, msg: Message) -> str:
    try:
        file_id = (
            msg.voice.file_id if msg.voice else
            msg.audio.file_id if msg.audio else
            msg.video.file_id if msg.video else
            msg.document.file_id
        )

        file = await bot.get_file(file_id)
        audio_bytes = await bot.download_file(file.file_path)

        audio_file = io.BytesIO(audio_bytes.read())
        audio_file.name = "audio.wav"

        res = await openai.Audio.atranscribe(
            model="whisper-1",
            file=audio_file
        )
        return res["text"].strip()

    except Exception:
        logger.exception("Audio transcription failed")
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


def _format_listening_feedback(data: dict) -> str:
    def norm(x):
        if isinstance(x, list):
            return "; ".join(str(i) for i in x)
        return x or "—"

    band = data.get("apr_band", "—")
    raw = data.get("raw_score")

    score_line = (
        f"<b>📊 Taxminiy natija:</b> {band} ({raw}/40)"
        if raw else
        f"<b>📊 Taxminiy natija:</b> {band}"
    )

    return (
        f"{score_line}\n\n"
        f"<b>🧠 Umumiy fikr</b>\n{norm(data.get('overall'))}\n\n"
        f"<b>❌ Xatolar</b>\n{norm(data.get('mistakes'))}\n\n"
        f"<b>📝 Imlo yoki shakl</b>\n{norm(data.get('spelling'))}\n\n"
        f"<b>⚠️ IELTS listening tuzoqlari</b>\n{norm(data.get('traps'))}\n\n"
        f"<b>🎯 Amaliy maslahat</b>\n{norm(data.get('advice'))}"
    )


# ─────────────────────────────
# Entry
# ─────────────────────────────

@router.message(Command("check_listening"))
async def start_listening(message: Message, state: FSMContext):
    uid = message.from_user.id

    if get_user_mode(uid) != IELTS_MODE:
        return

    limit = can_use_feature(uid, "listening")
    if not limit["allowed"]:
        await message.answer(limit["message"], parse_mode="Markdown")
        return

    set_user_mode(uid, CHECKER_MODE)
    await state.set_state(WAITING_FOR_AUDIO)
    await state.update_data(audios=[], audio_text=None, questions=[], answers=[])

    await message.answer(
        "🎧 *Listening audio yuboring.*\nBir nechta fayl yuborishingiz mumkin.",
        parse_mode="Markdown",
        reply_markup=_listening_keyboard()
    )


# ─────────────────────────────
# Collect Audio
# ─────────────────────────────

@router.message(StateFilter(WAITING_FOR_AUDIO), F.voice | F.audio | F.video | F.document)
async def collect_audio(message: Message, state: FSMContext):
    uid = message.from_user.id
    if get_user_mode(uid) != CHECKER_MODE:
        return

    data = await state.get_data()
    audios = list(data.get("audios", []))
    audios.append(message)

    await state.update_data(audios=audios)

    confirmed = await _should_confirm_album_safe(message, state, "confirmed_audio_albums")
    if confirmed:
        await message.answer(
            "🎧 *Qabul qilindi.*\nYana bo‘lsa yuboring, tugatgach ➡️ *Davom etish* ni bosing.",
            parse_mode="Markdown"
        )


@router.message(StateFilter(WAITING_FOR_AUDIO), F.text == "➡️ Davom etish")
async def proceed_to_questions(message: Message, state: FSMContext):
    uid = message.from_user.id
    if get_user_mode(uid) != CHECKER_MODE:
        return

    data = await state.get_data()
    audios = data.get("audios", [])
    if not audios:
        await message.answer("⚠️ Avval audio yuboring.")
        return

    transcripts = []
    for msg in audios:
        text = await _transcribe_audio(message.bot, msg)
        if text:
            transcripts.append(text)

    audio_text = "\n".join(transcripts)
    if not audio_text.strip():
        await message.answer("⚠️ Audio matnini aniqlab bo‘lmadi. Boshqa audio yuboring.")
        return

    await state.update_data(audio_text=audio_text)
    await state.set_state(WAITING_FOR_QUESTIONS)

    await message.answer(
        "📸 *Listening savollari rasmlarini yuboring.*",
        parse_mode="Markdown",
        reply_markup=_listening_keyboard()
    )


# ─────────────────────────────
# Collect Questions
# ─────────────────────────────

@router.message(StateFilter(WAITING_FOR_QUESTIONS), F.photo)
async def collect_questions(message: Message, state: FSMContext):
    uid = message.from_user.id
    if get_user_mode(uid) != CHECKER_MODE:
        return

    data = await state.get_data()
    questions = list(data.get("questions", []))

    text = await _ocr_image_to_text(message.bot, message.photo)
    if text.strip():
        questions.append(text)

    await state.update_data(questions=questions)

    confirmed = await _should_confirm_album_safe(message, state, "confirmed_question_albums")
    if confirmed:
        await message.answer(
            "🖼️ *Qabul qilindi.*\nYana bo‘lsa yuboring, tugatgach ➡️ *Davom etish* ni bosing.",
            parse_mode="Markdown"
        )


@router.message(StateFilter(WAITING_FOR_QUESTIONS), F.text == "➡️ Davom etish")
async def proceed_to_answers(message: Message, state: FSMContext):
    uid = message.from_user.id
    if get_user_mode(uid) != CHECKER_MODE:
        return

    data = await state.get_data()
    if not data.get("questions"):
        await message.answer("⚠️ Avval savollar rasmlarini yuboring.")
        return

    await state.set_state(WAITING_FOR_ANSWERS)
    await message.answer(
        "✍️ *Javoblaringizni yuboring.*",
        parse_mode="Markdown",
        reply_markup=_listening_keyboard()
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
    answers = list(data.get("answers", []))

    if message.text:
        answers.append(message.text)
    elif message.photo:
        text = await _ocr_image_to_text(message.bot, message.photo)
        if text.strip():
            answers.append(text)

    await state.update_data(answers=answers)

    confirmed = await _should_confirm_album_safe(message, state, "confirmed_answers_albums")
    if confirmed:
        await message.answer(
            "✍️ *Qabul qilindi.*\nTugatgach ➡️ *Davom etish* ni bosing.",
            parse_mode="Markdown"
        )


@router.message(StateFilter(WAITING_FOR_ANSWERS), F.text == "➡️ Davom etish")
async def finalize_listening(message: Message, state: FSMContext):
    uid = message.from_user.id
    if get_user_mode(uid) != CHECKER_MODE:
        return

    data = await state.get_data()
    if not data.get("answers"):
        await message.answer("⚠️ Avval javoblarni yuboring.")
        return

    audio_text = data.get("audio_text", "")
    questions = "\n".join(data.get("questions", []))
    answers = "\n".join(data.get("answers", []))

    await message.answer("⏳ Listening tahlil qilinmoqda...")

    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Listening Audio Transcript:\n{audio_text}\n\nListening Questions:\n{questions}\n\nStudent Answers:\n{answers}"},
            ],
            max_tokens=700,
        )

        raw = response["choices"][0]["message"]["content"]
        ai_data = json.loads(raw)

        output = _format_listening_feedback(ai_data)
        await _split_and_send(message, output)

        await send_admin_card(message.bot, uid, "New IELTS Listening", output)
        log_ai_usage(uid, "listening")

    except Exception:
        logger.exception("Listening AI error")
        await message.answer("❌ Xatolik yuz berdi. Keyinroq urinib ko‘ring.")

    finally:
        await state.clear()
        set_user_mode(uid, IELTS_MODE)

        from features.ielts_checkup_ui import ielts_skills_reply_keyboard
        await message.answer("✅ Tekshiruv yakunlandi.", reply_markup=ielts_skills_reply_keyboard())


# ─────────────────────────────
# Cancel
# ─────────────────────────────

@router.message(F.text == "❌ Cancel", StateFilter(WAITING_FOR_AUDIO))
@router.message(F.text == "❌ Cancel", StateFilter(WAITING_FOR_QUESTIONS))
@router.message(F.text == "❌ Cancel", StateFilter(WAITING_FOR_ANSWERS))
async def cancel_anytime(message: Message, state: FSMContext):
    uid = message.from_user.id
    if get_user_mode(uid) != CHECKER_MODE:
        return

    await state.clear()
    set_user_mode(uid, IELTS_MODE)

    from features.ielts_checkup_ui import ielts_skills_reply_keyboard
    await message.answer("❌ Tekshiruv bekor qilindi.", reply_markup=ielts_skills_reply_keyboard())
