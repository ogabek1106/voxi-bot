# features/ai/check_reading.py
"""
/check_reading
IELTS Reading AI checker (FREE MODE, command-based)

Flow (BUTTON-GATED, LIKE LISTENING):
1) User sends /check_reading
2) User sends PASSAGE + QUESTIONS (text or image, multiple allowed)
3) User presses "Davom etish"
4) User sends ANSWERS (text or image, multiple allowed)
5) User presses "Davom etish"
6) Bot evaluates and replies in Uzbek
"""

import logging
import os
import base64
import json
import re
from global_checker import allow
from global_cleaner import clean_user
from database import clear_checker_mode

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
from features.ielts_checkup_ui import _ielts_skills_reply_keyboard
from features.ai.check_limits import can_use_feature
from features.admin_feedback import send_admin_card
from database import (
    get_checker_mode,
    log_ai_usage,
    set_checker_mode,
)

logger = logging.getLogger(__name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

# ---------- States ----------
WAITING_FOR_PASSAGE = 0
WAITING_FOR_ANSWERS = 1

# ---------- SYSTEM PROMPT ----------
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

MAX_TELEGRAM_LEN = 4000


# ---------- Helpers ----------

def _should_confirm_album(msg, context, key):
    album_id = msg.media_group_id
    if not album_id:
        return True

    confirmed = context.user_data.setdefault(key, set())
    if album_id in confirmed:
        return False

    confirmed.add(album_id)
    return True


def _reading_keyboard():
    return ReplyKeyboardMarkup(
        [["➡️ Davom etish", "❌ Cancel"]],
        resize_keyboard=True
    )


def _send_long_message(message, text: str):
    if not text:
        return

    bot = message.bot
    chat_id = message.chat_id

    for i in range(0, len(text), MAX_TELEGRAM_LEN):
        bot.send_message(
            chat_id=chat_id,
            text=text[i:i + MAX_TELEGRAM_LEN],
            parse_mode="HTML"
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
            max_tokens=900,
        )

        return response["choices"][0]["message"]["content"].strip()

    except Exception:
        logger.exception("OCR failed")
        return ""


def _split_passage_and_questions(text: str):
    lines = text.splitlines()
    passage = []
    questions = []
    found_questions = False

    q_pattern = re.compile(
        r"^\s*(\d+[\.\)]|\bTRUE\b|\bFALSE\b|\bNOT GIVEN\b|A\.|B\.|C\.|D\.|_{3,})",
        re.IGNORECASE
    )

    for line in lines:
        if not found_questions and q_pattern.search(line):
            found_questions = True

        if found_questions:
            questions.append(line)
        else:
            passage.append(line)

    return "\n".join(passage).strip(), "\n".join(questions).strip()


def _normalize_answers(text: str) -> str:
    text = text.upper()
    text = re.sub(r"\bN\s*G\b", "NOT GIVEN", text)
    text = re.sub(r"\bNOTGIVEN\b", "NOT GIVEN", text)
    text = re.sub(r"\bT\b", "TRUE", text)
    text = re.sub(r"\bF\b", "FALSE", text)
    return text


def _format_reading_feedback(data: dict) -> str:
    band = data.get("apr_band", "—")
    raw = data.get("raw_score", "—")

    return (
        f"<b>📊 Taxminiy natija:</b> {band} ({raw}/40)\n\n"
        f"<b>🧠 Umumiy fikr</b>\n"
        f"{data.get('overall', '—')}\n\n"
        f"<b>❌ Xatolar</b>\n"
        f"{data.get('mistakes', '—')}\n\n"
        f"<b>🎯 Amaliy maslahat</b>\n"
        f"{data.get('advice', '—')}"
    )


# ---------- Handlers ----------

def start_check(update: Update, context: CallbackContext):
    from features.sub_check import require_subscription
    if not require_subscription(update, context):
        return ConversationHandler.END

    user = update.effective_user
    if not user:
        return ConversationHandler.END

    if not allow(user.id, mode="ielts_check_up"):
        return False

    limit = can_use_feature(user.id, "reading")
    if not limit["allowed"]:
        from features.ielts_checkup_ui import _main_user_keyboard
        update.message.reply_text(
            limit["message"],
            parse_mode="Markdown",
            reply_markup=_main_user_keyboard()
        )
        return ConversationHandler.END

    set_checker_mode(user.id, "reading")

    update.message.reply_text(
        "ℹ️ *Eslatma:*\n"
        "Reading mantiqiy o‘ylashni talab qiladi.\n"
        "AI ayrim savollarda *adashishi mumkin*.\n"
        "To‘g‘rilik darajasi taxminan *80%*.\n"
        "Natijalar rasmiy IELTS bahosi emas.",
        parse_mode="Markdown"
    )
    
    context.user_data.clear()
    context.user_data.update({
        "texts": [],
        "answers": [],
    })

    update.message.reply_text(
        "📘 *Reading matni va savollarni yuboring.*\n"
        "Matn yoki rasm bo‘lishi mumkin.",
        parse_mode="Markdown",
        reply_markup=_reading_keyboard()
    )

    return WAITING_FOR_PASSAGE


def collect_passage(update: Update, context: CallbackContext):
    user = update.effective_user

    if not allow(user.id, mode="ielts_check_up"):
        return False

    if get_checker_mode(user.id) != "reading":
        return False
    
    msg = update.message

    # ---- STORE CONTENT ----
    if msg.text:
        context.user_data["texts"].append(msg.text)

    elif msg.photo:
        text = _ocr_image_to_text(context.bot, msg.photo)
        if text.strip():
            context.user_data["texts"].append(text)

    # ---- CONFIRM ONLY ONCE PER ALBUM ----
    if _should_confirm_album(msg, context, "confirmed_passage_albums"):
        msg.reply_text(
            "📄 *Qabul qilindi.*\n"
            "Agar yana bo‘lsa yuboring, tugatgach ➡️ *Davom etish* ni bosing.",
            parse_mode="Markdown"
        )

    return WAITING_FOR_PASSAGE

def collect_answers(update: Update, context: CallbackContext):
    user = update.effective_user
    
    if not allow(user.id, mode="ielts_check_up"):
        return False

    if get_checker_mode(user.id) != "reading":
        return False
    
    msg = update.message

    msg.reply_text(
        "✍️ *Qabul qilindi.*\n"
        "Agar yana bo‘lsa yuboring, tugatgach ➡️ *Davom etish* ni bosing.",
        parse_mode="Markdown"
    )

    if msg.text:
        context.user_data["answers"].append(msg.text)

    elif msg.photo:
        text = _ocr_image_to_text(context.bot, msg.photo)
        if text.strip():
            context.user_data["answers"].append(text)

    return WAITING_FOR_ANSWERS


def proceed_next(update: Update, context: CallbackContext):
    user = update.effective_user

    if not allow(user.id, mode="ielts_check_up"):
        return False

    if get_checker_mode(user.id) != "reading":
        return False

    # ---------- STEP 1: PASSAGE + QUESTIONS ----------
    if not context.user_data.get("passage"):
        if not context.user_data.get("texts"):
            update.message.reply_text(
                "⚠️ *Reading matni yoki savollar yuborilmadi.*\n"
                "Iltimos, avval matn yoki rasmlarni yuboring.",
                parse_mode="Markdown"
            )
            return WAITING_FOR_PASSAGE

        full_text = "\n".join(context.user_data["texts"])
        passage, questions = _split_passage_and_questions(full_text)

        if not questions.strip():
            update.message.reply_text(
                "⚠️ *Savollar aniqlanmadi.*\n"
                "Iltimos, savollar aniq ko‘rinadigan rasm yoki matn yuboring.",
                parse_mode="Markdown"
            )
            return WAITING_FOR_PASSAGE

        context.user_data["passage"] = passage
        context.user_data["questions"] = questions

        update.message.reply_text(
            "✍️ *Javoblaringizni yuboring.*",
            parse_mode="Markdown",
            reply_markup=_reading_keyboard()
        )
        return WAITING_FOR_ANSWERS

    # ---------- STEP 2: ANSWERS ----------
    if not context.user_data.get("answers"):
        update.message.reply_text(
            "⚠️ *Javoblar yuborilmadi.*\n"
            "Iltimos, javoblaringizni yuboring.",
            parse_mode="Markdown"
        )
        return WAITING_FOR_ANSWERS

    return finalize_reading(update, context)



def finalize_reading(update: Update, context: CallbackContext):

    if not allow(update.effective_user.id, mode="ielts_check_up"):
        return False

    if get_checker_mode(update.effective_user.id) != "reading":
        return False
    
    passage = context.user_data.get("passage", "")
    questions = context.user_data.get("questions", "")
    answers_raw = "\n".join(context.user_data.get("answers", ""))
    answers = _normalize_answers(answers_raw)

    update.message.reply_text(
        "*⏳ Reading tahlil qilinmoqda...*",
        parse_mode="Markdown"
    )

    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"PASSAGE:\n{passage}\n\n"
                    f"QUESTIONS:\n{questions}\n\n"
                    f"STUDENT ANSWERS:\n{answers}"
                ),
            },
        ],
        max_tokens=700,
    )

    raw = response["choices"][0]["message"]["content"]

    try:
        ai_data = json.loads(raw)
    except Exception:
        ai_data = {
            "apr_band": "—",
            "raw_score": "—",
            "overall": "Baholashda texnik noaniqlik yuz berdi.",
            "mistakes": "Ma’lumot yetarli emas.",
            "advice": "Keyinroq qayta urinib ko‘ring."
        }

    output = _format_reading_feedback(ai_data)
    _send_long_message(update.message, output)

    send_admin_card(
        context.bot,
        update.effective_user.id,
        "New IELTS Reading feedback",
        output
    )

    log_ai_usage(update.effective_user.id, "reading")
    clean_user(update.effective_user.id, reason="reading finished")
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
        clean_user(user.id, reason="reading cancel")
        clear_checker_mode(user.id)

    context.user_data.clear()

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
            CommandHandler("check_reading", start_check),
            #MessageHandler(Filters.regex("^📖 Reading$"), start_check),
        ],
        states={
            WAITING_FOR_PASSAGE: [
                MessageHandler(Filters.regex("^➡️ Davom etish$"), proceed_next),
                MessageHandler(
                    (Filters.text & ~Filters.command) | Filters.photo,
                    collect_passage
                ),
            ],
            WAITING_FOR_ANSWERS: [
                MessageHandler(Filters.regex("^➡️ Davom etish$"), proceed_next),
                MessageHandler(
                    (Filters.text & ~Filters.command) | Filters.photo,
                    collect_answers
                ),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(Filters.regex("^❌ Cancel$"), cancel),
        ],
        allow_reentry=False,
    )

    dispatcher.add_handler(conv, group=2)


def setup(dispatcher):
    register(dispatcher)
