# features/ai/check_writing2.py
"""
/check_writing2
IELTS Writing Task 2 AI checker (FREE MODE, command-based)

Flow:
1) User sends /check_writing2
2) Bot asks for TASK QUESTION (topic)
3) User sends topic
4) Bot asks for essay
5) User sends essay
6) Bot evaluates and replies in Uzbek
"""

import logging
import os

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
You are an IELTS Writing Task 2 evaluator.

You will be given:
1) The IELTS Writing Task 2 QUESTION (topic)
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


# ---------- Handlers ----------

def start_check(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user:
        return ConversationHandler.END

    # prevent re-entry
    if get_checker_mode(user.id):
        update.message.reply_text(
            "⚠️ Siz allaqachon tekshiruv rejimidasiz.\n\n"
            "Iltimos, savolni yoki inshoni yuboring yoki /cancel ni bosing."
        )
        return WAITING_FOR_TOPIC

    # enable checker mode
    set_checker_mode(user.id, "writing_task2")

    # clear any previous data
    context.user_data.pop("writing_task2_topic", None)

    update.message.reply_text(
        "📝 *IELTS Writing Task 2 SAVOLINI (topic) yuboring.*\n\n"
        "Masalan:\n"
        "Some people believe that change is always positive..."
    )
    return WAITING_FOR_TOPIC


def receive_topic(update: Update, context: CallbackContext):
    message = update.message
    user = update.effective_user

    if not message or not message.text or not user:
        return WAITING_FOR_TOPIC

    # DB state check
    if get_checker_mode(user.id) != "writing_task2":
        return ConversationHandler.END

    topic = message.text.strip()

    if len(topic.split()) < 5:
        message.reply_text(
            "❗️Savol juda qisqa.\n\n"
            "Iltimos, to‘liq IELTS Writing Task 2 savolini yuboring."
        )
        return WAITING_FOR_TOPIC

    # store topic temporarily
    context.user_data["writing_task2_topic"] = topic

    message.reply_text(
        "✅ *Savol qabul qilindi.*\n\n"
        "Endi ushbu savol bo‘yicha yozgan inshongizni yuboring.\n"
        "❗️Kamida ~80 so‘z."
    )
    return WAITING_FOR_ESSAY


def receive_essay(update: Update, context: CallbackContext):
    message = update.message
    user = update.effective_user

    if not message or not message.text or not user:
        return WAITING_FOR_ESSAY

    # DB state check
    if get_checker_mode(user.id) != "writing_task2":
        return ConversationHandler.END

    topic = context.user_data.get("writing_task2_topic")
    if not topic:
        message.reply_text("❗️Avval savolni yuboring.")
        return WAITING_FOR_TOPIC

    essay = message.text.strip()

    if len(essay.split()) < 80:
        message.reply_text(
            "❗️Matn juda qisqa.\n\n"
            "Iltimos, to‘liq IELTS Writing Task 2 inshosini yuboring."
        )
        return WAITING_FOR_ESSAY

    message.reply_text("*⏳ Insho tahlil qilinmoqda, iltimos kuting...*")

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

    except Exception:
        logger.exception("check_writing2 AI error")
        message.reply_text(
            "❌ Xatolik yuz berdi. Iltimos, keyinroq yana urinib ko‘ring."
        )

    finally:
        clear_checker_mode(user.id)
        context.user_data.pop("writing_task2_topic", None)

    return ConversationHandler.END


def cancel(update: Update, context: CallbackContext):
    user = update.effective_user
    if user:
        clear_checker_mode(user.id)

    context.user_data.pop("writing_task2_topic", None)
    update.message.reply_text("❌ Bekor qilindi.")
    return ConversationHandler.END


# ---------- Registration ----------

def register(dispatcher):
    """
    Auto-loaded by your feature loader.
    DO NOT rename.
    """
    conv = ConversationHandler(
        entry_points=[CommandHandler("check_writing2", start_check)],
        states={
            WAITING_FOR_TOPIC: [
                MessageHandler(Filters.text & ~Filters.command, receive_topic)
            ],
            WAITING_FOR_ESSAY: [
                MessageHandler(Filters.text & ~Filters.command, receive_essay)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=False,
    )

    dispatcher.add_handler(conv, group=2)


def setup(dispatcher):
    """
    Entry point for Voxi feature loader.
    """
    register(dispatcher)
