# features/ai/check_writing2.py
"""
/check_writing2
IELTS Writing Task 2 AI checker (FREE MODE, command-based)

Flow:
1) User sends /check_writing2
2) Bot asks for essay
3) User sends essay
4) Bot evaluates and replies in Uzbek
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

logger = logging.getLogger(__name__)

# ---------- OpenAI ----------
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ---------- States ----------
WAITING_FOR_ESSAY = 1

# ---------- Prompt ----------
SYSTEM_PROMPT = """
You are an IELTS Writing Task 2 evaluator.

Your task:
- Evaluate ONLY IELTS Writing Task 2 essays.
- Follow ONLY official public IELTS band descriptors.
- Do NOT invent new criteria.
- Do NOT claim this is an official IELTS score.
- If text is too short or irrelevant, say it clearly.

Evaluation rules:
- Assess based on these 4 criteria only:
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

Output rules:
- Be clear, calm, and teacher-like.
- Do NOT use emojis.
- Do NOT mention AI, model, or OpenAI.
- Output must follow the structure exactly.

IMPORTANT:
- This is an ESTIMATED band score, not official.

FREE MODE:
- Give only a band RANGE (example: 6.0–6.5).
- List maximum 2 mistakes.
- Give maximum 2 improvement tips.
- Do NOT rewrite the essay.
"""

# ---------- Helpers ----------

MAX_TELEGRAM_LEN = 4000


def _send_long_message(message, text: str):
    """
    Safely send long text by splitting into Telegram-sized chunks.
    """
    if not text:
        return

    for i in range(0, len(text), MAX_TELEGRAM_LEN):
        message.reply_text(text[i:i + MAX_TELEGRAM_LEN])


# ---------- Handlers ----------

def start_check(update: Update, context: CallbackContext):
    update.message.reply_text(
        "✍️ IELTS Writing Task 2 inshongizni yuboring.\n\n"
        "❗️Faqat to‘liq insho yuboring (kamida ~80 so‘z)."
    )
    return WAITING_FOR_ESSAY


def receive_essay(update: Update, context: CallbackContext):
    message = update.message
    if not message or not message.text:
        return WAITING_FOR_ESSAY

    essay = message.text.strip()

    if len(essay.split()) < 80:
        message.reply_text(
            "❗️Matn juda qisqa. Iltimos, to‘liq IELTS Writing Task 2 inshosini yuboring."
        )
        return WAITING_FOR_ESSAY

    # IMPORTANT: send immediately (UX + Telegram keep-alive)
    message.reply_text("⏳ Insho tahlil qilinmoqda, iltimos kuting...")

    try:
        response = client.responses.create(
            model="gpt-5.2",
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": essay},
            ],
            max_output_tokens=500,
        )

        output_text = (response.output_text or "").strip()
        _send_long_message(message, output_text)

    except Exception:
        logger.exception("check_writing2 AI error")
        message.reply_text(
            "❌ Xatolik yuz berdi. Iltimos, keyinroq yana urinib ko‘ring."
        )

    return ConversationHandler.END


def cancel(update: Update, context: CallbackContext):
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
            WAITING_FOR_ESSAY: [
                MessageHandler(Filters.text & ~Filters.command, receive_essay)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=False,
    )

    dispatcher.add_handler(conv)


def setup(dispatcher):
    """
    Entry point for Voxi feature loader.
    """
    register(dispatcher)
