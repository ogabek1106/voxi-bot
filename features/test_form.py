# features/test_form.py
"""
Test form integration feature.

Flow:
 - User -> /get_test
    -> server generates token (or reuses unused), stores token,user_id,start_ts_human,form_url
    -> replies with button that opens FORM_PREFILL_URL with {token} and {start_ts} substituted
 - Admin -> /find_token <token>  (see token owner + status)
 - Admin -> /report <token> <score> [<submission_time>]
    -> marks completed, stores score + submission_ts, computes elapsed time vs stored start_ts (Moscow)
       If submission_time provided it's parsed (assumed Moscow) and used; otherwise current Moscow time used.
       The handler reports whether the submission was inside ALLOWED_MINUTES window.
       Admin may press inline button "Send reward message to user" to manually send reward.
"""

import logging
import os
import sqlite3
import time
import random
import string
from typing import Optional
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    HAVE_ZONEINFO = True
except Exception:
    ZoneInfo = None
    HAVE_ZONEINFO = False

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackContext, CommandHandler, CallbackQueryHandler

import admins

# try to reuse central database utilities if available (do not modify core files)
try:
    import database as core_database
except Exception:
    core_database = None

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "/data/data.db"))
FORM_PREFILL_URL = os.getenv("FORM_PREFILL_URL", "").strip()  # required to open prefilled form
REWARD_MESSAGE = os.getenv(
    "REWARD_MESSAGE",
    "Siz testa eng yuqori ballni qo'lga kiritdingiz! Yutuqni olish uchun @Ogabek1106 ga yozing!"
)
TOKEN_LENGTH = int(os.getenv("TOKEN_LENGTH", "8"))

# All times will be Moscow time
MOSCOW_TZ_NAME = "Europe/Moscow"

# Allowed minutes between start and submission (default 25)
ALLOWED_MINUTES = int(os.getenv("ALLOWED_MINUTES", "25"))
ALLOWED_SECONDS = ALLOWED_MINUTES * 60

# make sure DB folder exists (best-effort)
try:
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
except Exception:
    pass


def _connect():
    """
    Create a sqlite3 connection.

    Prefer to reuse core_database._connect() if available so both features
    use the same pragmas / timeout / DB path. Otherwise fall back to local connect.
    Caller must close the connection.
    """
    try:
        if core_database is not None:
            core_conn_fn = getattr(core_database, "_connect", None)
            if callable(core_conn_fn):
                return core_conn_fn()
    except Exception:
        logger.debug("Could not use core_database._connect(), falling back to local _connect()", exc_info=True)

    try:
        return sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    except Exception:
        logger.exception("Local sqlite3.connect failed; re-raising")
        raise


def _ensure_table():
    """
    Ensure users DB is prepared by core database utilities and ensure the
    local `tests` table exists (non-destructive). Try to add missing columns.
    """
    try:
        if core_database is not None:
            ensure_fn = getattr(core_database, "ensure_db", None)
            if callable(ensure_fn):
                ensure_fn()
    except Exception:
        logger.debug("core_database.ensure_db failed or not callable; continuing", exc_info=True)

    conn = _connect()
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tests (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    start_ts INTEGER NOT NULL,
                    start_ts_human TEXT,
                    form_url TEXT,
                    completed INTEGER DEFAULT 0,
                    score TEXT,
                    submission_ts INTEGER,
                    rewarded INTEGER DEFAULT 0
                );
                """
            )
        cur = conn.execute("PRAGMA table_info(tests);")
        cols = {r[1] for r in cur.fetchall()}
        needed = {
            "start_ts_human": "TEXT",
            "form_url": "TEXT",
            "rewarded": "INTEGER"
        }
        for col, ctype in needed.items():
            if col not in cols:
                try:
                    with conn:
                        conn.execute(f"ALTER TABLE tests ADD COLUMN {col} {ctype};")
                        logger.info("Added missing column %s to tests table", col)
                except Exception:
                    logger.exception("Failed adding column %s", col)
    except Exception:
        logger.exception("Failed to ensure tests table")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _is_admin(uid: int) -> bool:
    raw = getattr(admins, "ADMIN_IDS", None) or getattr(admins, "ADMINS", None) or []
    try:
        s = {int(x) for x in raw}
        return int(uid) in s
    except Exception:
        return False


def _gen_token(length: int = TOKEN_LENGTH) -> str:
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(10):
        t = "".join(random.choice(alphabet) for _ in range(length))
        if not _get_test_row(t):
            return t
    return f"T{int(time.time())}"


def _get_test_row(token: str) -> Optional[dict]:
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT token, user_id, start_ts, start_ts_human, form_url, completed, score, submission_ts, rewarded FROM tests WHERE token = ?;",
            (token,)
        )
        r = cur.fetchone()
        if not r:
            return None
        start_ts_val = r[2]
        try:
            start_ts_val = int(start_ts_val) if start_ts_val is not None else None
        except Exception:
            try:
                start_ts_val = int(float(start_ts_val))
            except Exception:
                start_ts_val = None

        rewarded_val = False
        try:
            rewarded_val = bool(r[8]) if len(r) > 8 else False
        except Exception:
            rewarded_val = False

        return {
            "token": r[0],
            "user_id": r[1],
            "start_ts": start_ts_val,
            "start_ts_human": r[3],
            "form_url": r[4],
            "completed": bool(r[5]),
            "score": r[6],
            "submission_ts": r[7],
            "rewarded": rewarded_val,
        }
    except Exception:
        logger.exception("Failed to read test row for %s", token)
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _find_unused_token_for_user(user_id: int) -> Optional[dict]:
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT token, user_id, start_ts, start_ts_human, form_url FROM tests WHERE user_id = ? AND completed = 0 LIMIT 1;",
            (int(user_id),)
        )
        r = cur.fetchone()
        if not r:
            return None
        start_ts_val = r[2]
        try:
            start_ts_val = int(start_ts_val) if start_ts_val is not None else None
        except Exception:
            try:
                start_ts_val = int(float(start_ts_val))
            except Exception:
                start_ts_val = None
        return {
            "token": r[0],
            "user_id": r[1],
            "start_ts": start_ts_val,
            "start_ts_human": r[3],
            "form_url": r[4],
        }
    except Exception:
        logger.exception("Failed to find unused token for %s", user_id)
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _insert_token(token: str, user_id: int, start_ts: int, start_human: str, form_url: str):
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO tests (token, user_id, start_ts, start_ts_human, form_url, completed, rewarded) VALUES (?, ?, ?, ?, ?, 0, 0);",
                (token, int(user_id), int(start_ts), start_human, form_url),
            )
    except Exception:
        logger.exception("Failed to insert token %s for user %s", token, user_id)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _mark_completed(token: str, score: str, submission_ts: Optional[int] = None):
    """
    Mark a token completed. If submission_ts provided, store it; otherwise set to current Moscow time.
    """
    conn = _connect()
    try:
        with conn:
            ts = int(submission_ts) if submission_ts is not None else int(_now_moscow().timestamp())
            conn.execute(
                "UPDATE tests SET completed = 1, score = ?, submission_ts = ? WHERE token = ?;",
                (str(score), ts, token),
            )
    except Exception:
        logger.exception("Failed to mark completed for %s", token)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _mark_rewarded(token: str):
    conn = _connect()
    try:
        with conn:
            conn.execute("UPDATE tests SET rewarded = 1 WHERE token = ?;", (token,))
    except Exception:
        logger.exception("Failed to mark rewarded for %s", token)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _build_prefill_url(token: str, start_human: str, user_id: int) -> str:
    """
    Replace placeholders {token}, {start_ts}, {user_id} in FORM_PREFILL_URL.
    Uses URL-encoding for inserted values.
    start_human here is intended to be MOSCOW human-readable time (for the form).
    """
    if not FORM_PREFILL_URL:
        return ""
    import urllib.parse
    t = urllib.parse.quote_plus(token)
    s = urllib.parse.quote_plus(start_human)
    u = urllib.parse.quote_plus(str(user_id))
    url = FORM_PREFILL_URL.replace("{token}", t).replace("{start_ts}", s).replace("{user_id}", u)
    return url


# --- handlers / time helpers ---


def _now_moscow() -> datetime:
    """
    Return timezone-aware current datetime in Moscow timezone.
    Falls back to UTC-aware now if zoneinfo not available (still labeled Moscow).
    """
    try:
        if HAVE_ZONEINFO and ZoneInfo is not None:
            return datetime.now(timezone.utc).astimezone(ZoneInfo(MOSCOW_TZ_NAME))
    except Exception:
        logger.debug("zoneinfo failed for %s; falling back to UTC", MOSCOW_TZ_NAME, exc_info=True)
    return datetime.now(timezone.utc)


def _format_moscow_short(dt: datetime) -> str:
    """
    Format Moscow datetime as: "hhmmss / ddmmyy (Moscow time)"
    Example: "163323 / 011225 (Moscow time)"
    """
    try:
        return dt.strftime("%H%M%S / %d%m%y") + " (Moscow time)"
    except Exception:
        # fallback simple
        return time.strftime("%H%M%S / %d%m%y", time.localtime()) + " (Moscow time)"


def _parse_moscow_time_to_epoch(value: str) -> Optional[int]:
    """
    Try to parse a submission time string (from Google Sheets or admin copy-paste)
    into an integer epoch (seconds). Assumes the given time is in Moscow time.

    Accepts:
      - pure digits epoch (e.g. "1764592123")
      - "HH:MM:SS DD.MM.YY" or "HH:MM:SS DD.MM.YYYY"
      - "YYYY-MM-DD HH:MM:SS" (common DB format)
      - "DD.MM.YYYY HH:MM:SS"
      - and several similar variants
    Returns epoch seconds (Moscow tz) or None on failure.
    """
    if not value:
        return None
    v = value.strip()
    # digits -> assume epoch seconds
    if v.isdigit():
        try:
            return int(v)
        except Exception:
            pass

    # try several datetime formats
    candidates = [
        "%H:%M:%S %d.%m.%y",
        "%H:%M:%S %d.%m.%Y",
        "%Y-%m-%d %H:%M:%S",
        "%d.%m.%Y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%d.%m.%y %H:%M:%S",
        "%H:%M:%S %d/%m/%Y",
        "%d-%m-%Y %H:%M:%S",
        "%d %b %Y %H:%M:%S",  # e.g. 02 Dec 2025 22:45:12
    ]
    for fmt in candidates:
        try:
            dt = datetime.strptime(v, fmt)
            # localize/interpret as MOSCOW time
            if HAVE_ZONEINFO and ZoneInfo is not None:
                moscow = ZoneInfo(MOSCOW_TZ_NAME)
                dt = dt.replace(tzinfo=moscow)
                return int(dt.timestamp())
            else:
                # Without zoneinfo we treat parsed time as UTC-equivalent (best-effort),
                # but log a warning.
                logger.warning("zoneinfo not available; parsed submission time as UTC fallback")
                dt = dt.replace(tzinfo=timezone.utc)
                return int(dt.timestamp())
        except Exception:
            continue

    # final attempt: try parsing ISO-like using fromisoformat
    try:
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            if HAVE_ZONEINFO and ZoneInfo is not None:
                dt = dt.replace(tzinfo=ZoneInfo(MOSCOW_TZ_NAME))
            else:
                dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        pass

    return None


def get_test_handler(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user:
        return

    _ensure_table()

    if not FORM_PREFILL_URL:
        update.message.reply_text("❌ Server is not configured for forms. Contact admin.")
        logger.warning("FORM_PREFILL_URL not set")
        return

    # If user already has an unused token (completed=0) reuse it
    existing = _find_unused_token_for_user(user.id)
    if existing:
        token = existing["token"]

        # Prefer stored start_ts_human if present (should be Moscow-format from previous runs)
        start_human = existing.get("start_ts_human")
        if not start_human:
            # try to derive from stored epoch (assume it is Moscow epoch)
            try:
                if existing.get("start_ts"):
                    if HAVE_ZONEINFO and ZoneInfo is not None:
                        moscow_dt = datetime.fromtimestamp(int(existing["start_ts"]), tz=ZoneInfo(MOSCOW_TZ_NAME))
                    else:
                        moscow_dt = datetime.fromtimestamp(int(existing["start_ts"]), tz=timezone.utc)
                    start_human = _format_moscow_short(moscow_dt)
            except Exception:
                start_human = None

        if not start_human:
            # final fallback: current Moscow time
            start_human = _format_moscow_short(_now_moscow())

        form_url = existing.get("form_url") or _build_prefill_url(token, start_human, user.id)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Open test (prefilled)", url=form_url)]])
        update.message.reply_text(
            f"🔐 You already have an active test token.\n\nToken: {token}\nStart (Moscow): {start_human}\n\nUse the button below to open the test.",
            reply_markup=kb
        )
        logger.info("Reused existing token for user %s: %s", user.id, token)
        return

    # create new token
    token = _gen_token()

    # compute Moscow time (for storing & prefill)
    moscow_dt = _now_moscow()

    # store epoch seconds from Moscow time (int)
    try:
        start_ts = int(moscow_dt.timestamp())
    except Exception:
        start_ts = int(time.time())

    # human-readable Moscow string in required short format
    moscow_human_short = _format_moscow_short(moscow_dt)

    # Build form URL with Moscow human time so form receives Moscow time
    form_url = _build_prefill_url(token, moscow_human_short, user.id)

    # debug log to confirm what we put into URL
    logger.info("test_form: built form_url=%s for token=%s (moscow=%s epoch=%s)", form_url, token, moscow_human_short, start_ts)

    # Insert token with start_ts (Moscow epoch) and visible human shown to user (Moscow)
    _insert_token(token, user.id, start_ts, moscow_human_short, form_url)

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Open test (prefilled)", url=form_url)]])
    update.message.reply_text(
        f"✅ Your token: {token}\nStart (Moscow): {moscow_human_short}\n\nClick the button below to open the test (fields should be prefilled).",
        reply_markup=kb
    )
    logger.info("Created new token for user %s: %s (moscow_ts=%s)", user.id, token, start_ts)


def find_token_handler(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        return

    args = context.args if getattr(context, "args", None) is not None else []
    if not args:
        update.message.reply_text("Usage: /find_token <TOKEN>")
        return
    token = args[0].strip()
    row = _get_test_row(token)
    if not row:
        update.message.reply_text(f"Token {token} not found.")
        return

    # Prefer stored human string (Moscow short); if missing try to derive from epoch
    start_h = row.get("start_ts_human")
    if not start_h:
        try:
            if row.get("start_ts"):
                moscow_dt = datetime.fromtimestamp(int(row["start_ts"]), tz=ZoneInfo(MOSCOW_TZ_NAME)) if HAVE_ZONEINFO else datetime.fromtimestamp(int(row["start_ts"]), tz=timezone.utc)
                start_h = _format_moscow_short(moscow_dt)
            else:
                start_h = _format_moscow_short(_now_moscow())
        except Exception:
            start_h = "(unknown)"

    txt = (
        f"Token: {row['token']}\n"
        f"User id: {row['user_id']}\n"
        f"Start (Moscow): {start_h}\n"
        f"Completed: {row['completed']}\n"
        f"Score: {row['score']}\n"
        f"Rewarded: {row.get('rewarded', False)}\n"
        f"Form URL: {row['form_url'] or '(none)'}"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✉️ Send reward message to user", callback_data=f"test_send:{token}")]])
    update.message.reply_text(txt, reply_markup=kb)


def report_handler(update: Update, context: CallbackContext):
    """Admin command: /report <TOKEN> <SCORE> [<SUBMISSION_TIME>]

    Submission time can be:
      - epoch seconds: 1764592123
      - Google Sheets string: "2025-12-02 22:45:12" or "22:45:12 02.12.2025" etc.
    If provided, we use it (interpreted as Moscow time) to compute elapsed time.
    """
    user = update.effective_user
    if not user or not _is_admin(user.id):
        return

    args = context.args if getattr(context, "args", None) is not None else []
    if len(args) < 2:
        update.message.reply_text("Usage: /report <TOKEN> <SCORE> [<SUBMISSION_TIME>]")
        return
    token = args[0].strip()
    # Score may contain spaces; treat second arg as score start and rest as possible submission time
    score = args[1].strip()
    submission_arg = None
    if len(args) >= 3:
        submission_arg = " ".join(args[2:]).strip()

    row = _get_test_row(token)
    if not row:
        update.message.reply_text(f"Token {token} not found.")
        return

    # Parse submission time (if provided) into epoch seconds (Moscow-based)
    submission_epoch = None
    if submission_arg:
        submission_epoch = _parse_moscow_time_to_epoch(submission_arg)
        if submission_epoch is None:
            update.message.reply_text("Could not parse submission time. Provide epoch or a known format (e.g. 'YYYY-MM-DD HH:MM:SS' or 'HH:MM:SS DD.MM.YYYY').")
            return
    else:
        # If admin didn't provide submission time, default to current Moscow time (less preferred)
        submission_epoch = int(_now_moscow().timestamp())
        logger.info("No submission time provided by admin; defaulting to current Moscow time %s", submission_epoch)

    # Compute start time: prefer stored epoch; if missing attempt to parse stored human string
    start_epoch = row.get("start_ts")
    if not start_epoch:
        # try parse start_ts_human (if exists)
        start_human = row.get("start_ts_human")
        if start_human:
            parsed = _parse_moscow_time_to_epoch(start_human)
            start_epoch = parsed
    if not start_epoch:
        update.message.reply_text("Start time for this token is not available; cannot compute duration.")
        return

    elapsed = int(submission_epoch) - int(start_epoch)
    elapsed_minutes = elapsed / 60.0

    ok = elapsed <= ALLOWED_SECONDS

    # Mark completed and store submission time
    _mark_completed(token, score, submission_epoch)

    report_text = (
        f"Report for {token}:\n"
        f"User id: {row['user_id']}\n"
        f"Start (Moscow epoch): {start_epoch}\n"
        f"Submission (Moscow epoch): {submission_epoch}\n"
        f"Elapsed: {elapsed} seconds ({elapsed_minutes:.1f} minutes)\n"
        f"Allowed: {ALLOWED_MINUTES} minutes\n"
        f"Within allowed window: {'✅ Yes' if ok else '❌ No'}\n"
        f"Score: {score}"
    )

    if not ok:
        report_text += "\n\nNote: submission exceeded allowed time — score recorded but reward not automatic."

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✉️ Send reward message to user", callback_data=f"test_send:{token}")]])
    update.message.reply_text(report_text, reply_markup=kb)


def callback_query_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    if not query:
        return
    user = query.from_user
    data = query.data or ""
    if not data.startswith("test_send:"):
        return
    token = data.split(":", 1)[1]
    if not _is_admin(user.id):
        try:
            query.answer("Unauthorized", show_alert=True)
        except Exception:
            pass
        return

    row = _get_test_row(token)
    if not row:
        try:
            query.answer("Token not found", show_alert=True)
        except Exception:
            pass
        return

    if row.get("rewarded"):
        try:
            query.answer("Already rewarded.", show_alert=True)
        except Exception:
            pass
        return

    try:
        context.bot.send_message(chat_id=row["user_id"], text=REWARD_MESSAGE)
        _mark_rewarded(token)
        try:
            query.answer("Reward message sent", show_alert=True)
            query.edit_message_text(f"Reward message sent to {row['user_id']} for token {token}.")
        except Exception:
            logger.exception("Failed to update callback message after sending reward")
    except Exception:
        logger.exception("Failed to send reward message to user %s for token %s", row["user_id"], token)
        try:
            query.answer("Failed to send message. Check logs.", show_alert=True)
        except Exception:
            pass


def setup(dispatcher):
    _ensure_table()
    dispatcher.add_handler(CommandHandler("get_test", get_test_handler))
    dispatcher.add_handler(CommandHandler("find_token", find_token_handler))
    dispatcher.add_handler(CommandHandler("report", report_handler))
    dispatcher.add_handler(CallbackQueryHandler(callback_query_handler))
    logger.info("test_form feature loaded. FORM_PREFILL_URL set? %s", bool(FORM_PREFILL_URL))
