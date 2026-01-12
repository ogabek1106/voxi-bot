# features/ai/check_speaking1.py
"""
/check_speaking1
IELTS Speaking Part 1 AI checker (FREE MODE, command-based)

Flow:
1) User sends /check_speaking1
2) Bot asks for Speaking Part 1 QUESTION (topic)
3) User sends question (TEXT)
4) Bot asks for VOICE answer
5) User sends voice (10 sec – 3 min)
6) Bot evaluates and replies in Uzbek (WRITTEN feedback)
"""

import logging
import os
import io

from telegram import Update
from telegram.ext import (
    CallbackContext,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    Filters,
)
from telegram.ext import DispatcherHandlerStop
from features.admin_feedback import send_admin_card

import openai

from features.ai.check_limits import can_use_feature
from database import log_ai_usage
from database import (
    set_checker_mode,
    clear_checker_mode,
    get_checker_mode,
)

logger = logging.getLogger(__name__)

# ---------- OpenAI (OLD SDK – STABLE) ----------
openai.api_key = os.getenv("OPENAI_API_KEY")

# ---------- States ----------
WAITING_FOR_QUESTION = 0
WAITING_FOR_VOICE = 1

# ---------- Limits ----------
MIN_SECONDS = 10
MAX_SECONDS = 180  # 3 minutes
RECOMMENDED = "15–30 soniya"

# ---------- Prompt ----------
SYSTEM_PROMPT = """
You are an IELTS Speaking Part 1 evaluator.

You will be given:
1) The Speaking Part 1 QUESTION
2) The student's SPOKEN ANSWER (transcribed)

Your task:
- Evaluate STRICTLY as IELTS Speaking Part 1.
- Follow ONLY public IELTS band descriptors.
- Do NOT act as an examiner.
- Do NOT ask questions.
- This is NOT an official score.

Assessment focus:
- Fluency and Coherence
- Lexical Resource (basic)
- Grammatical Accuracy
- Pronunciation (clarity, stress, sounds)

Language rules:
- ALL feedback must be in Uzbek.
- English allowed ONLY to quote incorrect phrases and corrections.

IMPORTANT OUTPUT RULES:
- Use EXACTLY the following structure.
- DO NOT add or remove sections.
- Keep feedback concise (FREE MODE).

OUTPUT TEMPLATE (USE VERBATIM):

📊 *Taxminiy band (range):*
<content>

🌟 *Yaxshi tomonlar:*
<content>

❗ *Asosiy muammolar:*
<content>

🛠 *Yaxshilash bo‘yicha maslahat:*
<content>

Tone:
- Calm
- Teacher-like
- Honest
"""

# ---------- Handlers ----------

def start_check(update: Update, context: CallbackContext):
    from features.sub_check import require_subscription
    if not require_subscription(update, context):
        return ConversationHandler.END

    user = update.effective_user
    if not user:
        return ConversationHandler.END

    limit_result = can_use_feature(user.id, "speaking")
    if not limit_result["allowed"]:
        from features.ielts_checkup_ui import _main_user_keyboard
        update.message.reply_text(
            limit_result["message"],
            parse_mode="Markdown",
            reply_markup=_main_user_keyboard()
        )
        raise DispatcherHandlerStop

    set_checker_mode(user.id, "speaking_part1")
    context.user_data.pop("speaking_p1_question", None)

    from features.ielts_checkup_ui import _checker_cancel_keyboard
    update.message.reply_text(
        "🎤 *IELTS Speaking Part 1 savolini yuboring.*\n\n"
        "Masalan:\n"
        "_Where do you live?_\n"
        "_Do you like your job?_",
        parse_mode="Markdown",
        reply_markup=_checker_cancel_keyboard()
    )
    # 🔥 THIS IS THE KEY (same as Writing)
    raise DispatcherHandlerStop


def receive_question(update: Update, context: CallbackContext):
    message = update.message
    user = update.effective_user

    if not message or not user:
        return WAITING_FOR_QUESTION

    if get_checker_mode(user.id) != "speaking_part1":
        return ConversationHandler.END

    if not message.text or len(message.text.strip()) < 5:
        message.reply_text("❗️Iltimos, aniq speaking savolini yuboring.")
        return WAITING_FOR_QUESTION

    context.user_data["speaking_p1_question"] = message.text.strip()

    message.reply_text(
        "✅ *Savol qabul qilindi.*\n\n"
        "🎙 Endi ovozli javob yuboring.\n\n"
        f"📌 Tavsiya etiladi: {RECOMMENDED}\n"
        "⛔️ Juda uzun javob bahoni pasaytiradi.",
        parse_mode="Markdown"
    )
    return WAITING_FOR_VOICE


def receive_voice(update: Update, context: CallbackContext):
    message = update.message
    user = update.effective_user

    if not message or not user or not message.voice:
        message.reply_text("❗️Iltimos, ovozli xabar yuboring.")
        return WAITING_FOR_VOICE

    if get_checker_mode(user.id) != "speaking_part1":
        return ConversationHandler.END

    duration = message.voice.duration

    if duration < MIN_SECONDS:
        message.reply_text(
            "❗️Javob juda qisqa.\n"
            "IELTS baholash uchun kamida 10 soniya kerak."
        )
        return WAITING_FOR_VOICE

    if duration > MAX_SECONDS:
        message.reply_text(
            "❗️Javob juda uzun.\n"
            "Speaking Part 1 uchun bu noto‘g‘ri."
        )

    question = context.user_data.get("speaking_p1_question")
    if not question:
        message.reply_text("❗️Avval savolni yuboring.")
        return WAITING_FOR_QUESTION

    message.reply_text(
        "*⏳ Ovozli javob tahlil qilinmoqda...*",
        parse_mode="Markdown"
    )

    try:
        # 1️⃣ Download Telegram voice
        tg_file = context.bot.get_file(message.voice.file_id)
        audio_bytes = tg_file.download_as_bytearray()

        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "speech.ogg"

        # 2️⃣ TRANSCRIBE WITH WHISPER (OLD SDK – CORRECT)
        transcription_result = openai.Audio.transcribe(
            model="whisper-1",
            file=audio_file
        )
        transcription = transcription_result["text"]

        # 3️⃣ IELTS Speaking evaluation (OLD SDK – CORRECT)
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Speaking Part 1 Question:\n{question}\n\n"
                        f"Student Answer (transcribed):\n{transcription}"
                    ),
                },
            ],
            max_tokens=500,
        )

        output_text = response["choices"][0]["message"]["content"].strip()
        message.reply_text(output_text, parse_mode="Markdown")
        send_admin_card(
            context.bot,
            user.id,
            "New IELTS feedback processed",
            output_text
        )       
        log_ai_usage(user.id, "speaking")

    except Exception:
        logger.exception("check_speaking1 AI error")
        message.reply_text("❌ Xatolik yuz berdi. Keyinroq urinib ko‘ring.")

    finally:
        clear_checker_mode(user.id)
        context.user_data.pop("speaking_p1_question", None)

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

    context.user_data.pop("speaking_p1_question", None)

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
            CommandHandler("check_speaking1", start_check),
            MessageHandler(Filters.regex("^🗣️ Part 1 – Introduction$"), start_check),
        ],
        states={
            WAITING_FOR_QUESTION: [
                MessageHandler(Filters.text & ~Filters.command, receive_question)
            ],
            WAITING_FOR_VOICE: [
                MessageHandler(Filters.voice, receive_voice)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=False,
    )

    dispatcher.add_handler(conv, group=2)


def setup(dispatcher):
    register(dispatcher)
