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
from features.admin_feedback import send_admin_card, store_writing_essay
from global_checker import allow
from global_cleaner import clean_user
from telegram import Update
from database import get_checker_mode
from telegram.ext import (
    CallbackContext,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    Filters,
)

import openai

# ✅ checker state DB helpers
from database import set_checker_mode

logger = logging.getLogger(__name__)

# ---------- OpenAI ----------
openai.api_key = os.getenv("OPENAI_API_KEY")

# ---------- States ----------
WAITING_FOR_TOPIC = 0
WAITING_FOR_ESSAY = 1

# ---------- Prompt ----------
SYSTEM_PROMPT = """
You are an IELTS Writing Task 2 evaluator.

You will be given:
1) The IELTS Writing Task 2 QUESTION
2) The student's ESSAY

Your task:
- Evaluate the essay STRICTLY based on the given question.
- Follow ONLY official public IELTS Writing Task 2 band descriptors.
- Do NOT invent criteria.
- Do NOT claim this is an official IELTS score.
- If the essay does not fully answer the question, say it clearly.

Assessment criteria (internal only):
1) Task Response
2) Coherence and Cohesion
3) Lexical Resource
4) Grammatical Range and Accuracy

Language rules:
- ALL explanations must be in Uzbek.
- English allowed ONLY for:
  - Quoting incorrect sentences
  - Showing corrected examples
- Do NOT translate the whole essay.

IMPORTANT OUTPUT RULES (STRICT):
- Use EXACTLY the structure below.
- Do NOT add/remove sections.
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

FREE MODE LIMITS:
- Band: range only (e.g. 5.0–5.5)
- Strength: max 1–2 short sentences
- Muhim xatolar: max 2 items
- Vocabulary: max 2 examples (wrong → correct)
- Grammar: error TYPES only
- Do NOT rewrite the essay

Tone:
- Calm, teacher-like
- No exaggeration

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
                                "Do NOT explain.\n"
                                "Do NOT summarize."
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
    # 🔒 SUBSCRIPTION GATE (CRITICAL)
    from features.sub_check import require_subscription
    if not require_subscription(update, context):
        return ConversationHandler.END

    user = update.effective_user
    if not user:
        return ConversationHandler.END

    if not allow(user.id, mode="ielts_check_up"):
        return False
    
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

    # 1️⃣ global corridor
    if not allow(user.id, mode="ielts_check_up"):
        return False
   
    if not message or not user:
        return WAITING_FOR_TOPIC

    if get_checker_mode(user.id) != "writing_task2":
        return False

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

    # 1️⃣ global corridor
    if not allow(user.id, mode="ielts_check_up"):
        return False
        
    if not message or not user:
        return WAITING_FOR_ESSAY

    if get_checker_mode(user.id) != "writing_task2":
        return False

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

    # 🔐 Store RAW essay for AI analysis (internal, user never sees this)
    store_writing_essay(
        context.bot,
        essay,
        "#writing2"
    )
    
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"IELTS Writing Task 2 Question:\n{topic}\n\n"
                        f"Student Essay:\n{essay}"
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
            "New IELTS Writing Task 2 feedback",
            output_text
        )
        
        log_ai_usage(user.id, "writing")

    except Exception:
        logger.exception("check_writing2 AI error")
        message.reply_text("❌ Xatolik yuz berdi. Keyinroq urinib ko‘ring.")

    finally:
        clean_user(user.id, reason="writing_task2 finished")
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
        clean_user(user.id, reason="writing_task2 cancel")

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
            MessageHandler(Filters.regex("^🧠 Writing Task 2$"), start_check),            
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
