# features/ai/check_speaking2.py
"""
/check_speaking2
IELTS Speaking Part 2 AI checker (FREE MODE, command-based)

Flow:
1) User sends /check_speaking2
2) Bot asks for Speaking Part 2 CUE CARD (text / image / voice)
3) User sends cue card
4) Bot asks for VOICE answer
5) User sends voice (30 sec – 2.5 min)
6) Bot evaluates and replies in Uzbek (WRITTEN feedback)
"""

import logging
import os
import io
import base64
from global_checker import allow
from global_cleaner import clean_user
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
from features.ai.check_limits import can_use_feature

from database import (
    log_ai_usage,
    set_checker_mode,
    get_checker_mode,
)

import openai

logger = logging.getLogger(__name__)

# ---------- OpenAI (OLD SDK – STABLE) ----------
openai.api_key = os.getenv("OPENAI_API_KEY")

# ---------- States ----------
WAITING_FOR_CUE_CARD = 0
WAITING_FOR_VOICE = 1

# ---------- Limits ----------
MIN_SECONDS = 30
MAX_SECONDS = 150  # 2.5 minutes
RECOMMENDED = "1–2 daqiqa"

# ---------- SYSTEM PROMPT ----------
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

# ---------- Handlers ----------

def start_check(update: Update, context: CallbackContext):
    from features.sub_check import require_subscription
    if not require_subscription(update, context):
        return ConversationHandler.END

    user = update.effective_user
    if not user:
        return ConversationHandler.END

    if not allow(user.id, mode="ielts_check_up"):
        raise DispatcherHandlerStop

    limit_result = can_use_feature(user.id, "speaking")
    if not limit_result["allowed"]:
        from features.ielts_checkup_ui import _main_user_keyboard
        update.message.reply_text(
            limit_result["message"],
            parse_mode="Markdown",
            reply_markup=_main_user_keyboard()
        )
        return ConversationHandler.END

    set_checker_mode(user.id, "speaking_part2")
    context.user_data.pop("speaking_p2_cue_card", None)

    from features.ielts_checkup_ui import _checker_cancel_keyboard
    update.message.reply_text(
        "📝 *IELTS Speaking Part 2 cue cardni yuboring.*\n\n"
        "Qabul qilinadi:\n"
        "• Matn\n"
        "• Rasm\n"
        "• Ovoz\n",
        parse_mode="Markdown",
        reply_markup=_checker_cancel_keyboard()
    )
    return WAITING_FOR_CUE_CARD


def receive_cue_card(update: Update, context: CallbackContext):
    message = update.message
    user = update.effective_user

    if not allow(user.id, mode="speaking_part2"):
        return ConversationHandler.END

    if not message or not user:
        return WAITING_FOR_CUE_CARD

    if get_checker_mode(user.id) != "speaking_part2":
        return ConversationHandler.END

    cue_text = None

    # ---------- TEXT ----------
    if message.text:
        if len(message.text.strip()) < 20:
            message.reply_text("❗️Cue card juda qisqa. To‘liq matn yuboring.")
            return WAITING_FOR_CUE_CARD
        cue_text = message.text.strip()

    # ---------- VOICE ----------
    elif message.voice:
        tg_file = context.bot.get_file(message.voice.file_id)
        audio_bytes = tg_file.download_as_bytearray()

        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "cue_card.ogg"

        transcription = openai.Audio.transcribe(
            model="whisper-1",
            file=audio_file
        )["text"]

        cue_text = transcription.strip()

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
                        {"type": "text", "text": "Extract the IELTS Speaking Part 2 cue card text from this image."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}"
                            }
                        }
                    ],
                }
            ],
            max_tokens=300,
        )

        cue_text = vision_response["choices"][0]["message"]["content"].strip()

    else:
        message.reply_text("❗️Cue card yuborilmadi.")
        return WAITING_FOR_CUE_CARD

    context.user_data["speaking_p2_cue_card"] = cue_text

    message.reply_text(
        "✅ *Cue card qabul qilindi.*\n\n"
        "🎙 Endi *FAqat ovozli javob* yuboring.\n"
        f"📌 Tavsiya: {RECOMMENDED}",
        parse_mode="Markdown"
    )
    return WAITING_FOR_VOICE


def receive_voice(update: Update, context: CallbackContext):
    message = update.message
    user = update.effective_user

    if not allow(user.id, mode="speaking_part2"):
        return ConversationHandler.END
    
    if not message or not user or not message.voice:
        message.reply_text("❗️Javob FAqat ovozli bo‘lishi kerak.")
        return WAITING_FOR_VOICE

    if get_checker_mode(user.id) != "speaking_part2":
        return ConversationHandler.END

    duration = message.voice.duration

    if duration < MIN_SECONDS:
        message.reply_text("❗️Javob juda qisqa (kamida 30 soniya).")
        return WAITING_FOR_VOICE

    if duration > MAX_SECONDS:
        message.reply_text("⚠️ Javob juda uzun, ammo tekshiriladi.")

    cue_card = context.user_data.get("speaking_p2_cue_card")
    if not cue_card:
        message.reply_text("❗️Avval cue cardni yuboring.")
        return WAITING_FOR_CUE_CARD

    message.reply_text("*⏳ Ovozli javob tahlil qilinmoqda...*", parse_mode="Markdown")

    try:
        tg_file = context.bot.get_file(message.voice.file_id)
        audio_bytes = tg_file.download_as_bytearray()

        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "speech.ogg"

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
                        f"Speaking Part 2 Cue Card:\n{cue_card}\n\n"
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
            "New IELTS Speaking Part 2 feedback",
            output
        )

        log_ai_usage(user.id, "speaking")

    except Exception:
        logger.exception("check_speaking2 AI error")
        message.reply_text("❌ Xatolik yuz berdi. Keyinroq urinib ko‘ring.")

    finally:
        clean_user(user.id, reason="speaking_part2 finished")
        context.user_data.pop("speaking_p2_cue_card", None)

        from features.ielts_checkup_ui import _main_user_keyboard
        message.reply_text(
            "✅ Tekshiruv yakunlandi.",
            reply_markup=_main_user_keyboard()
        )

    return ConversationHandler.END


def cancel(update: Update, context: CallbackContext):
    user = update.effective_user
    if user:
        clean_user(user.id, reason="speaking_part2 cancel")

    context.user_data.pop("speaking_p2_cue_card", None)

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
            CommandHandler("check_speaking2", start_check),
            MessageHandler(Filters.regex("^🗣️ Part 2 – Cue Card$"), start_check),
        ],
        states={
            WAITING_FOR_CUE_CARD: [
                MessageHandler(
                    Filters.text | Filters.photo | Filters.voice,
                    receive_cue_card
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
