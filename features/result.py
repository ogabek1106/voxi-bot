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


def _safe_time_fields(row):
    time_left = None
    auto_finished = None
    if row and len(row) >= 10:
        time_left = row[8]
        auto_finished = row[9]
    return time_left, auto_finished


def _is_test_program_ended() -> bool:
    """
    Returns True ONLY after admin runs /end_test_prog
    Fails safely if table or row does not exist.
    """
    try:
        conn = _connect()
        cur = conn.execute(
            "SELECT ended FROM test_program ORDER BY id DESC LIMIT 1;"
        )
        row = cur.fetchone()
        conn.close()
        return bool(row and row[0])
    except Exception:
        return False


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
    active = get_active_test()
    if not active:
        return None

    test_id, _, _, _, time_limit, _ = active

    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        "SELECT question_number, correct_answer FROM test_questions WHERE test_id = ?;",
        (test_id,),
    )
    correct_map = dict(cur.fetchall())
    if not correct_map:
        conn.close()
        return None

    cur.execute(
        "SELECT question_number, selected_answer FROM test_answers WHERE token = ?;",
        (token,),
    )
    answers = dict(cur.fetchall())
    if not answers:
        conn.close()
        return None

    correct = sum(1 for q, a in correct_map.items() if answers.get(q) == a)
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
        "total": total,
        "correct": correct,
        "score": score,
        "max": 100,
    }


def _format_done_time(time_left: int, time_limit_min: int) -> str:
    done = max(0, (time_limit_min * 60) - time_left)
    m, s = divmod(done, 60)
    return f"{m:02d}:{s:02d}"


def _build_detailed_review(token: str, test_id: int) -> str:
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT question_number, question_text, a, b, c, d, correct_answer
        FROM test_questions
        WHERE test_id = ?
        ORDER BY question_number;
        """,
        (test_id,),
    )
    questions = cur.fetchall()

    cur.execute(
        "SELECT question_number, selected_answer FROM test_answers WHERE token = ?;",
        (token,),
    )
    user_answers = dict(cur.fetchall())

    conn.close()

    lines = [
        "\n\n✅/✅ — correct choice",
        "❌ — wrong choice\n"
    ]

    for qn, text, a, b, c, d, correct in questions:
        chosen = user_answers.get(qn)
        lines.append(f"{qn}. {text}")

        for opt, val in zip(["a", "b", "c", "d"], [a, b, c, d]):
            mark = ""
            if chosen == opt and opt == correct:
                mark = " ✅/✅"
            elif chosen == opt and opt != correct:
                mark = " ❌"
            elif chosen != opt and opt == correct:
                mark = " ✅"

            lines.append(f"{opt}) {val}{mark}")

        lines.append("")

    return "\n".join(lines)


# ---------- command ----------

def result_command(update: Update, context: CallbackContext):
    message = update.message
    user_id = message.from_user.id
    args = context.args

    # ---------- FETCH RESULT ----------
    if args:
        if not _is_admin(user_id):
            message.reply_text("⛔ This command is for admins only.")
            return

        token = args[0].strip().upper()
        row = get_test_score(token)
        if not row:
            data = _calculate_and_save_score(token, user_id)
            if not data:
                message.reply_text("❌ Result not found.")
                return
            row = get_test_score(token)

    else:
        row = _get_latest_score_by_user(user_id)
        if not row:
            message.reply_text("❌ You have no test results yet.")
            return
        token = row[0]

    (
        _,
        test_id,
        _,
        total,
        correct,
        score,
        max_score,
        _,
        *_
    ) = row

    time_left, auto_finished = _safe_time_fields(row)

    active = get_active_test()
    if active and time_left is not None:
        _, _, _, _, time_limit, _ = active
        time_text = (
            "\n⏱ Time: <b>auto-finished</b>"
            if auto_finished
            else f"\n⏱ Time: <b>{_format_done_time(time_left, time_limit)}</b>"
        )
    else:
        time_text = "\n⏱ Time: <i>no data</i>"

    # ---------- BASE RESULT ----------
    text = (
        "📊 <b>Test Result</b>\n\n"
        f"🧮 Questions: {total}\n"
        f"✅ Correct: {correct}\n"
        f"🎯 Score: <b>{score} / {max_score}</b>"
        f"{time_text}"
    )

    # ---------- DETAILS GATE ----------
    if not _is_test_program_ended():
        text += "\n\n<i>Batafsil test tugagach bilishingiz mumkin</i>"
    else:
        text += _build_detailed_review(token, test_id)

    message.reply_text(text, parse_mode="HTML")


# ---------- setup ----------

def setup(dispatcher, bot=None):
    dispatcher.add_handler(CommandHandler("result", result_command))
    logger.info("Feature loaded: result")
