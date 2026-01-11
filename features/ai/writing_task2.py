# features/ai/writing_task2.py
"""
/check_writing2
IELTS Writing Task 2 AI checker (FREE MODE, command-based)

Flow:
1) User sends /check_writing2
2) Bot asks for TASK QUESTION (topic)
3) User sends topic (TEXT or IMAGE)
4) Bot asks for essay
5) User sends essay (TEXT or IMAGE)
6) Bot evaluates and replies in Uzbek
"""

import logging
import os
import base64
from features.ai.check_limits import can_use_feature
from database import log_ai_usage
from telegram.ext import DispatcherHandlerStop

from telegram import Update
from telegram.ext import (
    CallbackContext,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    Filters,
)

from openai import OpenAI

# ✅ checker state DB helpers
from database import (
    set_checker_mode,
    clear_checker_mode,
    get_checker_mode,
)

logger = logging.getLogger(__name__)

# ---------- OpenAI ----------
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ---------- States ----------
WAITING_FOR_TOPIC = 0
WAITING_FOR_ESSAY = 1

# ---------- Prompt ----------
SYSTEM_PROMPT = """
You are an IELTS  Task 2 evaluator.

You will be given:
1) The IELTS  Task 2 QUESTION (topic)
2) The student's ESSAY

Your task:
- Evaluate the essay STRICTLY based on the given question.
- Follow ONLY official public IELTS band descriptors.
- Do NOT invent new criteria.
- Do NOT claim this is an official IELTS score.
- If the essay does not fully answer the question, say it clearly.

Evaluation rules:
- Assess based ONLY on these 4 criteria internally:
  1) Task Response
  2) Coherence and Cohesion
  3) Lexical Resource
  4) Grammatical Range and Accuracy

Language rules:
- ALL explanations must be in Uzbek.
- English is allowed ONLY for:
  - Quoting user's incorrect sentence
  - Showing corrected examples
- Do NOT translate the whole essay.

IMPORTANT OUTPUT RULES (STRICT):
- You MUST output the answer using EXACTLY the following FIXED STRUCTURE.
- Section titles, wording, emojis, and order MUST NOT be changed.
- Section titles MUST be bold.
- You MUST NOT add any extra sections.
- You MUST NOT remove any section.
- You MUST NOT add explanations outside the sections.
- ONLY the <content> inside sections may change.

EXACT OUTPUT TEMPLATE (USE THIS VERBATIM):

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
- Band: range only (e.g. 5.0–5.5), 1 line
- Strength: max 1–2 short sentences
- Muhim xatolar: max 2 items
- Vocabulary errors: max 2 examples (wrong → correct)
- Grammar: list of error types only
- Do NOT rewrite the essay
- Do NOT give more than requested

Tone rules:
- Calm, teacher-like, respectful
- No exaggeration
- No praise without reason

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
    """
    OCR helper: reads text from Telegram image using OpenAI Vision.
    FIXED: correct Responses API image format (image_url with data URL).
    """
    try:
        photo = photos[-1]  # highest resolution
        file = bot.get_file(photo.file_id)
        image_bytes = file.download_as_bytearray()

        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        image_data_url = f"data:image/jpeg;base64,{image_b64}"

        response = client.responses.create(
            model="gpt-5.2",
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Extract ALL readable text from this image.\n"
                                "Return ONLY the extracted text.\n"
                                "Do NOT explain.\n"
                                "Do NOT summarize."
                            ),
                        },
                        {
                            "type": "input_image",
                            "image_url": image_data_url,
                        },
                    ],
                }
            ],
            max_output_tokens=800,
        )

        return (response.output_text or "").strip()

    except Exception:
        logger.exception("OCR failed")
        return ""


# ---------- Handlers ----------

def start_check(update: Update, context: CallbackContext):
    # 🔒 SUBSCRIPTION GATE (CRITICAL)
    from features.sub_check import require_subscription
    if not require_subscription(update, context):
        return ConversationHandler.END

    user = update.effective_user
    if not user:
        return ConversationHandler.END

    # 🔒 LIMITER GATE (ADD THIS)
    limit_result = can_use_feature(user.id, "writing")

    if not limit_result["allowed"]:
        from features.ielts_checkup_ui import _main_user_keyboard

        update.message.reply_text(
            limit_result["message"],
            parse_mode="Markdown",
            reply_markup=_main_user_keyboard()
        )

        raise DispatcherHandlerStop

    # ✅ allowed → continue flow
    set_checker_mode(user.id, "writing_task2")
    context.user_data.pop("writing_task2_topic", None)

    from features.ielts_checkup_ui import _checker_cancel_keyboard
   
    update.message.reply_text(
        "📝 *IELTS Writing Task 2 SAVOLINI (topic) yuboring.*\n\n"
        "Matn yoki rasm yuborishingiz mumkin.",
        parse_mode="Markdown",
        reply_markup=_checker_cancel_keyboard()
    )
    return WAITING_FOR_TOPIC


def receive_topic(update: Update, context: CallbackContext):
    message = update.message
    user = update.effective_user

    if not message or not user:
        return WAITING_FOR_TOPIC

    if get_checker_mode(user.id) != "writing_task2":
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

    context.user_data["writing_task2_topic"] = topic

    message.reply_text(
        "✅ *Savol qabul qilindi.*\n\n"
        "Endi ushbu savol bo‘yicha inshoni yuboring.\n"
        "Matn yoki rasm bo‘lishi mumkin.\n"
        "❗️Kamida ~80 so‘z.",
        parse_mode="Markdown"
    )
    return WAITING_FOR_ESSAY


def receive_essay(update: Update, context: CallbackContext):
    message = update.message
    user = update.effective_user

    if not message or not user:
        return WAITING_FOR_ESSAY

    if get_checker_mode(user.id) != "writing_task2":
        return ConversationHandler.END

    topic = context.user_data.get("writing_task2_topic")
    if not topic:
        message.reply_text("❗️Avval savolni yuboring.")
        return WAITING_FOR_TOPIC

    if message.text:
        essay = message.text.strip()
    elif message.photo:
        message.reply_text("🖼️ Insho rasmdan o‘qilmoqda...", parse_mode="Markdown")
        essay = _ocr_image_to_text(context.bot, message.photo)
    else:
        message.reply_text("❗️Inshoni matn yoki rasm sifatida yuboring.")
        return WAITING_FOR_ESSAY

    if len(essay.split()) < 80:
        message.reply_text(
            "❗️Matn juda qisqa yoki rasm noto‘g‘ri o‘qildi.\n"
            "Iltimos, to‘liq inshoni yuboring."
        )
        return WAITING_FOR_ESSAY

    message.reply_text(
        "*⏳ Insho tahlil qilinmoqda, iltimos kuting...*",
        parse_mode="Markdown"
    )

    try:
        response = client.responses.create(
            model="gpt-5.2",
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"IELTS Writing Task 2 Question:\n{topic}\n\n"
                        f"Student Essay:\n{essay}"
                    ),
                },
            ],
            max_output_tokens=600,
        )

        output_text = (response.output_text or "").strip()
        _send_long_message(message, output_text)
        log_ai_usage(user.id, "writing")

    except Exception:
        logger.exception("check_writing2 AI error")
        message.reply_text("❌ Xatolik yuz berdi. Keyinroq urinib ko‘ring.")

    finally:
        clear_checker_mode(user.id)
        context.user_data.pop("writing_task2_topic", None)

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

    context.user_data.pop("writing_task2_topic", None)

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
            CommandHandler("check_writing2", start_check),
            # ✅ ADD THIS
            # MessageHandler(
                # Filters.regex("^✍️ Writing$"),
                # start_check
            # ),
        ],

        states={
            WAITING_FOR_TOPIC: [
                MessageHandler(
                    (Filters.text & ~Filters.command) | Filters.photo,
                    receive_topic
                )
            ],
            WAITING_FOR_ESSAY: [
                MessageHandler(
                    (Filters.text & ~Filters.command) | Filters.photo,
                    receive_essay
                )
            ],
        },

        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=False,
    )

    dispatcher.add_handler(conv, group=2)


def setup(dispatcher):
    register(dispatcher)
