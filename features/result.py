# features/result.py
"""
Shows test result.
Usage:
/result            -> show your own latest result
/result <TOKEN>    -> admin only (exact token lookup)
"""

import logging
import sqlite3
import os

from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

import admins
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


def _is_admin(user_id: int) -> bool:
    raw = getattr(admins, "ADMIN_IDS", []) or []
    return int(user_id) in {int(x) for x in raw}


def _get_latest_score_by_user(user_id: int):
    conn = _connect()
    cur = conn.execute(
        """
        SELECT
            token,
            test_id,
            user_id,
            total_questions,
            correct_answers,
            score,
            max_score,
            finished_at,
            time_left,
            auto_finished
        FROM test_scores
        WHERE user_id = ?
        ORDER BY finished_at DESC
        LIMIT 1;
        """,
        (int(user_id),),
    )
    row = cur.fetchone()
    conn.close()
    return row


def _calculate_and_save_score(token: str, user_id: int):
    """
    Calculate score using:
    - test_answers
    - test_questions
    - active_test
    Save into test_scores.
    """

    active = get_active_test()
    if not active:
        return None

    test_id, _, _, _, time_limit, _ = active

    conn = _connect()
    cur = conn.cursor()

    # Correct answers
    cur.execute(
        """
        SELECT question_number, correct_answer
        FROM test_questions
        WHERE test_id = ?;
        """,
        (test_id,),
    )
    correct_map = dict(cur.fetchall())
    if not correct_map:
        conn.close()
        return None

    # User answers
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

    correct = sum(
        1 for q, a in correct_map.items()
        if answers.get(q) == a
    )

    total = len(correct_map)
    score = round((correct / total) * 100, 2)

    save_test_score(
        token=token,
        test_id=test_id,
        user_id=user_id,
        total_questions=total,
        correct_answers=correct,
        score=score,
        max_score=100,
    )

    conn.close()

    return {
        "test_id": test_id,
        "user_id": user_id,
        "total": total,
        "correct": correct,
        "score": score,
        "max": 100,
        "time_left": None,
        "auto_finished": None,
    }


def _format_done_time(time_left: int, time_limit_min: int) -> str:
    done = max(0, (time_limit_min * 60) - time_left)
    m, s = divmod(done, 60)
    return f"{m:02d}:{s:02d}"


# ---------- command ----------

def result_command(update: Update, context: CallbackContext):
    message = update.message
    user_id = message.from_user.id
    args = context.args

    time_text = ""

    # ---------- CASE 1: /result <TOKEN> (ADMIN ONLY) ----------
    if args:
        if not _is_admin(user_id):
            message.reply_text("⛔ This command is for admins only.")
            return

        token = args[0].strip().upper()
        row = get_test_score(token)

        if row:
            (
                _,
                test_id,
                uid,
                total,
                correct,
                score,
                max_score,
                finished_at,
                time_left,
                auto_finished,
            ) = row + (None, None)
        else:
            data = _calculate_and_save_score(token, user_id)
            if not data:
                message.reply_text("❌ Result not found.\nCheck your token.")
                return

            test_id = data["test_id"]
            uid = data["user_id"]
            total = data["total"]
            correct = data["correct"]
            score = data["score"]
            max_score = data["max"]
            time_left = None
            auto_finished = None

    # ---------- CASE 2: /result (USER OWN RESULT) ----------
    else:
        row = _get_latest_score_by_user(user_id)
        if not row:
            message.reply_text("❌ You have no test results yet.")
            return

        (
            _,
            test_id,
            uid,
            total,
            correct,
            score,
            max_score,
            finished_at,
            time_left,
            auto_finished,
        ) = row + (None, None)

    # ---------- TIME DISPLAY ----------
    active = get_active_test()
    if active and time_left is not None:
        _, _, _, _, time_limit, _ = active

        if auto_finished:
            time_text = "\n⏱ Time: <b>auto-finished</b>"
        else:
            time_text = f"\n⏱ Time: <b>{_format_done_time(time_left, time_limit)}</b>"
    else:
        time_text = "\n⏱ Time: <i>no data</i>"

    # ---------- RESPONSE ----------
    message.reply_text(
        "📊 <b>Test Result</b>\n\n"
        f"🧮 Questions: {total}\n"
        f"✅ Correct: {correct}\n"
        f"🎯 Score: <b>{score} / {max_score}</b>"
        f"{time_text}",
        parse_mode="HTML",
    )


# ---------- setup ----------

def setup(dispatcher, bot=None):
    dispatcher.add_handler(CommandHandler("result", result_command))
    logger.info("Feature loaded: result")
