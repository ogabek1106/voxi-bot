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
)

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "/data/data.db"))
SQLITE_TIMEOUT = 5


# ---------- helpers ----------

def _connect():
    return sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT, check_same_thread=False)


def _calculate_and_save_score(token: str):
    """
    Calculates score from stored answers + correct answers,
    then saves into test_scores table.
    """

    conn = _connect()
    cur = conn.cursor()

    # 1️⃣ Find test_id + user_id from attempts table
    cur.execute(
        """
        SELECT test_id, user_id
        FROM tests
        WHERE token = ?
        LIMIT 1;
        """,
        (token,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return None

    test_id, user_id = row

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

    # 4️⃣ Count correct
    correct_count = 0
    for q_num, correct in correct_map.items():
        if answers.get(q_num) == correct:
            correct_count += 1

    # 5️⃣ Calculate score (MAX = 100)
    points_per_question = 100 / total_questions
    score = round(correct_count * points_per_question, 2)

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

    # 1️⃣ Try to load saved score
    row = get_test_score(token)

    if not row:
        # 2️⃣ If not exists → calculate now
        data = _calculate_and_save_score(token)
        if not data:
            message.reply_text("❌ Result not found.\nCheck your token.")
            return
    else:
        _, test_id, user_id, total, correct, score, max_score, finished_at = row
        data = {
            "test_id": test_id,
            "user_id": user_id,
            "total": total,
            "correct": correct,
            "score": score,
            "max": max_score,
        }

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
