# features/ai/check_speaking3.py
"""
/check_speaking3
IELTS Speaking Part 3 AI checker (FREE MODE, command-based)

Flow:
1) User sends /check_speaking3
2) Bot asks for Speaking Part 3 QUESTION (text / image / voice)
3) User sends question
4) Bot asks for VOICE answer
5) User sends voice (20 sec – 2 min)
6) Bot evaluates and replies in Uzbek (WRITTEN feedback)
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

from features.admin_feedback import send_admin_card
from features.ai.check_limits import can_use_feature

from database import (
    log_ai_usage,
    set_checker_mode,
    clear_checker_mode,
    get_checker_mode,
)

import openai

logger = logging.getLogger(__name__)

# ---------- OpenAI (OLD SDK – STABLE) ----------
openai.api_key = os.getenv("OPENAI_API_KEY")

# ---------- States ----------
WAITING_FOR_QUESTION = 0
WAITING_FOR_VOICE = 1

# ---------- Limits ----------
MIN_SECONDS = 20
MAX_SECONDS = 120
RECOMMENDED = "30–60 soniya"

# ---------- SYSTEM PROMPT ----------
SYSTEM_PROMPT = """
You are an IELTS Speaking Part 3 teacher giving precise, warm, and supportive feedback directly to the student.

You will be given:
1) The full set of IELTS Speaking Part 3 QUESTIONS (may include several discussion topics)
2) The student's SPOKEN ANSWER (transcribed)

Your task:
- Carefully read ALL the questions — even if there are multiple topics (e.g. “School rules” and “Working in the legal profession”).
- For EACH question, check if the student answered it or not:
    • If answered → give short, natural feedback (1–2 sentences) in Uzbek.
    • If NOT answered → write: “Siz bu savolga javob bermadingiz.”
- Never skip or merge questions, even if the student didn’t mention the topic.
- Start each feedback line with the question number (e.g. “- 1-savol: ...”).
- Do NOT repeat the question number again inside the sentence (no doubling like “1-savolda...”).
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
- Use short, clear, and friendly teacher-like sentences.
- Avoid robotic or examiner-style phrasing.

STRICT FORMAT RULES:
- Use EXACTLY the structure below.
- In the band section, write ONLY a numeric range (e.g. “6.0–6.5”).
- In “Savollar bo‘yicha kuzatuvlar”, give feedback for EVERY question in the uploaded text/image, including unanswered ones.
- For unanswered questions, write: “Siz bu savolga javob bermadingiz.”
- Do NOT repeat question numbers inside sentences.

OUTPUT TEMPLATE (USE VERBATIM):

📊 *Taxminiy band (range):*
<number range only, e.g. 6.0–6.5>

🌟 *Yaxshi tomonlar:*
<2–4 short sentences describing overall strengths>

❗ *Savollar bo‘yicha kuzatuvlar:*
- 1-savol: <feedback or “Siz bu savolga javob bermadingiz.”>
- 2-savol: <feedback or “Siz bu savolga javob bermadingiz.”>
- 3-savol: <feedback or “Siz bu savolga javob bermadingiz.”>
- 4-savol: <feedback or “Siz bu savolga javob bermadingiz.”>
- 5-savol: <feedback or “Siz bu savolga javob bermadingiz.”>
- 6-savol: <feedback or “Siz bu savolga javob bermadingiz.”>
(Add more automatically if the question set has more.)

🛠 *Yaxshilash bo‘yicha maslahat:*
<1–2 short practical suggestions + motivational sentence>

Tone:
- Warm, respectful, and natural (teacher → student)
- Always use “siz”
- Each sentence must be short, precise, and clear.
- End with light encouragement (e.g. “Shunday davom eting!”, “Sizda yaxshi potentsial bor.”)
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
        return ConversationHandler.END

    set_checker_mode(user.id, "speaking_part3")
    context.user_data.pop("speaking_p3_question", None)

    from features.ielts_checkup_ui import _checker_cancel_keyboard
    update.message.reply_text(
        "🧠 *IELTS Speaking Part 3 savolini yuboring.*\n\n"
        "Qabul qilinadi:\n"
        "• Matn\n"
        "• Rasm\n"
        "• Ovoz",
        parse_mode="Markdown",
        reply_markup=_checker_cancel_keyboard()
    )
    return WAITING_FOR_QUESTION


def receive_question(update: Update, context: CallbackContext):
    message = update.message
    user = update.effective_user

    if not message or not user:
        return WAITING_FOR_QUESTION

    if get_checker_mode(user.id) != "speaking_part3":
        return ConversationHandler.END

    question_text = None

    # ---------- TEXT ----------
    if message.text:
        if len(message.text.strip()) < 10:
            message.reply_text("❗️Savol juda qisqa. To‘liq savol yuboring.")
            return WAITING_FOR_QUESTION
        question_text = message.text.strip()

    # ---------- VOICE ----------
    elif message.voice:
        tg_file = context.bot.get_file(message.voice.file_id)
        audio_bytes = tg_file.download_as_bytearray()

        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "question.ogg"

        transcription = openai.Audio.transcribe(
            model="whisper-1",
            file=audio_file
        )["text"]

        question_text = transcription.strip()

    # ---------- IMAGE ----------
    elif message.photo:
        photo = message.photo[-1]
        tg_file = context.bot.get_file(photo.file_id)
        image_bytes = tg_file.download_as_bytearray()

        image_b64 = base64.b64encode(image_bytes).decode()

        vision_response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract the IELTS Speaking Part 3 question from this image."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}"
                            }
                        }
                    ],
                }
            ],
            max_tokens=200,
        )

        question_text = vision_response["choices"][0]["message"]["content"].strip()

    else:
        message.reply_text("❗️Savol aniqlanmadi.")
        return WAITING_FOR_QUESTION

    context.user_data["speaking_p3_question"] = question_text

    message.reply_text(
        "✅ *Savol qabul qilindi.*\n\n"
        "🎙 Endi *FAqat ovozli javob* yuboring.\n"
        f"📌 Tavsiya: {RECOMMENDED}",
        parse_mode="Markdown"
    )
    return WAITING_FOR_VOICE


def receive_voice(update: Update, context: CallbackContext):
    message = update.message
    user = update.effective_user

    if not message or not user or not message.voice:
        message.reply_text("❗️Javob FAqat ovozli bo‘lishi kerak.")
        return WAITING_FOR_VOICE

    if get_checker_mode(user.id) != "speaking_part3":
        return ConversationHandler.END

    duration = message.voice.duration

    if duration < MIN_SECONDS:
        message.reply_text("❗️Javob juda qisqa (kamida 20 soniya).")
        return WAITING_FOR_VOICE

    if duration > MAX_SECONDS:
        message.reply_text("⚠️ Javob juda uzun, ammo tekshiriladi.")

    question = context.user_data.get("speaking_p3_question")
    if not question:
        message.reply_text("❗️Avval savolni yuboring.")
        return WAITING_FOR_QUESTION

    message.reply_text("*⏳ Ovozli javob tahlil qilinmoqda...*", parse_mode="Markdown")

    try:
        tg_file = context.bot.get_file(message.voice.file_id)
        audio_bytes = tg_file.download_as_bytearray()

        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "answer.ogg"

        transcription = openai.Audio.transcribe(
            model="whisper-1",
            file=audio_file
        )["text"]

        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Speaking Part 3 Question:\n{question}\n\n"
                        f"Student Answer (transcribed):\n{transcription}"
                    ),
                },
            ],
            max_tokens=600,
        )

        output = response["choices"][0]["message"]["content"].strip()
        message.reply_text(output, parse_mode="Markdown")

        send_admin_card(
            context.bot,
            user.id,
            "New IELTS Speaking Part 3 feedback",
            output
        )

        log_ai_usage(user.id, "speaking")

    except Exception:
        logger.exception("check_speaking3 AI error")
        message.reply_text("❌ Xatolik yuz berdi. Keyinroq urinib ko‘ring.")

    finally:
        clear_checker_mode(user.id)
        context.user_data.pop("speaking_p3_question", None)

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

    context.user_data.pop("speaking_p3_question", None)

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
            CommandHandler("check_speaking3", start_check),
            MessageHandler(Filters.regex("^🗣️ Part 3 – Discussion$"), start_check),
        ],
        states={
            WAITING_FOR_QUESTION: [
                MessageHandler(
                    Filters.text | Filters.photo | Filters.voice,
                    receive_question
                )
            ],
            WAITING_FOR_VOICE: [
                MessageHandler(Filters.voice, receive_voice)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    dispatcher.add_handler(conv, group=2)


def setup(dispatcher):
    register(dispatcher)
