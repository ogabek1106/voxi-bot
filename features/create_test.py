#features/create_test.py
"""
Admin feature: create a new test (metadata only).

Command:
  /create_test   (admin only)

Flow (each step can be skipped with /skip):
  1) Ask test name
  2) Ask test level
  3) Ask number of questions
  4) Ask time limit (minutes)

Extra:
  /abort — cancel test creation (only inside this flow)

Result:
  - Creates a JSON file in /tests/<test_id>.json
  - Stores test metadata + empty questions list
"""

import os
import json
import logging
import time
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

# ---- paths ----
TESTS_DIR = "tests"

# ---- conversation states ----
ASK_NAME = 1
ASK_LEVEL = 2
ASK_COUNT = 3
ASK_TIME = 4


# ---- helpers ----

def _is_admin(user_id: Optional[int]) -> bool:
    if user_id is None:
        return False
    raw = getattr(admins, "ADMIN_IDS", None) or getattr(admins, "ADMINS", None) or []
    try:
        return int(user_id) in {int(x) for x in raw}
    except Exception:
        return False


def _ensure_tests_dir():
    if not os.path.exists(TESTS_DIR):
        os.makedirs(TESTS_DIR, exist_ok=True)


def _gen_test_id() -> str:
    return f"test_{int(time.time())}"


def _abort(update: Update, context: CallbackContext):
    update.message.reply_text("❌ Test creation aborted.")
    context.user_data.clear()
    return ConversationHandler.END


# ---- conversation handlers ----

def create_test_start(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        update.message.reply_text("⛔ This command is for admins only.")
        return ConversationHandler.END

    _ensure_tests_dir()

    context.user_data.clear()
    context.user_data["test_id"] = _gen_test_id()

    update.message.reply_text(
        "🧪 Creating a new test.\n\n"
        "Send test name or /skip.\n"
        "Use /abort to cancel."
    )
    return ASK_NAME


def ask_name(update: Update, context: CallbackContext):
    text = (update.message.text or "").strip()

    if text.lower() != "/skip":
        context.user_data["name"] = text or None
    else:
        context.user_data["name"] = None

    update.message.reply_text("Send test level (A2 / B1 / B2 / C1) or /skip.")
    return ASK_LEVEL


def ask_level(update: Update, context: CallbackContext):
    text = (update.message.text or "").strip()

    if text.lower() != "/skip":
        context.user_data["level"] = text or None
    else:
        context.user_data["level"] = None

    update.message.reply_text("Send number of questions or /skip.")
    return ASK_COUNT


def ask_count(update: Update, context: CallbackContext):
    text = (update.message.text or "").strip()

    if text.lower() == "/skip":
        context.user_data["question_count"] = None
    else:
        try:
            context.user_data["question_count"] = int(text)
        except Exception:
            update.message.reply_text("❗ Send a number or /skip.")
            return ASK_COUNT

    update.message.reply_text("Send time limit (minutes) or /skip.")
    return ASK_TIME


def ask_time(update: Update, context: CallbackContext):
    text = (update.message.text or "").strip()

    if text.lower() == "/skip":
        context.user_data["time_limit"] = None
    else:
        try:
            context.user_data["time_limit"] = int(text)
        except Exception:
            update.message.reply_text("❗ Send a number or /skip.")
            return ASK_TIME

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

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception:
        logger.exception("Failed to write test file")
        update.message.reply_text("❌ Failed to create test file.")
        return ConversationHandler.END

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


# ---- setup ----

def setup(dispatcher, bot=None):
    conv = ConversationHandler(
        entry_points=[CommandHandler("create_test", create_test_start)],
        states={
            ASK_NAME: [MessageHandler(Filters.text, ask_name)],
            ASK_LEVEL: [MessageHandler(Filters.text, ask_level)],
            ASK_COUNT: [MessageHandler(Filters.text, ask_count)],
            ASK_TIME: [MessageHandler(Filters.text, ask_time)],
        },
        fallbacks=[
            CommandHandler("abort", _abort),
            CommandHandler("cancel", _abort),
        ],
        allow_reentry=False,
        name="create_test_conv",
    )

    dispatcher.add_handler(conv)
    logger.info("Feature loaded: create_test")
