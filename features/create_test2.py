# features/create_test2.py
# Handles QUESTION creation for tests (AFTER test definition exists)

import logging
from typing import Optional

from telegram import Update
from telegram.ext import (
    CallbackContext,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    Filters,
)

import admins
from database import save_test_question, get_test_definition

logger = logging.getLogger(__name__)

# ---- STATES ----
ASK_QUESTION, ASK_ANSWERS, ASK_CORRECT = range(3)

# ---------- helpers ----------

def _is_admin(user_id: Optional[int]) -> bool:
    raw = getattr(admins, "ADMIN_IDS", []) or []
    return user_id is not None and int(user_id) in {int(x) for x in raw}


def _unknown_command(update: Update, context: CallbackContext):
    update.message.reply_text("❓ Please answer the question or use /skip.")
    return None


def _parse_answers(text: str):
    """
    Expect:
    a - ...
    b - ...
    c - ...
    d - ...
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if len(lines) != 4:
        return None

    answers = {}
    for line in lines:
        if "-" not in line:
            return None
        key, val = line.split("-", 1)
        key = key.strip().lower()
        val = val.strip()
        if key not in ("a", "b", "c", "d") or not val:
            return None
        answers[key] = val

    if len(answers) != 4:
        return None

    return answers


# ---------- END COMMAND (FIXED) ----------

def end_test(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        update.message.reply_text("⛔ Admins only.")
        return ConversationHandler.END

    if context.user_data.get("question_mode"):
        context.user_data.clear()
        update.message.reply_text("🛑 Test creation mode ended.")
        return ConversationHandler.END   # 🔴 IMPORTANT FIX

    update.message.reply_text("ℹ️ You are not in test creation mode.")
    return ConversationHandler.END


# ---------- START QUESTION MODE ----------

def start_questions(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        update.message.reply_text("⛔ Admins only.")
        return ConversationHandler.END

    test_id = context.user_data.get("test_id")
    if not test_id:
        update.message.reply_text("❌ No active test found. Create a test first.")
        return ConversationHandler.END

    test_def = get_test_definition(test_id)
    if not test_def:
        update.message.reply_text("❌ Test definition not found in DB.")
        return ConversationHandler.END

    _, _, _, question_count, _, _ = test_def

    context.user_data["question_mode"] = True
    context.user_data["question_count"] = int(question_count)
    context.user_data["current_q"] = 1

    update.message.reply_text(
        "✍️ Now send questions one by one.\n\n"
        "Question 1:"
    )
    return ASK_QUESTION


# ---------- QUESTION TEXT ----------

def question_text(update: Update, context: CallbackContext):
    context.user_data["question_text"] = update.message.text.strip()

    update.message.reply_text(
        "Now send answers in this format:\n\n"
        "a - ...\n"
        "b - ...\n"
        "c - ...\n"
        "d - ..."
    )
    return ASK_ANSWERS


# ---------- ANSWERS ----------

def answers_text(update: Update, context: CallbackContext):
    parsed = _parse_answers(update.message.text)
    if not parsed:
        update.message.reply_text(
            "❗ Invalid format.\nUse:\n"
            "a - ...\n"
            "b - ...\n"
            "c - ...\n"
            "d - ..."
        )
        return ASK_ANSWERS

    context.user_data["answers"] = parsed
    update.message.reply_text("Now send correct answer (a / b / c / d).")
    return ASK_CORRECT


# ---------- CORRECT ANSWER ----------

def correct_text(update: Update, context: CallbackContext):
    correct = update.message.text.strip().lower()
    if correct not in ("a", "b", "c", "d"):
        update.message.reply_text("❗ Correct answer must be a / b / c / d.")
        return ASK_CORRECT

    test_id = context.user_data["test_id"]
    q_num = context.user_data["current_q"]

    save_test_question(
        test_id=test_id,
        question_number=q_num,
        question_text=context.user_data["question_text"],
        answers=context.user_data["answers"],
        correct_answer=correct,
    )

    total = context.user_data["question_count"]
    q_num += 1
    context.user_data["current_q"] = q_num

    if q_num > total:
        update.message.reply_text(
            "🎉 All questions saved!\n\n"
            "Test is READY.\n"
            "Send /end_test to exit creation mode."
        )
        return ConversationHandler.END

    update.message.reply_text(f"✅ Saved.\n\nQuestion {q_num}:")
    return ASK_QUESTION


# ---------- SETUP ----------

def setup(dispatcher, bot=None):
    conv = ConversationHandler(
        entry_points=[CommandHandler("add_questions", start_questions)],
        states={
            ASK_QUESTION: [
                CommandHandler("end_test", end_test),
                MessageHandler(Filters.command, _unknown_command),
                MessageHandler(Filters.text, question_text),
            ],
            ASK_ANSWERS: [
                CommandHandler("end_test", end_test),
                MessageHandler(Filters.command, _unknown_command),
                MessageHandler(Filters.text, answers_text),
            ],
            ASK_CORRECT: [
                CommandHandler("end_test", end_test),
                MessageHandler(Filters.command, _unknown_command),
                MessageHandler(Filters.text, correct_text),
            ],
        },
        fallbacks=[CommandHandler("end_test", end_test)],
        per_user=True,
        per_chat=True,
        name="create_test_questions_conv",
    )

    dispatcher.add_handler(conv, group=-100)
    dispatcher.add_handler(CommandHandler("end_test", end_test), group=-100)

    logger.info("Feature loaded: create_test2 (QUESTION CREATION)")
