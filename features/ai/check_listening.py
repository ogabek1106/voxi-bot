# features/ai/check_listening.py
"""
/check_listening
IELTS Listening AI checker (FREE MODE, command-based)

Desired Flow (BUTTON-GATED):
1) User sends /check_listening
2) User sends LISTENING AUDIOS (multiple allowed)
3) User presses "Davom etish"
4) User sends QUESTION IMAGES (multiple allowed)
5) User presses "Davom etish"
6) User sends ANSWERS (text or image, multiple allowed)
7) User presses "Davom etish"
8) Bot evaluates and replies in Uzbek
"""

import logging
import os
import io
import base64

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    CallbackContext,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
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


def _continue_keyboard(cb):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➡️ Davom etish", callback_data=cb)]
    ])


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
    context.user_data["audios"] = []
    context.user_data["questions"] = []
    context.user_data["answers"] = []
    context.user_data["audio_notified"] = False

    update.message.reply_text(
        "🎧 *Listening audio yuboring.*\n"
        "Bir nechta fayl yuborishingiz mumkin.\n\n"
        "Tugatgach tugmani bosing 👇",
        parse_mode="Markdown",
        reply_markup=_continue_keyboard("audio_done")
    )
    return WAITING_FOR_AUDIO


# ---------- AUDIO COLLECTION ----------

def collect_audio(update: Update, context: CallbackContext):
    if update.message.voice or update.message.audio or update.message.video or update.message.document:
        context.user_data["audios"].append(update.message)

        if not context.user_data.get("audio_notified"):
            update.message.reply_text("🎧 Audio fayllar qabul qilinmoqda...")
            context.user_data["audio_notified"] = True

    return WAITING_FOR_AUDIO


def audio_done(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    transcripts = []

    for msg in context.user_data["audios"]:
        tg_file = context.bot.get_file(
            msg.voice.file_id if msg.voice else
            msg.audio.file_id if msg.audio else
            msg.video.file_id if msg.video else
            msg.document.file_id
        )

        audio_bytes = tg_file.download_as_bytearray()
        audio_file = io.BytesIO(audio_bytes)

        if msg.voice:
            audio_file.name = "audio.ogg"
        elif msg.audio and msg.audio.file_name:
            audio_file.name = msg.audio.file_name
        elif msg.video:
            audio_file.name = "audio.mp4"
        elif msg.document and msg.document.file_name:
            audio_file.name = msg.document.file_name
        else:
            audio_file.name = "audio.wav"

        text = openai.Audio.transcribe(
            model="whisper-1",
            file=audio_file
        )["text"]

        transcripts.append(text)

    context.user_data["audio_text"] = "\n".join(transcripts)

    query.message.reply_text(
        "📸 *Endi Listening savollari rasmlarini yuboring.*\n"
        "Bir nechta rasm bo‘lishi mumkin.\n\n"
        "Tugatgach tugmani bosing 👇",
        parse_mode="Markdown",
        reply_markup=_continue_keyboard("questions_done")
    )
    return WAITING_FOR_QUESTIONS


# ---------- QUESTIONS COLLECTION ----------

def collect_questions(update: Update, context: CallbackContext):
    if update.message.photo:
        text = _ocr_image_to_text(context.bot, update.message.photo)
        context.user_data["questions"].append(text)
        update.message.reply_text("🖼️ Savol rasmi qabul qilindi.")
    return WAITING_FOR_QUESTIONS


def questions_done(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    query.message.reply_text(
        "✍️ *Endi javoblaringizni yuboring.*\n"
        "Matn yoki rasm bo‘lishi mumkin.\n\n"
        "Tugatgach tugmani bosing 👇",
        parse_mode="Markdown",
        reply_markup=_continue_keyboard("answers_done")
    )
    return WAITING_FOR_ANSWERS


# ---------- ANSWERS COLLECTION ----------

def collect_answers(update: Update, context: CallbackContext):
    msg = update.message
    if msg.text:
        context.user_data["answers"].append(msg.text)
    elif msg.photo:
        text = _ocr_image_to_text(context.bot, msg.photo)
        context.user_data["answers"].append(text)

    msg.reply_text("✍️ Javob qabul qilindi.")
    return WAITING_FOR_ANSWERS


def answers_done(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    audio_text = context.user_data.get("audio_text", "")
    questions = "\n".join(context.user_data.get("questions", []))
    answers = "\n".join(context.user_data.get("answers", []))

    query.message.reply_text(
        "*⏳ Listening tahlil qilinmoqda...*",
        parse_mode="Markdown"
    )

    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Listening Audio Transcript:\n{audio_text}\n\n"
                    f"Listening Questions:\n{questions}\n\n"
                    f"Student Answers:\n{answers}"
                ),
            },
        ],
        max_tokens=700,
    )

    output = response["choices"][0]["message"]["content"].strip()
    _send_long_message(query.message, output)

    send_admin_card(
        context.bot,
        query.from_user.id,
        "New IELTS Listening feedback",
        output
    )

    log_ai_usage(query.from_user.id, "listening")

    clear_checker_mode(query.from_user.id)
    context.user_data.clear()

    from features.ielts_checkup_ui import _main_user_keyboard
    query.message.reply_text(
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
        per_message=True,
        entry_points=[
            CommandHandler("check_listening", start_check),
            MessageHandler(Filters.regex("^🎧 Listening$"), start_check),
        ],
        states={
            WAITING_FOR_AUDIO: [
                MessageHandler(
                    Filters.voice | Filters.audio | Filters.video | Filters.document,
                    collect_audio
                ),
                CallbackQueryHandler(audio_done, pattern="^audio_done$")
            ],
            WAITING_FOR_QUESTIONS: [
                MessageHandler(Filters.photo, collect_questions),
                CallbackQueryHandler(questions_done, pattern="^questions_done$")
            ],
            WAITING_FOR_ANSWERS: [
                MessageHandler(
                    (Filters.text & ~Filters.command) | Filters.photo,
                    collect_answers
                ),
                CallbackQueryHandler(answers_done, pattern="^answers_done$")
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=False,
    )

    dispatcher.add_handler(conv, group=2)


def setup(dispatcher):
    register(dispatcher)
