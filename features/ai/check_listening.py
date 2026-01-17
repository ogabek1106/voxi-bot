# features/ai/check_listening.py
"""
/check_listening
IELTS Listening AI checker (FREE MODE, command-based)

Flow:
1) User sends /check_listening
2) Bot asks for LISTENING AUDIO (mp3 / mp4 / voice / document)
3) User sends audio
4) Bot transcribes audio (Whisper)
5) Bot asks for QUESTION IMAGES
6) User sends images
7) Bot asks for USER ANSWERS (text or image)
8) Bot evaluates and replies in Uzbek
"""

import logging
import os
import io
import base64

from telegram import Update
from telegram.ext import (
    CallbackContext,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    Filters,
)
from telegram.ext import DispatcherHandlerStop

import openai

from features.ai.check_limits import can_use_feature
from features.admin_feedback import send_admin_card
from database import (
    log_ai_usage,
    set_checker_mode,
    clear_checker_mode,
    get_checker_mode,
)

logger = logging.getLogger(__name__)

openai.api_key = os.getenv("OPENAI_API_KEY")

# ---------- States ----------
WAITING_FOR_AUDIO = 0
WAITING_FOR_QUESTIONS = 1
WAITING_FOR_ANSWERS = 2

# ---------- SYSTEM PROMPT ----------
SYSTEM_PROMPT = """
You are an IELTS Listening teacher evaluating a student's performance.

You will be given:
1) The Listening AUDIO transcription
2) Images of Listening QUESTIONS (already extracted)
3) The student's ANSWERS (typed or OCR)

Your task:
- Reconstruct the most likely correct answers from the audio USING the questions.
- Evaluate the student's answers strictly according to IELTS Listening rules.
- Do NOT invent answers if the audio is unclear — say this clearly.
- This is NOT an official IELTS score.

IELTS Listening rules:
- Spelling matters.
- Singular / plural matters.
- Word limits matter.
- Articles are usually ignored unless meaning changes.
- Numbers must be correct.
- Accept reasonable variants IELTS would accept.

Language rules:
- ALL explanations must be in Uzbek.
- English ONLY for:
  - wrong → correct examples
  - quoting answers
- Do NOT translate the questions.

STRICT OUTPUT FORMAT (DO NOT CHANGE):

📊 *Umumiy natija:*
<score range /40 + taxminiy band>

❌ *Xatolar va sabablari:*
<max 3 short explanations>

📝 *Imlo yoki shakl xatolari:*
<wrong → correct examples>

⚠️ *IELTS listening tuzoqlari:*
<short list>

🎯 *Maslahat:*
<short practical advice>

Tone:
- Calm
- Teacher-like
- Natural Uzbek
- Supportive, not robotic

IMPORTANT:
- This is an ESTIMATED result.
"""

MAX_TELEGRAM_LEN = 4000


# ---------- Helpers ----------

def _send_long_message(message, text: str):
    if not text:
        return
    for i in range(0, len(text), MAX_TELEGRAM_LEN):
        message.reply_text(
            text[i:i + MAX_TELEGRAM_LEN],
            parse_mode="Markdown"
        )


def _ocr_image_to_text(bot, photos):
    try:
        photo = photos[-1]
        tg_file = bot.get_file(photo.file_id)
        image_bytes = tg_file.download_as_bytearray()

        image_b64 = base64.b64encode(image_bytes).decode()
        image_url = f"data:image/jpeg;base64,{image_b64}"

        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Extract ALL readable text from this image.\n"
                                "Return ONLY the text.\n"
                                "Do NOT explain."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": image_url},
                        },
                    ],
                }
            ],
            max_tokens=800,
        )

        return response["choices"][0]["message"]["content"].strip()

    except Exception:
        logger.exception("OCR failed")
        return ""


# ---------- Handlers ----------

def start_check(update: Update, context: CallbackContext):
    from features.sub_check import require_subscription
    if not require_subscription(update, context):
        return ConversationHandler.END

    user = update.effective_user
    if not user:
        return ConversationHandler.END

    limit = can_use_feature(user.id, "listening")
    if not limit["allowed"]:
        from features.ielts_checkup_ui import _main_user_keyboard
        update.message.reply_text(
            limit["message"],
            parse_mode="Markdown",
            reply_markup=_main_user_keyboard()
        )
        raise DispatcherHandlerStop

    set_checker_mode(user.id, "listening")
    context.user_data.clear()

    from features.ielts_checkup_ui import _checker_cancel_keyboard
    update.message.reply_text(
        "🎧 *IELTS Listening audio yuboring.*\n\n"
        "Qabul qilinadi:\n"
        "• mp3 / mp4\n"
        "• Voice message\n"
        "• Audio fayl",
        parse_mode="Markdown",
        reply_markup=_checker_cancel_keyboard()
    )
    return WAITING_FOR_AUDIO


def receive_audio(update: Update, context: CallbackContext):
    message = update.message
    user = update.effective_user

    if get_checker_mode(user.id) != "listening":
        return ConversationHandler.END

    if not (message.voice or message.audio or message.video or message.document):
        message.reply_text("❗️Audio fayl yuboring.")
        return WAITING_FOR_AUDIO

    message.reply_text("🎧 Audio o‘qilmoqda...", parse_mode="Markdown")

    try:
        # ---------- Download audio ----------
        if message.voice:
            tg_file = context.bot.get_file(message.voice.file_id)
            audio_bytes = tg_file.download_as_bytearray()
            audio_name = "listening.ogg"
        elif message.audio:
            tg_file = context.bot.get_file(message.audio.file_id)
            audio_bytes = tg_file.download_as_bytearray()
            audio_name = "listening.mp3"
        elif message.video:
            tg_file = context.bot.get_file(message.video.file_id)
            audio_bytes = tg_file.download_as_bytearray()
            audio_name = "listening.mp4"
        else:  # document
            tg_file = context.bot.get_file(message.document.file_id)
            audio_bytes = tg_file.download_as_bytearray()
            audio_name = message.document.file_name or "listening"

        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = audio_name

        transcription = openai.Audio.transcribe(
            model="whisper-1",
            file=audio_file
        )["text"].strip()

        context.user_data["audio_text"] = transcription

    except Exception:
        logger.exception("Audio transcription failed")
        message.reply_text(
            "❌ Audio o‘qilmadi. Iltimos, boshqa audio yuboring."
        )
        return WAITING_FOR_AUDIO

    message.reply_text(
        "✅ Audio qabul qilindi.\n\n"
        "📸 Endi *Listening savollari rasmlarini* yuboring.",
        parse_mode="Markdown"
    )
    return WAITING_FOR_QUESTIONS


def receive_questions(update: Update, context: CallbackContext):
    message = update.message
    user = update.effective_user

    if get_checker_mode(user.id) != "listening":
        return ConversationHandler.END

    if not message.photo:
        message.reply_text("❗️Savollarni rasm sifatida yuboring.")
        return WAITING_FOR_QUESTIONS

    message.reply_text("🖼️ Savollar o‘qilmoqda...", parse_mode="Markdown")
    questions_text = _ocr_image_to_text(context.bot, message.photo)

    if len(questions_text.split()) < 10:
        message.reply_text(
            "❗️Savollar to‘liq o‘qilmadi. Iltimos, aniqroq rasm yuboring."
        )
        return WAITING_FOR_QUESTIONS

    context.user_data["questions"] = questions_text

    message.reply_text(
        "✍️ Endi *javoblaringizni* yuboring.\n\n"
        "Matn yoki qo‘lda yozilgan rasm bo‘lishi mumkin.",
        parse_mode="Markdown"
    )
    return WAITING_FOR_ANSWERS


def receive_answers(update: Update, context: CallbackContext):
    message = update.message
    user = update.effective_user

    if get_checker_mode(user.id) != "listening":
        return ConversationHandler.END

    if message.text:
        answers = message.text.strip()
    elif message.photo:
        message.reply_text("🖼️ Javoblar rasmdan o‘qilmoqda...", parse_mode="Markdown")
        answers = _ocr_image_to_text(context.bot, message.photo)
    else:
        message.reply_text("❗️Javoblarni matn yoki rasm sifatida yuboring.")
        return WAITING_FOR_ANSWERS

    if len(answers.split()) < 5:
        message.reply_text("❗️Javoblar juda qisqa yoki noto‘g‘ri o‘qildi.")
        return WAITING_FOR_ANSWERS

    message.reply_text("*⏳ Listening tahlil qilinmoqda...*", parse_mode="Markdown")

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Listening Audio Transcript:\n{context.user_data['audio_text']}\n\n"
                        f"Listening Questions:\n{context.user_data['questions']}\n\n"
                        f"Student Answers:\n{answers}"
                    ),
                },
            ],
            max_tokens=700,
        )

        output = response["choices"][0]["message"]["content"].strip()
        _send_long_message(message, output)

        send_admin_card(
            context.bot,
            user.id,
            "New IELTS Listening feedback",
            output
        )

        log_ai_usage(user.id, "listening")

    except Exception:
        logger.exception("Listening AI error")
        message.reply_text("❌ Xatolik yuz berdi. Keyinroq urinib ko‘ring.")

    finally:
        clear_checker_mode(user.id)
        context.user_data.clear()

        from features.ielts_checkup_ui import _main_user_keyboard
        message.reply_text(
            "✅ Tekshiruv yakunlandi.",
            reply_markup=_main_user_keyboard()
        )

    return ConversationHandler.END


def cancel(update: Update, context: CallbackContext):
    user = update.effective_user
    if user:
        clear_checker_mode(user.id)

    context.user_data.clear()

    from features.ielts_checkup_ui import _ielts_skills_reply_keyboard
    update.message.reply_text(
        "❌ Tekshiruv bekor qilindi.",
        reply_markup=_ielts_skills_reply_keyboard()
    )
    return ConversationHandler.END


# ---------- Registration ----------

def register(dispatcher):
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("check_listening", start_check),
            MessageHandler(Filters.regex("^🎧 Listening$"), start_check),
        ],
        states={
            WAITING_FOR_AUDIO: [
                MessageHandler(
                    Filters.voice | Filters.audio | Filters.video | Filters.document,
                    receive_audio
                )
            ],
            WAITING_FOR_QUESTIONS: [
                MessageHandler(Filters.photo, receive_questions)
            ],
            WAITING_FOR_ANSWERS: [
                MessageHandler(
                    (Filters.text & ~Filters.command) | Filters.photo,
                    receive_answers
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=False,
    )

    dispatcher.add_handler(conv, group=2)


def setup(dispatcher):
    register(dispatcher)
