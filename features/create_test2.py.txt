# features/create_test2.py
# Handles QUESTION creation for tests (AFTER test definition exists)

import logging
from typing import Optional

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

import admins
from database import save_test_question, get_test_definition

logger = logging.getLogger(__name__)

# ---- STATES ----
ASK_TEST_ID, ASK_QUESTION, ASK_ANSWERS, ASK_CORRECT = range(4)

MODE_NAME = "create_test_questions"

# ---------- helpers ----------

def _is_admin(user_id: Optional[int]) -> bool:
    raw = getattr(admins, "ADMIN_IDS", []) or []
    return user_id is not None and int(user_id) in {int(x) for x in raw}


def _unknown_command(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not allow(user.id, mode=MODE_NAME):
        return ConversationHandler.END

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


# ---------- END COMMAND ----------

def end_test(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        update.message.reply_text("⛔ Admins only.")
        return ConversationHandler.END

    if not allow(user.id, mode=MODE_NAME):
        return ConversationHandler.END

    clean_user(user.id, reason="create_test_questions manual end")
    context.user_data.clear()

    update.message.reply_text("🛑 Test creation mode ended.")
    return ConversationHandler.END


# ---------- START QUESTION MODE ----------

def start_questions(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        update.message.reply_text("⛔ Admins only.")
        return ConversationHandler.END

    # 🔒 MUST be FREE to start
    if not allow(user.id, mode=None, allow_free=False):
        return ConversationHandler.END

    from database import set_user_mode
    set_user_mode(user.id, MODE_NAME)

    context.user_data.clear()

    update.message.reply_text("🆔 Send test_id for which you want to add questions:")
    return ASK_TEST_ID

# ---------- QUESTION TEXT ----------

def test_id_text(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not allow(user.id, mode=MODE_NAME):
        return ConversationHandler.END

    test_id = update.message.text.strip()
    test_def = get_test_definition(test_id)
    if not test_def:
        update.message.reply_text("❌ Test not found. Send valid test_id.")
        return ASK_TEST_ID

    _, _, _, question_count, _, _ = test_def

    context.user_data.clear()
    context.user_data["test_id"] = test_id
    context.user_data["question_count"] = int(question_count)
    context.user_data["current_q"] = 1

    update.message.reply_text("✍️ Question 1:")
    return ASK_QUESTION


def question_text(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not allow(user.id, mode=MODE_NAME):
        return ConversationHandler.END

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
    user = update.effective_user
    if not user or not allow(user.id, mode=MODE_NAME):
        return ConversationHandler.END

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
    user = update.effective_user
    if not user or not allow(user.id, mode=MODE_NAME):
        return ConversationHandler.END

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
        clean_user(user.id, reason="create_test_questions finished")
        context.user_data.clear()
        return ConversationHandler.END

    update.message.reply_text(f"✅ Saved.\n\nQuestion {q_num}:")
    return ASK_QUESTION


def cancel(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not allow(user.id, mode=MODE_NAME):
        return ConversationHandler.END

    clean_user(user.id, reason="create_test_questions cancelled")
    context.user_data.clear()
    update.message.reply_text("🛑 Question creation cancelled.")
    return ConversationHandler.END


# ---------- SETUP ----------

def setup(dispatcher, bot=None):
    conv = ConversationHandler(
        entry_points=[CommandHandler("add_questions", start_questions)],
        states={
            ASK_TEST_ID: [
                CommandHandler("end_test", end_test),
                CommandHandler("cancel", cancel),
                MessageHandler(Filters.command, _unknown_command),
                MessageHandler(Filters.text, test_id_text),
            ],
            ASK_QUESTION: [
                CommandHandler("end_test", end_test),
                CommandHandler("cancel", cancel),
                MessageHandler(Filters.command, _unknown_command),
                MessageHandler(Filters.text, question_text),
            ],
            ASK_ANSWERS: [
                CommandHandler("end_test", end_test),
                CommandHandler("cancel", cancel),
                MessageHandler(Filters.command, _unknown_command),
                MessageHandler(Filters.text, answers_text),
            ],
            ASK_CORRECT: [
                CommandHandler("end_test", end_test),
                CommandHandler("cancel", cancel),
                MessageHandler(Filters.command, _unknown_command),
                MessageHandler(Filters.text, correct_text),
            ],
        },
        fallbacks=[CommandHandler("end_test", end_test), CommandHandler("cancel", cancel),],
        per_user=True,
        per_chat=True,
        name="create_test_questions_conv",
    )

    dispatcher.add_handler(conv, group=-100)
    dispatcher.add_handler(CommandHandler("end_test", end_test), group=-100)

    logger.info("Feature loaded: create_test2 (QUESTION CREATION)")
