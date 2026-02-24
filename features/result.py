# features/results.py
"""
Results & visibility control (Aiogram 3)

Commands:
/result
/result <TOKEN | USER_ID>   (admin only)
/open_results               (admin only)
/close_results              (admin only)

Rules:
- Works ONLY for last active test
- If no active test -> error
- Detailed results visible only when program is OPEN
"""

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

import admins
from database import (
    get_active_test,
    get_checker_mode,
    is_test_program_ended,
    end_test_program,
    clear_test_program_state,
    get_test_score,
    get_referral_stats,
)

import sqlite3
import os

logger = logging.getLogger(__name__)
router = Router()

DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "/data/data.db"))
SQLITE_TIMEOUT = 5
SHOW_REFERRAL_BONUS = False  # 🔴 OFF for simple tests (turn ON for MMT)
BONUS_TIERS = {
    5: "2× bonus",
    10: "3× bonus",
}
MAX_TELEGRAM_LEN = 4000  # keep margin for HTML tags

def _split_text_for_telegram(text: str, limit: int = MAX_TELEGRAM_LEN):
    chunks = []
    current = []

    size = 0
    for line in text.split("\n"):
        # +1 for newline
        line_len = len(line) + 1

        if size + line_len > limit:
            chunks.append("\n".join(current))
            current = [line]
            size = line_len
        else:
            current.append(line)
            size += line_len

    if current:
        chunks.append("\n".join(current))

    return chunks

# ─────────────────────────────
# Helpers (READ-ONLY SQL)
# ─────────────────────────────

def _is_admin(user_id: int) -> bool:
    raw = getattr(admins, "ADMIN_IDS", []) or []
    return int(user_id) in {int(x) for x in raw}


def _get_latest_score_for_user_in_active_test(user_id: int, test_id: str):
    conn = sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT, check_same_thread=False)
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
        WHERE user_id = ? AND test_id = ?
        ORDER BY finished_at DESC
        LIMIT 1;
        """,
        (int(user_id), str(test_id)),
    )
    row = cur.fetchone()
    conn.close()
    return row


def _get_latest_score_by_token(token: str, test_id: str):
    conn = sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT, check_same_thread=False)
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
        WHERE token = ? AND test_id = ?
        LIMIT 1;
        """,
        (token, str(test_id)),
    )
    row = cur.fetchone()
    conn.close()
    return row


def _get_latest_score_by_user_id(user_id: int, test_id: str):
    return _get_latest_score_for_user_in_active_test(user_id, test_id)


def _format_done_time(time_left: int, time_limit_min: int) -> str:
    done = max(0, (time_limit_min * 60) - (time_left or 0))
    m, s = divmod(done, 60)
    return f"{m:02d}:{s:02d}"


def _build_detailed_review(token: str, test_id: str) -> str:
    conn = sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT, check_same_thread=False)
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


# ─────────────────────────────
# /result
# ─────────────────────────────

@router.message(Command("result"))
async def result_handler(message: Message, state: FSMContext):
    user_id = message.from_user.id

    # FSM guard
    if get_checker_mode(user_id) is not None:
        await message.answer("⚠️ Finish current operation before using /result.")
        return

    active = get_active_test()
    if not active:
        await message.answer("❌ No active recent tests.")
        return

    test_id, _, _, _, time_limit, _ = active

    parts = message.text.split(maxsplit=1)
    arg = parts[1].strip() if len(parts) > 1 else None

    # ── ADMIN LOOKUP
    if arg:
        if not _is_admin(user_id):
            await message.answer("⛔ Admins only.")
            return

        if arg.isdigit():
            row = _get_latest_score_by_user_id(int(arg), test_id)
        else:
            row = _get_latest_score_by_token(arg.upper(), test_id)

        if not row:
            await message.answer("❌ Result not found for this user/token in active test.")
            return

    # ── USER SELF LOOKUP
    else:
        row = _get_latest_score_for_user_in_active_test(user_id, test_id)
        if not row:
            await message.answer("❌ You have no results for the active test.")
            return

    (
        token,
        _,
        target_user_id,
        total,
        correct,
        score,
        max_score,
        _,
        time_left,
        auto_finished,
    ) = row

    time_text = (
        "\n⏱ Time: <b>auto-finished</b>"
        if auto_finished
        else f"\n⏱ Time: <b>{_format_done_time(time_left, time_limit)}</b>"
    )

    text = (
        "📊 <b>Test Result</b>\n\n"
        f"👤 User ID: {target_user_id}\n"
        f"🧮 Questions: {total}\n"
        f"✅ Correct: {correct}\n"
        f"🎯 Score: <b>{score} / {max_score}</b>"
        f"{time_text}"
    )
    # ---- Bonus progress (optional) ----
    if SHOW_REFERRAL_BONUS:
        stats = get_referral_stats(target_user_id) or {}
        confirmed = int(stats.get("confirmed", 0) or 0)

        if confirmed >= 10:
            bonus_line = "🏆 3× bonus unlocked"
        elif confirmed >= 5:
            bonus_line = "✨ 2× bonus unlocked"
        else:
            left = max(0, 5 - confirmed)
            bonus_line = f"🎁 Bonus progress: <b>{left}</b> invites left for 2×"

        text += f"\n{bonus_line}"

    if is_test_program_ended():
        text += _build_detailed_review(token, test_id)
    else:
        text += "\n\n<i>Detailed results are currently closed.</i>"

    if len(text) <= MAX_TELEGRAM_LEN:
        await message.answer(text, parse_mode="HTML")
    else:
        parts = _split_text_for_telegram(text)
        for i, part in enumerate(parts, start=1):
            header = f"<b>📄 Results (part {i}/{len(parts)})</b>\n\n" if i > 1 else ""
            await message.answer(header + part, parse_mode="HTML")

# ─────────────────────────────
# /open_results (admin)
# ─────────────────────────────

@router.message(Command("open_results"))
async def open_results_handler(message: Message):
    if not _is_admin(message.from_user.id):
        await message.answer("⛔ Admins only.")
        return

    if end_test_program():
        await message.answer("✅ Detailed results are now OPEN for everyone.")
    else:
        await message.answer("❌ Failed to open results.")


# ─────────────────────────────
# /close_results (admin)
# ─────────────────────────────

@router.message(Command("close_results"))
async def close_results_handler(message: Message):
    if not _is_admin(message.from_user.id):
        await message.answer("⛔ Admins only.")
        return

    if clear_test_program_state():
        await message.answer("🔒 Detailed results are now CLOSED.")
    else:
        await message.answer("❌ Failed to close results.")
