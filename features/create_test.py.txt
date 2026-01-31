# features/create_test.py
# these are functions that are admin only command and saves info about test only

import os
import json
import time
import logging
from database import save_test_definition, set_user_mode
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

logger = logging.getLogger(__name__)

TESTS_DIR = "tests"

ASK_NAME, ASK_LEVEL, ASK_COUNT, ASK_TIME = range(4)

def GLOBAL_DEBUG_ECHO(update: Update, context: CallbackContext):
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    uid = user.id if user else None

    if not _is_admin(uid):
        return
   
    if not allow(uid, mode="create_test"):
        return
    
    try:
        from database import get_user_mode
        mode = get_user_mode(uid) if uid else None
    except Exception as e:
        mode = f"ERR:{e}"

    update.message.reply_text(
        "🧨 GLOBAL DEBUG\n"
        f"Text: {update.message.text!r}\n"
        f"User ID: {uid}\n"
        f"DB mode: {mode}\n"
        f"user_data: {dict(context.user_data)}"
    )

def _dbg(update: Update, context: CallbackContext, where: str):
    text = update.message.text if update.message else None
    uid = update.effective_user.id if update.effective_user else None
    logger.error(
        f"[CREATE_TEST DEBUG] {where} | uid={uid} | text={text!r} | user_data={dict(context.user_data)}"
    )

# ---------- helpers ----------

def _is_admin(user_id: Optional[int]) -> bool:
    raw = getattr(admins, "ADMIN_IDS", []) or []
    return user_id is not None and int(user_id) in {int(x) for x in raw}


def _ensure_tests_dir():
    os.makedirs(TESTS_DIR, exist_ok=True)


def _gen_test_id():
    return f"test_{int(time.time())}"


def _abort(update: Update, context: CallbackContext):
    _dbg(update, context, "ABORT")

    user = update.effective_user
    if not user or not allow(user.id, mode="create_test"):
        return ConversationHandler.END

    clean_user(user.id, reason="create_test abort")

    for k in list(context.user_data.keys()):
        if k.startswith("test_") or k in {
            "name", "level", "question_count", "time_limit"
        }:
            context.user_data.pop(k, None)

    update.message.reply_text("❌ Test creation aborted.")
    return ConversationHandler.END


def _unknown_command(update: Update, context: CallbackContext):
    _dbg(update, context, "UNKNOWN_COMMAND_HANDLER")

    user = update.effective_user
    if not user or not allow(user.id, mode="create_test"):
        return ConversationHandler.END

    update.message.reply_text("❓ Please answer the question or use /skip.")
    return

# ---------- MANUAL END COMMAND ----------

def end_test(update: Update, context: CallbackContext):
    _dbg(update, context, "END_TEST")

    user = update.effective_user
    if not user or not _is_admin(user.id):
        update.message.reply_text("⛔ Admins only.")
        return ConversationHandler.END

    if not allow(user.id, mode="create_test"):
        return ConversationHandler.END

    clean_user(user.id, reason="create_test manual end")

    for k in list(context.user_data.keys()):
        if k.startswith("test_") or k in {
            "name", "level", "question_count", "time_limit"
        }:
            context.user_data.pop(k, None)

    update.message.reply_text("🛑 Test mode ended.")
    return ConversationHandler.END

# ---------- START ----------

def start(update: Update, context: CallbackContext):
    _dbg(update, context, "START")

    user = update.effective_user
    if not user or not _is_admin(user.id):
        update.message.reply_text("⛔ Admins only.")
        return ConversationHandler.END

    # 🔒 MUST be FREE to start
    if not allow(user.id, mode=None, allow_free=False):
        return ConversationHandler.END

    _ensure_tests_dir()

    for k in list(context.user_data.keys()):
        if k.startswith("test_") or k in {
            "name", "level", "question_count", "time_limit"
        }:
            context.user_data.pop(k, None)

    context.user_data["test_id"] = _gen_test_id()

    set_user_mode(user.id, "create_test")

    update.message.reply_text(
        "🧪 Creating a new test.\n\n"
        "Send test name.\n"
        "/skip — skip step\n"
        "/abort — cancel\n"
        "/end_test — finish test mode"
    )
    return ASK_NAME

# ---------- NAME ----------

def name_text(update: Update, context: CallbackContext):
    _dbg(update, context, "NAME_TEXT_HANDLER_HIT")

    user = update.effective_user
    if not user or not allow(user.id, mode="create_test"):
        return ConversationHandler.END

    context.user_data["name"] = update.message.text.strip()
    update.message.reply_text(
        "✅ Name saved.\nSend test level (A2 / B1 / B2 / C1) or /skip."
    )
    return ASK_LEVEL


def name_skip(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not allow(user.id, mode="create_test"):
        return ConversationHandler.END

    context.user_data["name"] = None
    update.message.reply_text("⏭ Name skipped.\nSend test level or /skip.")
    return ASK_LEVEL

# ---------- LEVEL ----------

def level_text(update: Update, context: CallbackContext):
    _dbg(update, context, "LEVEL_TEXT_HANDLER_HIT")

    user = update.effective_user
    if not user or not allow(user.id, mode="create_test"):
        return ConversationHandler.END

    context.user_data["level"] = update.message.text.strip()
    update.message.reply_text("✅ Level saved.\nSend number of questions or /skip.")
    return ASK_COUNT


def level_skip(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not allow(user.id, mode="create_test"):
        return ConversationHandler.END

    context.user_data["level"] = None
    update.message.reply_text("⏭ Level skipped.\nSend number of questions or /skip.")
    return ASK_COUNT

# ---------- QUESTION COUNT ----------

def count_text(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not allow(user.id, mode="create_test"):
        return ConversationHandler.END

    try:
        context.user_data["question_count"] = int(update.message.text.strip())
    except ValueError:
        update.message.reply_text("❗ Please send a NUMBER or /skip.")
        return ASK_COUNT

    update.message.reply_text(
        "✅ Question count saved.\nSend time limit (minutes) or /skip."
    )
    return ASK_TIME


def count_skip(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not allow(user.id, mode="create_test"):
        return ConversationHandler.END

    context.user_data["question_count"] = None
    update.message.reply_text("⏭ Question count skipped.\nSend time limit or /skip.")
    return ASK_TIME

# ---------- TIME LIMIT ----------

def time_text(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not allow(user.id, mode="create_test"):
        return ConversationHandler.END

    try:
        context.user_data["time_limit"] = int(update.message.text.strip())
    except ValueError:
        update.message.reply_text("❗ Please send a NUMBER or /skip.")
        return ASK_TIME

    return finish(update, context)


def time_skip(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not allow(user.id, mode="create_test"):
        return ConversationHandler.END

    context.user_data["time_limit"] = None
    return finish(update, context)

# ---------- FINISH ----------

def finish(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not allow(user.id, mode="create_test"):
        return ConversationHandler.END

    test_id = context.user_data.get("test_id")
    if not test_id:
        clean_user(user.id, reason="create_test finish missing test_id")
        return ConversationHandler.END

    data = {
        "test_id": test_id,
        "name": context.user_data.get("name"),
        "level": context.user_data.get("level"),
        "question_count": context.user_data.get("question_count"),
        "time_limit": context.user_data.get("time_limit"),
        "questions": [],
    }

    save_test_definition(
        test_id=test_id,
        name=data["name"],
        level=data["level"],
        question_count=data["question_count"],
        time_limit=data["time_limit"],
    )

    path = os.path.join(TESTS_DIR, f"{test_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    update.message.reply_text(
        "✅ Test definition created!\n\n"
        f"ID: {test_id}\n"
        f"Name: {data['name']}\n"
        f"Level: {data['level']}\n"
        f"Questions: {data['question_count']}\n"
        f"Time limit: {data['time_limit']} min\n"
    )

    clean_user(user.id, reason="create_test finished successfully")

    return ConversationHandler.END

# ---------- SETUP ----------

def setup(dispatcher, bot=None):
    conv = ConversationHandler(
        entry_points=[CommandHandler("create_test", start)],
        states={
            ASK_NAME: [
                CommandHandler("skip", name_skip),
                CommandHandler("abort", _abort),
                CommandHandler("end_test", end_test),
                MessageHandler(Filters.command, _unknown_command),
                MessageHandler(Filters.text, name_text),
            ],
            ASK_LEVEL: [
                CommandHandler("skip", level_skip),
                CommandHandler("abort", _abort),
                CommandHandler("end_test", end_test),
                MessageHandler(Filters.command, _unknown_command),
                MessageHandler(Filters.text, level_text),
            ],
            ASK_COUNT: [
                CommandHandler("skip", count_skip),
                CommandHandler("abort", _abort),
                CommandHandler("end_test", end_test),
                MessageHandler(Filters.command, _unknown_command),
                MessageHandler(Filters.text, count_text),
            ],
            ASK_TIME: [
                CommandHandler("skip", time_skip),
                CommandHandler("abort", _abort),
                CommandHandler("end_test", end_test),
                MessageHandler(Filters.command, _unknown_command),
                MessageHandler(Filters.text, time_text),
            ],
        },
        fallbacks=[
            CommandHandler("abort", _abort),
            CommandHandler("end_test", end_test),
        ],
        per_user=True,
        allow_reentry=True,
        name="create_test_conv",
    )

    dispatcher.add_handler(conv, group=-100)
    dispatcher.add_handler(CommandHandler("end_test", end_test), group=-100)

    logger.info("Feature loaded: create_test (TEST DEFINITIONS ONLY)")
