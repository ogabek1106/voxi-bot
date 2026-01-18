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
    ReplyKeyboardMarkup,
)
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
- If the audio or question is unclear, DO NOT invent explanations.
  Instead, say clearly that the reason cannot be determined.
- This is NOT an official IELTS score.

IELTS Listening rules:
- Spelling matters (very important).
- Singular / plural matters.
- Word limits matter.
- Articles are usually ignored unless meaning changes.
- Numbers must be correct.
- Accept only reasonable variants IELTS would accept.

LANGUAGE & QUALITY RULES (CRITICAL):
- Use ONLY correct, standard Uzbek (Latin).
- Spelling mistakes in Uzbek are NOT acceptable.
- Do NOT use mixed, awkward, or literal translations.
- Sentences MUST be logically connected and meaningful.
- Prefer simple, natural Uzbek over complex phrases.
- NEVER invent explanations.
- NEVER give advice related to Speaking or Writing.
- LISTENING feedback only.

ERROR REPORTING RULE (VERY IMPORTANT):
- ONLY mention answers that are WRONG or PROBLEMATIC.
- NEVER list correct answers.
- NEVER explain why a correct answer is correct.

ANTI-HALLUCINATION RULE:
- Refer ONLY to information that exists in the audio or questions.
- If something cannot be confirmed, say it is unclear.

OUTPUT STRUCTURE RULES (ABSOLUTE — NO EXCEPTIONS):

1) FIRST LINE (MANDATORY):
📊 Taxminiy natija: <band range>

- Must be EXACT.
- Must be the FIRST line.
- Must appear ONCE.

2) REQUIRED SECTIONS (IN THIS ORDER):
- Umumiy fikr
- Xatolar va sabablari
- Imlo yoki shakl
- IELTS listening tuzoqlari
- Amaliy maslahat

3) SECTION TITLE FORMAT (MANDATORY — MARKDOWN REQUIRED):

EVERY section title MUST:
- Be wrapped in DOUBLE ASTERISKS (** **)
- Start with an emoji
- Be on its own line

✅ CORRECT:
**🧠 Umumiy fikr**

❌ INVALID:
🧠 Umumiy fikr  
**Umumiy fikr**  
🧠 **Umumiy fikr**

4) FORMATTING RULES:
- ONLY section titles may be bold.
- Body text MUST NEVER be bold.
- Use short paragraphs.
- No blocky or dry text.

5) EMPTY SECTIONS:
- If nothing meaningful exists, say so briefly.
- DO NOT invent content.

FREE PLAN DEPTH RULES:
- Maximum 2–3 key issues.
- ONE short practical advice only.
- No long explanations.

TONE & STYLE:
- Calm, supportive teacher tone.
- Natural Uzbek.
- Human, not robotic.

FINAL SELF-CHECK (MANDATORY):
Before sending the final answer:
- Verify ALL section titles are bold (** **).
- Verify emojis are present in ALL titles.
- If ANY title is not bolded, REWRITE THE OUTPUT.

IMPORTANT:
- This is an ESTIMATED result.
"""

MAX_TELEGRAM_LEN = 4000


# ---------- Helpers ----------

def _listening_keyboard():
    return ReplyKeyboardMarkup(
        [["➡️ Davom etish", "❌ Cancel"]],
        resize_keyboard=True
    )


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
    context.user_data.update({
        "audios": [],
        "questions": [],
        "answers": [],
        "state": WAITING_FOR_AUDIO,
        "audio_notified": False,
        "questions_notified": False,
        "answers_notified": False,
    })

    update.message.reply_text(
        "🎧 *Listening audio yuboring.*\n"
        "Bir nechta fayl yuborishingiz mumkin.",
        parse_mode="Markdown",
        reply_markup=_listening_keyboard()
    )
    return WAITING_FOR_AUDIO


# ---------- AUDIO COLLECTION ----------

def collect_audio(update: Update, context: CallbackContext):
    if update.message.voice or update.message.audio or update.message.video or update.message.document:
        context.user_data["audios"].append(update.message)

        if not context.user_data["audio_notified"]:
            update.message.reply_text(
                "🎧 *Qabul qilindi.*\n"
                "Agar yana bo‘lsa jo‘nating, tugatgach ➡️ *Davom etish* tugmasini bosing.",
                parse_mode="Markdown"
            )
            context.user_data["audio_notified"] = True

    return WAITING_FOR_AUDIO


# ---------- QUESTIONS COLLECTION ----------

def collect_questions(update: Update, context: CallbackContext):
    if update.message.photo:
        text = _ocr_image_to_text(context.bot, update.message.photo)
        context.user_data["questions"].append(text)

        if not context.user_data["questions_notified"]:
            update.message.reply_text(
                "🖼️ *Qabul qilindi.*\n"
                "Agar yana bo‘lsa jo‘nating, tugatgach ➡️ *Davom etish* tugmasini bosing.",
                parse_mode="Markdown"
            )
            context.user_data["questions_notified"] = True

    return WAITING_FOR_QUESTIONS


# ---------- ANSWERS COLLECTION ----------

def collect_answers(update: Update, context: CallbackContext):
    msg = update.message

    if msg.text:
        context.user_data["answers"].append(msg.text)
    elif msg.photo:
        text = _ocr_image_to_text(context.bot, msg.photo)
        context.user_data["answers"].append(text)

    if not context.user_data["answers_notified"]:
        msg.reply_text(
            "✍️ *Qabul qilindi.*\n"
            "Agar yana bo‘lsa jo‘nating, tugatgach ➡️ *Davom etish* tugmasini bosing.",
            parse_mode="Markdown"
        )
        context.user_data["answers_notified"] = True

    return WAITING_FOR_ANSWERS


# ---------- FLOW CONTROL ----------

def proceed_next(update: Update, context: CallbackContext):
    state = context.user_data.get("state")

    if state == WAITING_FOR_AUDIO:
        if not context.user_data["audios"]:
            update.message.reply_text("⚠️ Avval listening audio yuboring.")
            return WAITING_FOR_AUDIO

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
            audio_file.name = "audio.wav"

            text = openai.Audio.transcribe(
                model="whisper-1",
                file=audio_file
            )["text"]

            transcripts.append(text)

        context.user_data["audio_text"] = "\n".join(transcripts)
        context.user_data["state"] = WAITING_FOR_QUESTIONS

        update.message.reply_text(
            "📸 *Listening savollari rasmlarini yuboring.*",
            parse_mode="Markdown",
            reply_markup=_listening_keyboard()
        )
        return WAITING_FOR_QUESTIONS

    if state == WAITING_FOR_QUESTIONS:
        if not context.user_data["questions"]:
            update.message.reply_text("⚠️ Avval savol rasmlarini yuboring.")
            return WAITING_FOR_QUESTIONS

        context.user_data["state"] = WAITING_FOR_ANSWERS
        update.message.reply_text(
            "✍️ *Javoblaringizni yuboring.*",
            parse_mode="Markdown",
            reply_markup=_listening_keyboard()
        )
        return WAITING_FOR_ANSWERS

    if state == WAITING_FOR_ANSWERS:
        if not context.user_data["answers"]:
            update.message.reply_text("⚠️ Avval javoblaringizni yuboring.")
            return WAITING_FOR_ANSWERS

        return finalize_listening(update, context)


def finalize_listening(update: Update, context: CallbackContext):
    audio_text = context.user_data.get("audio_text", "")
    questions = "\n".join(context.user_data["questions"])
    answers = "\n".join(context.user_data["answers"])

    update.message.reply_text(
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
    _send_long_message(update.message, output)

    send_admin_card(
        context.bot,
        update.effective_user.id,
        "New IELTS Listening feedback",
        output
    )

    log_ai_usage(update.effective_user.id, "listening")
    clear_checker_mode(update.effective_user.id)
    context.user_data.clear()

    from features.ielts_checkup_ui import _main_user_keyboard
    update.message.reply_text(
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
        per_message=False,
        entry_points=[
            CommandHandler("check_listening", start_check),
            MessageHandler(Filters.regex("^🎧 Listening$"), start_check),
        ],
        states={
            WAITING_FOR_AUDIO: [
                MessageHandler(Filters.regex("^➡️ Davom etish$"), proceed_next),
                MessageHandler(
                    Filters.voice | Filters.audio | Filters.video | Filters.document,
                    collect_audio
                ),
            ],
            WAITING_FOR_QUESTIONS: [
                MessageHandler(Filters.regex("^➡️ Davom etish$"), proceed_next),
                MessageHandler(Filters.photo, collect_questions),
            ],
            WAITING_FOR_ANSWERS: [
                MessageHandler(Filters.regex("^➡️ Davom etish$"), proceed_next),
                MessageHandler(
                    (Filters.text & ~Filters.command) | Filters.photo,
                    collect_answers
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=False,
    )

    dispatcher.add_handler(conv, group=2)


def setup(dispatcher):
    register(dispatcher)
