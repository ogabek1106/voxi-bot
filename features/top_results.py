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

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from features.sub_check import is_subscribed
import admins
from database import (
    get_active_test,
    get_user_name,
    get_checker_mode,
    get_referral_stats,
    recheck_all_referrals,   
)

logger = logging.getLogger(__name__)
router = Router()

DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "/data/data.db"))
SQLITE_TIMEOUT = 5
SHOW_REFERRAL_BONUS = True  # 🔴 turn OFF bonus display for simple tests
BONUS_TIERS = {
    5: "2× bonus",
    10: "3× bonus",
}

# ─────────────────────────────
# Helpers
# ─────────────────────────────

def _connect():
    return sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT, check_same_thread=False)


def _is_admin(user_id: int) -> bool:
    raw = getattr(admins, "ADMIN_IDS", []) or []
    return int(user_id) in {int(x) for x in raw}


def _format_seconds(seconds: float) -> str:
    seconds = int(seconds or 0)
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"


# ─────────────────────────────
# /top_results (admin)
# ─────────────────────────────

@router.message(Command("top_results"))
async def top_results_handler(message: Message, state: FSMContext):
    user_id = message.from_user.id
    # 🔁 LIVE referral recheck for admin (keeps bonus truthful)
    await recheck_all_referrals(message.bot, user_id, is_subscribed)
    # 🚫 FSM guard
    if get_checker_mode(user_id) is not None:
        await message.answer("⚠️ Finish current operation before using /top_results.")
        return

    if not _is_admin(user_id):
        await message.answer("⛔ This command is for admins only.")
        return

    active = get_active_test()
    if not active:
        await message.answer("❌ No active test.")
        return

    test_id, _, _, _, time_limit_min, _ = active
    total_seconds = (time_limit_min or 0) * 60

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
        await message.answer("📊 No results yet.")
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
    avg_score = round((cur.fetchone()[0] or 0), 1)

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
        name = get_user_name(uid) or "—"
        medal = medals[i - 1] if i <= 3 else f"#{i}"
        time_spent = total_seconds - (time_left or 0)

        bonus_line = ""

        if SHOW_REFERRAL_BONUS:
            stats = get_referral_stats(uid) or {}
            confirmed = int(stats.get("confirmed", 0) or 0)

            # Determine bonus tier (based on BONUS_TIERS)
            bonus_line = None
            for threshold in sorted(BONUS_TIERS.keys(), reverse=True):
                if confirmed >= threshold:
                    bonus_line = f"🎉 {BONUS_TIERS[threshold]} unlocked ({threshold}+ referrals)"
                    break

            if not bonus_line:
                next_tier = min(BONUS_TIERS.keys())
                left = max(0, next_tier - confirmed)
                bonus_line = f"🎁 {left} more invites to unlock {BONUS_TIERS[next_tier]}"

        text = (
            f"{medal} <code>{uid}</code> — <b>{name}</b>\n"
            f"Score: <b>{score}</b> | Time: <b>{_format_seconds(time_spent)}</b>\n"
        )

        if SHOW_REFERRAL_BONUS:
            text += f"{bonus_line}\n"

        lines.append(text)

    await message.answer("\n".join(lines), parse_mode="HTML")
