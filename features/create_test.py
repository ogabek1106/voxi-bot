# features/create_test.py
import os
import json
import time
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

logger = logging.getLogger(__name__)

TESTS_DIR = "tests"

ASK_NAME, ASK_LEVEL, ASK_COUNT, ASK_TIME = range(4)


# ---------- helpers ----------

def _is_admin(user_id: Optional[int]) -> bool:
    raw = getattr(admins, "ADMIN_IDS", []) or []
    return user_id is not None and int(user_id) in {int(x) for x in raw}


def _ensure_tests_dir():
    os.makedirs(TESTS_DIR, exist_ok=True)


def _gen_test_id():
    return f"test_{int(time.time())}"


def _abort(update: Update, context: CallbackContext):
    context.user_data.clear()
    update.message.reply_text("❌ Test creation aborted.")
    return ConversationHandler.END


def _unknown_command(update: Update, context: CallbackContext):
    update.message.reply_text("❓ Sorry?")
    return None


# ---------- start ----------

def start(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        update.message.reply_text("⛔ Admins only.")
        return ConversationHandler.END

    _ensure_tests_dir()
    context.user_data.clear()
    context.user_data["test_id"] = _gen_test_id()

    update.message.reply_text(
        "🧪 Creating a new test.\n\n"
        "Send test name.\n"
        "/skip — skip step\n"
        "/abort — cancel"
    )
    return ASK_NAME


# ---------- NAME ----------

def name_text(update: Update, context: CallbackContext):
    value = update.message.text.strip()
    context.user_data["name"] = value

    update.message.reply_text(f"✅ Received name: {value}")
    update.message.reply_text("Send test level (A2 / B1 / B2 / C1) or /skip.")
    return ASK_LEVEL


def name_skip(update: Update, context: CallbackContext):
    context.user_data["name"] = None
    update.message.reply_text("⏭ Name skipped.")
    update.message.reply_text("Send test level (A2 / B1 / B2 / C1) or /skip.")
    return ASK_LEVEL


# ---------- LEVEL ----------

def level_text(update: Update, context: CallbackContext):
    value = update.message.text.strip()
    context.user_data["level"] = value

    update.message.reply_text(f"✅ Received level: {value}")
    update.message.reply_text("Send number of questions or /skip.")
    return ASK_COUNT


def level_skip(update: Update, context: CallbackContext):
    context.user_data["level"] = None
    update.message.reply_text("⏭ Level skipped.")
    update.message.reply_text("Send number of questions or /skip.")
    return ASK_COUNT


# ---------- COUNT ----------

def count_text(update: Update, context: CallbackContext):
    try:
        value = int(update.message.text.strip())
    except ValueError:
        update.message.reply_text("❗ Please send a NUMBER or /skip.")
        return ASK_COUNT

    context.user_data["question_count"] = value
    update.message.reply_text(f"✅ Received number of questions: {value}")
    update.message.reply_text("Send time limit (minutes) or /skip.")
    return ASK_TIME


def count_skip(update: Update, context: CallbackContext):
    context.user_data["question_count"] = None
    update.message.reply_text("⏭ Question count skipped.")
    update.message.reply_text("Send time limit (minutes) or /skip.")
    return ASK_TIME


# ---------- TIME ----------

def time_text(update: Update, context: CallbackContext):
    try:
        value = int(update.message.text.strip())
    except ValueError:
        update.message.reply_text("❗ Please send a NUMBER or /skip.")
        return ASK_TIME

    context.user_data["time_limit"] = value
    update.message.reply_text(f"✅ Received time limit: {value} minutes")
    return finish(update, context)


def time_skip(update: Update, context: CallbackContext):
    context.user_data["time_limit"] = None
    update.message.reply_text("⏭ Time limit skipped.")
    return finish(update, context)


# ---------- FINISH ----------

def finish(update: Update, context: CallbackContext):
    test_id = context.user_data["test_id"]

    data = {
        "id": test_id,
        "name": context.user_data.get("name"),
        "level": context.user_data.get("level"),
        "question_count": context.user_data.get("question_count"),
        "time_limit": context.user_data.get("time_limit"),
        "questions": [],
    }

    path = os.path.join(TESTS_DIR, f"{test_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    update.message.reply_text(
        "✅ Test created successfully!\n\n"
        f"ID: {test_id}\n"
        f"Name: {data['name']}\n"
        f"Level: {data['level']}\n"
        f"Questions: {data['question_count']}\n"
        f"Time limit: {data['time_limit']} min"
    )

    context.user_data.clear()
    return ConversationHandler.END


# ---------- setup ----------

def setup(dispatcher, bot=None):
    conv = ConversationHandler(
        entry_points=[CommandHandler("create_test", start)],
        states={
            ASK_NAME: [
                CommandHandler("skip", name_skip),
                CommandHandler("abort", _abort),
                MessageHandler(Filters.command, _unknown_command),
                MessageHandler(Filters.text, name_text),
            ],
            ASK_LEVEL: [
                CommandHandler("skip", level_skip),
                CommandHandler("abort", _abort),
                MessageHandler(Filters.command, _unknown_command),
                MessageHandler(Filters.text, level_text),
            ],
            ASK_COUNT: [
                CommandHandler("skip", count_skip),
                CommandHandler("abort", _abort),
                MessageHandler(Filters.command, _unknown_command),
                MessageHandler(Filters.text, count_text),
            ],
            ASK_TIME: [
                CommandHandler("skip", time_skip),
                CommandHandler("abort", _abort),
                MessageHandler(Filters.command, _unknown_command),
                MessageHandler(Filters.text, time_text),
            ],
        },
        fallbacks=[CommandHandler("abort", _abort)],
        per_user=True,
        per_chat=True,
        name="create_test_conv",
    )

    # 🔴 THIS LINE IS THE FIX
    dispatcher.add_handler(conv, group=-100)

    logger.info("Feature loaded: create_test (locked admin flow)")
