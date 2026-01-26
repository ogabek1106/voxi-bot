# features/top_results.py
"""
Admin-only command: /top_results

Shows:
- Total participants
- Average score
- Average time spent
- Top 8 participants ranked by:
    1) score DESC
    2) time_left DESC (faster)
    3) finished_at ASC
"""

import logging
import os
import sqlite3
from datetime import timedelta
from database import get_checker_mode
from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

import admins
from database import get_active_test

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "/data/data.db"))
SQLITE_TIMEOUT = 5


# ---------- helpers ----------

def _connect():
    return sqlite3.connect(
        DB_PATH,
        timeout=SQLITE_TIMEOUT,
        check_same_thread=False,
    )


def _is_admin(user_id: int) -> bool:
    raw = getattr(admins, "ADMIN_IDS", []) or []
    return int(user_id) in {int(x) for x in raw}


def _format_seconds(seconds: float) -> str:
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"


# ---------- command ----------

def top_results_command(update: Update, context: CallbackContext):
    message = update.message
    user_id = message.from_user.id

    # 🚫 FREE STATE ONLY
    if get_checker_mode(user_id) is not None:
        return

    if not _is_admin(user_id):
        message.reply_text("⛔ This command is for admins only.")
        return


    active = get_active_test()
    if not active:
        message.reply_text("❌ No active test.")
        return

    test_id, _, _, _, time_limit_min, _ = active
    total_seconds = time_limit_min * 60

    conn = _connect()
    cur = conn.cursor()

    # ---------- TOTAL PARTICIPANTS ----------
    cur.execute(
        """
        SELECT COUNT(DISTINCT user_id)
        FROM test_scores
        WHERE test_id = ?;
        """,
        (test_id,),
    )
    total_participants = cur.fetchone()[0] or 0

    if total_participants == 0:
        conn.close()
        message.reply_text("📊 No results yet.")
        return

    # ---------- AVERAGE SCORE ----------
    cur.execute(
        """
        SELECT AVG(score)
        FROM test_scores
        WHERE test_id = ?;
        """,
        (test_id,),
    )
    avg_score = cur.fetchone()[0] or 0
    avg_score = round(avg_score, 1)

    # ---------- AVERAGE TIME SPENT ----------
    cur.execute(
        """
        SELECT AVG(? - time_left)
        FROM test_scores
        WHERE test_id = ?
          AND time_left IS NOT NULL;
        """,
        (total_seconds, test_id),
    )
    avg_time_spent = cur.fetchone()[0] or 0
    avg_time_spent_text = _format_seconds(avg_time_spent)

    # ---------- TOP 8 PARTICIPANTS ----------
    cur.execute(
        """
        SELECT
            user_id,
            score,
            time_left
        FROM test_scores
        WHERE test_id = ?
        ORDER BY
            score DESC,
            time_left DESC,
            finished_at ASC
        LIMIT 8;
        """,
        (test_id,),
    )
    top_rows = cur.fetchall()

    conn.close()

    # ---------- BUILD MESSAGE ----------
    lines = [
        "🏆 <b>Top Results</b>\n",
        f"👥 Total participants: <b>{total_participants}</b>",
        f"📊 Average score: <b>{avg_score}</b>",
        f"⏱ Average time spent: <b>{avg_time_spent_text}</b>\n",
        "<b>🏅 Top 8 participants:</b>",
    ]

    medals = ["🥇", "🥈", "🥉"]

    for i, (uid, score, time_left) in enumerate(top_rows, start=1):
        medal = medals[i - 1] if i <= 3 else f"#{i}"
        time_spent = total_seconds - (time_left or 0)
        lines.append(
            f"{medal} <code>{uid}</code>\n"
            f"Score: <b>{score}</b> | Time: <b>{_format_seconds(time_spent)}</b>"
        )

    message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
    )


# ---------- setup ----------

def setup(dispatcher, bot=None):
    dispatcher.add_handler(CommandHandler("top_results", top_results_command))
    logger.info("Feature loaded: top_results")
