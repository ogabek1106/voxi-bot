# features/result.py
"""
Shows test result by token.
Usage:
/result <TOKEN>
"""

import logging
import sqlite3
import os
import time

from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

from database import (
    get_test_score,
    save_test_score,
    get_active_test,
)

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "/data/data.db"))
SQLITE_TIMEOUT = 5


# ---------- helpers ----------

def _connect():
    return sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT, check_same_thread=False)


def _calculate_and_save_score(token: str, user_id: int):
    """
    Calculate score ONLY using:
    - test_answers
    - test_questions
    - active_test
    Then save into test_scores.
    """

    # 1️⃣ Get active test (this defines test_id)
    active = get_active_test()
    if not active:
        return None

    test_id = active[0]

    conn = _connect()
    cur = conn.cursor()

    # 2️⃣ Load correct answers
    cur.execute(
        """
        SELECT question_number, correct_answer
        FROM test_questions
        WHERE test_id = ?;
        """,
        (test_id,),
    )
    correct_map = {q: a for q, a in cur.fetchall()}

    total_questions = len(correct_map)
    if total_questions == 0:
        conn.close()
        return None

    # 3️⃣ Load user answers
    cur.execute(
        """
        SELECT question_number, selected_answer
        FROM test_answers
        WHERE token = ?;
        """,
        (token,),
    )
    answers = dict(cur.fetchall())

    if not answers:
        conn.close()
        return None

    # 4️⃣ Count correct
    correct_count = 0
    for q_num, correct in correct_map.items():
        if answers.get(q_num) == correct:
            correct_count += 1

    # 5️⃣ Calculate score (MAX = 100)
    score = round((correct_count / total_questions) * 100, 2)

    # 6️⃣ Save final score
    save_test_score(
        token=token,
        test_id=test_id,
        user_id=user_id,
        total_questions=total_questions,
        correct_answers=correct_count,
        score=score,
        max_score=100,
    )

    conn.close()

    return {
        "test_id": test_id,
        "user_id": user_id,
        "total": total_questions,
        "correct": correct_count,
        "score": score,
        "max": 100,
    }


# ---------- command ----------

def result_command(update: Update, context: CallbackContext):
    message = update.message
    args = context.args

    if not args:
        message.reply_text("❌ Usage:\n/result <TOKEN>")
        return

    token = args[0].strip().upper()
    user_id = message.from_user.id

    # 1️⃣ Check if score already exists
    row = get_test_score(token)

    if row:
        _, test_id, uid, total, correct, score, max_score, finished_at = row
        data = {
            "test_id": test_id,
            "user_id": uid,
            "total": total,
            "correct": correct,
            "score": score,
            "max": max_score,
        }
    else:
        # 2️⃣ Calculate & save score
        data = _calculate_and_save_score(token, user_id)
        if not data:
            message.reply_text("❌ Result not found.\nCheck your token.")
            return

    # 3️⃣ Send result
    message.reply_text(
        "📊 <b>Test Result</b>\n\n"
        f"🧮 Questions: {data['total']}\n"
        f"✅ Correct: {data['correct']}\n"
        f"🎯 Score: <b>{data['score']} / {data['max']}</b>",
        parse_mode="HTML",
    )


# ---------- setup ----------

def setup(dispatcher, bot=None):
    dispatcher.add_handler(CommandHandler("result", result_command))
    logger.info("Feature loaded: result")
