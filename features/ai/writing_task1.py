# features/ai/writing_task1.py
"""
/check_writing1
IELTS Writing Task 1 AI checker (FREE MODE, command-based)

Flow:
1) User sends /check_writing1
2) Bot asks for TASK 1 QUESTION (graph / table / process / map)
3) User sends question (TEXT or IMAGE)
4) Bot asks for report
5) User sends report (TEXT or IMAGE)
6) Bot evaluates and replies in Uzbek
"""

import logging
import os
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
from features.admin_feedback import send_admin_card, store_writing_essay
from features.ai.check_limits import can_use_feature
from database import log_ai_usage

import openai

# checker mode helpers
from database import (
    set_checker_mode,
    clear_checker_mode,
    get_checker_mode,
)

logger = logging.getLogger(__name__)

# ---------- States ----------
WAITING_FOR_TOPIC = 0
WAITING_FOR_REPORT = 1

openai.api_key = os.getenv("OPENAI_API_KEY")

# ---------- Prompt ----------
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

# ---------- Helpers ----------
MAX_TELEGRAM_LEN = 4000


def _send_long_message(message, text: str):
    if not text:
        return

    for i in range(0, len(text), MAX_TELEGRAM_LEN):
        message.reply_text(
            text[i:i + MAX_TELEGRAM_LEN],
            parse_mode="Markdown"
        )


def _ocr_image_to_text(bot, photos):
    """Extract text from image using OpenAI Vision."""
    try:
        photo = photos[-1]
        file = bot.get_file(photo.file_id)
        image_bytes = file.download_as_bytearray()

        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        image_data_url = f"data:image/jpeg;base64,{image_b64}"

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
                                "Return ONLY the extracted text.\n"
                                "Do NOT explain."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_data_url
                            },
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
    # 🔒 subscription gate
    from features.sub_check import require_subscription
    if not require_subscription(update, context):
        return ConversationHandler.END

    user = update.effective_user
    if not user:
        return ConversationHandler.END

    # 🔒 usage limits
    limit_result = can_use_feature(user.id, "writing")
    if not limit_result["allowed"]:
        from features.ielts_checkup_ui import _main_user_keyboard

        update.message.reply_text(
            limit_result["message"],
            parse_mode="Markdown",
            reply_markup=_main_user_keyboard()
        )
        raise DispatcherHandlerStop

    set_checker_mode(user.id, "writing_task1")
    context.user_data.pop("writing_task1_topic", None)
    
    from features.ielts_checkup_ui import _checker_cancel_keyboard
    update.message.reply_text(
        "📝 *IELTS Writing Task 1 SAVOLINI yuboring.*\n\n"
        "Grafik, jadval, jarayon yoki xarita bo‘lishi mumkin.\n"
        "Matn yoki rasm yuboring.",
        parse_mode="Markdown",
        reply_markup=_checker_cancel_keyboard()
    )
    return WAITING_FOR_TOPIC


def receive_topic(update: Update, context: CallbackContext):
    message = update.message
    user = update.effective_user

    if not message or not user:
        return WAITING_FOR_TOPIC

    if get_checker_mode(user.id) != "writing_task1":
        return ConversationHandler.END

    if message.text:
        topic = message.text.strip()
    elif message.photo:
        message.reply_text("🖼️ Savol rasmdan o‘qilmoqda...", parse_mode="Markdown")
        topic = _ocr_image_to_text(context.bot, message.photo)
    else:
        message.reply_text("❗️Savolni matn yoki rasm sifatida yuboring.")
        return WAITING_FOR_TOPIC

    if len(topic.split()) < 5:
        message.reply_text(
            "❗️Savol juda qisqa yoki noto‘g‘ri o‘qildi.\n"
            "Iltimos, aniqroq savol yuboring."
        )
        return WAITING_FOR_TOPIC

    context.user_data["writing_task1_topic"] = topic

    message.reply_text(
        "✅ *Savol qabul qilindi.*\n\n"
        "Endi ushbu savol bo‘yicha javobingizni yuboring.\n"
        "❗️Kamida ~80 so‘z.",
        parse_mode="Markdown"
    )
    return WAITING_FOR_REPORT


def receive_report(update: Update, context: CallbackContext):
    message = update.message
    user = update.effective_user

    if not message or not user:
        return WAITING_FOR_REPORT

    if get_checker_mode(user.id) != "writing_task1":
        return ConversationHandler.END

    topic = context.user_data.get("writing_task1_topic")
    if not topic:
        message.reply_text("❗️Avval savolni yuboring.")
        return WAITING_FOR_TOPIC

    if message.text:
        report = message.text.strip()
    elif message.photo:
        message.reply_text("🖼️ Javob rasmdan o‘qilmoqda...", parse_mode="Markdown")
        report = _ocr_image_to_text(context.bot, message.photo)

    else:
        message.reply_text("❗️Javobni matn yoki rasm sifatida yuboring.")
        return WAITING_FOR_REPORT

    # 🔐 Store RAW essay for AI analysis (internal, user never sees this)
    store_writing_essay(
        context.bot,
        report,
        "#writing1"
    )
      
    if len(report.split()) < 80:
        message.reply_text(
            "❗️Matn juda qisqa yoki rasm noto‘g‘ri o‘qildi.\n"
            "Iltimos, to‘liq javob yuboring."
        )
        return WAITING_FOR_REPORT

    message.reply_text(
        "*⏳ Javob tahlil qilinmoqda, iltimos kuting...*",
        parse_mode="Markdown"
    )

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"IELTS Writing Task 1 Question:\n{topic}\n\n"
                        f"Student Report:\n{report}"
                    ),
                },
            ],
            max_tokens=600,
        )


        output_text = response["choices"][0]["message"]["content"].strip()
        
        _send_long_message(message, output_text)
        send_admin_card(
            context.bot,
            user.id,
            "New IELTS Writing Task 1 feedback",
            output_text
        )
        log_ai_usage(user.id, "writing")

    except Exception:
        logger.exception("check_writing1 AI error")
        message.reply_text("❌ Xatolik yuz berdi. Keyinroq urinib ko‘ring.")

    finally:
        clear_checker_mode(user.id)
        context.user_data.pop("writing_task1_topic", None)

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

    context.user_data.pop("writing_task1_topic", None)

    from features.ielts_checkup_ui import _ielts_skills_reply_keyboard
    from telegram.ext import DispatcherHandlerStop

    update.message.reply_text(
        "❌ Tekshiruv bekor qilindi.",
        reply_markup=_ielts_skills_reply_keyboard()
    )

    raise DispatcherHandlerStop


# ---------- Registration ----------
def register(dispatcher):
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("check_writing1", start_check),
            MessageHandler(Filters.regex("^📝 Writing Task 1$"), start_check),
        ],
        states={
            WAITING_FOR_TOPIC: [
                MessageHandler(
                    (Filters.text & ~Filters.command) | Filters.photo,
                    receive_topic
                )
            ],
            WAITING_FOR_REPORT: [
                MessageHandler(
                    (Filters.text & ~Filters.command) | Filters.photo,
                    receive_report
                )
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
