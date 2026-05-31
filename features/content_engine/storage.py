import json
import logging
import os
import sqlite3
import time
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from database import _connect, _table_columns

logger = logging.getLogger(__name__)


def _now_ts() -> int:
    return int(time.time())


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _connect_rows():
    conn = _connect()
    conn.row_factory = sqlite3.Row
    return conn


def ensure_content_engine_tables() -> None:
    conn = None
    try:
        conn = _connect()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS content_engine_drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    draft_text TEXT NOT NULL,
                    generated_date TEXT NOT NULL,
                    weekday TEXT,
                    slot TEXT,
                    content_category TEXT,
                    source_resource_id INTEGER,
                    source_title TEXT,
                    status TEXT NOT NULL,
                    used_topic TEXT,
                    used_vocabulary TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS content_engine_resources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    category TEXT,
                    file_id TEXT,
                    file_unique_id TEXT,
                    file_name TEXT,
                    mime_type TEXT,
                    local_path TEXT,
                    extracted_text TEXT,
                    created_at INTEGER NOT NULL,
                    last_used_at INTEGER
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS content_engine_slots (
                    slot_date TEXT NOT NULL,
                    slot TEXT NOT NULL,
                    scheduled_time TEXT NOT NULL,
                    generated_draft_id INTEGER,
                    status TEXT NOT NULL DEFAULT 'scheduled',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (slot_date, slot)
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS content_engine_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at INTEGER NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS content_engine_channel_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    message_id INTEGER,
                    text TEXT,
                    received_at INTEGER NOT NULL,
                    UNIQUE(chat_id, message_id)
                );
                """
            )
    except Exception as e:
        logger.exception("ensure_content_engine_tables failed: %s", e)
    finally:
        if conn:
            conn.close()


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    ensure_content_engine_tables()
    conn = None
    try:
        conn = _connect()
        cur = conn.execute(
            "SELECT value FROM content_engine_settings WHERE key = ? LIMIT 1;",
            (key,),
        )
        row = cur.fetchone()
        return row[0] if row else default
    except Exception:
        logger.exception("get_setting failed for %s", key)
        return default
    finally:
        if conn:
            conn.close()


def set_setting(key: str, value: str) -> bool:
    ensure_content_engine_tables()
    conn = None
    try:
        conn = _connect()
        with conn:
            conn.execute(
                """
                INSERT INTO content_engine_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at;
                """,
                (key, value, _now_ts()),
            )
        return True
    except Exception:
        logger.exception("set_setting failed for %s", key)
        return False
    finally:
        if conn:
            conn.close()


def is_paused() -> bool:
    return get_setting("paused", "0") == "1"


def set_paused(paused: bool) -> bool:
    return set_setting("paused", "1" if paused else "0")


def upsert_daily_slots(slot_date: str, schedule: Dict[str, str]) -> None:
    ensure_content_engine_tables()
    conn = None
    now = _now_ts()
    try:
        conn = _connect()
        with conn:
            for slot, scheduled_time in schedule.items():
                conn.execute(
                    """
                    INSERT OR IGNORE INTO content_engine_slots
                    (slot_date, slot, scheduled_time, status, created_at, updated_at)
                    VALUES (?, ?, ?, 'scheduled', ?, ?);
                    """,
                    (slot_date, slot, scheduled_time, now, now),
                )
    except Exception:
        logger.exception("upsert_daily_slots failed")
    finally:
        if conn:
            conn.close()


def get_slots_for_date(slot_date: str) -> List[Dict[str, Any]]:
    ensure_content_engine_tables()
    conn = None
    try:
        conn = _connect_rows()
        cur = conn.execute(
            """
            SELECT slot_date, slot, scheduled_time, generated_draft_id, status
            FROM content_engine_slots
            WHERE slot_date = ?
            ORDER BY CASE slot
                WHEN 'morning' THEN 1
                WHEN 'afternoon' THEN 2
                WHEN 'evening' THEN 3
                ELSE 4
            END;
            """,
            (slot_date,),
        )
        return [_row_to_dict(row) for row in cur.fetchall()]
    except Exception:
        logger.exception("get_slots_for_date failed")
        return []
    finally:
        if conn:
            conn.close()


def mark_slot_generated(slot_date: str, slot: str, draft_id: int) -> None:
    ensure_content_engine_tables()
    conn = None
    try:
        conn = _connect()
        with conn:
            conn.execute(
                """
                UPDATE content_engine_slots
                SET generated_draft_id = ?, status = 'generated', updated_at = ?
                WHERE slot_date = ? AND slot = ?;
                """,
                (int(draft_id), _now_ts(), slot_date, slot),
            )
    except Exception:
        logger.exception("mark_slot_generated failed")
    finally:
        if conn:
            conn.close()


def create_draft(
    draft_text: str,
    generated_date: str,
    weekday: str,
    slot: str,
    content_category: str,
    source_resource_id: Optional[int] = None,
    source_title: Optional[str] = None,
    used_topic: Optional[str] = None,
    used_vocabulary: Optional[Iterable[str]] = None,
) -> Optional[int]:
    ensure_content_engine_tables()
    conn = None
    now = _now_ts()
    vocab = json.dumps(list(used_vocabulary or []), ensure_ascii=False)
    try:
        conn = _connect()
        with conn:
            cur = conn.execute(
                """
                INSERT INTO content_engine_drafts
                (draft_text, generated_date, weekday, slot, content_category,
                 source_resource_id, source_title, status, used_topic,
                 used_vocabulary, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending_review', ?, ?, ?, ?);
                """,
                (
                    draft_text,
                    generated_date,
                    weekday,
                    slot,
                    content_category,
                    source_resource_id,
                    source_title,
                    used_topic,
                    vocab,
                    now,
                    now,
                ),
            )
            return int(cur.lastrowid)
    except Exception:
        logger.exception("create_draft failed")
        return None
    finally:
        if conn:
            conn.close()


def update_draft_status(draft_id: int, status: str) -> bool:
    ensure_content_engine_tables()
    conn = None
    try:
        conn = _connect()
        with conn:
            cur = conn.execute(
                """
                UPDATE content_engine_drafts
                SET status = ?, updated_at = ?
                WHERE id = ?;
                """,
                (status, _now_ts(), int(draft_id)),
            )
        return cur.rowcount > 0
    except Exception:
        logger.exception("update_draft_status failed")
        return False
    finally:
        if conn:
            conn.close()


def get_draft(draft_id: int) -> Optional[Dict[str, Any]]:
    ensure_content_engine_tables()
    conn = None
    try:
        conn = _connect_rows()
        cur = conn.execute(
            "SELECT * FROM content_engine_drafts WHERE id = ? LIMIT 1;",
            (int(draft_id),),
        )
        row = cur.fetchone()
        return _row_to_dict(row) if row else None
    except Exception:
        logger.exception("get_draft failed")
        return None
    finally:
        if conn:
            conn.close()


def get_pending_drafts(limit: int = 10) -> List[Dict[str, Any]]:
    return list_drafts_by_status(["pending_review"], limit)


def list_drafts_by_status(statuses: List[str], limit: int = 10) -> List[Dict[str, Any]]:
    ensure_content_engine_tables()
    conn = None
    placeholders = ",".join("?" for _ in statuses)
    try:
        conn = _connect_rows()
        cur = conn.execute(
            f"""
            SELECT * FROM content_engine_drafts
            WHERE status IN ({placeholders})
            ORDER BY created_at DESC
            LIMIT ?;
            """,
            [*statuses, int(limit)],
        )
        return [_row_to_dict(row) for row in cur.fetchall()]
    except Exception:
        logger.exception("list_drafts_by_status failed")
        return []
    finally:
        if conn:
            conn.close()


def get_recent_drafts(limit: int = 20) -> List[Dict[str, Any]]:
    ensure_content_engine_tables()
    conn = None
    try:
        conn = _connect_rows()
        cur = conn.execute(
            """
            SELECT * FROM content_engine_drafts
            ORDER BY created_at DESC
            LIMIT ?;
            """,
            (int(limit),),
        )
        return [_row_to_dict(row) for row in cur.fetchall()]
    except Exception:
        logger.exception("get_recent_drafts failed")
        return []
    finally:
        if conn:
            conn.close()


def add_resource(
    title: str,
    category: str,
    file_id: str,
    file_unique_id: str,
    file_name: str,
    mime_type: str,
    local_path: str,
    extracted_text: str = "",
) -> Optional[int]:
    ensure_content_engine_tables()
    conn = None
    try:
        conn = _connect()
        with conn:
            cur = conn.execute(
                """
                INSERT INTO content_engine_resources
                (title, category, file_id, file_unique_id, file_name, mime_type,
                 local_path, extracted_text, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    title,
                    category,
                    file_id,
                    file_unique_id,
                    file_name,
                    mime_type,
                    local_path,
                    extracted_text,
                    _now_ts(),
                ),
            )
            return int(cur.lastrowid)
    except Exception:
        logger.exception("add_resource failed")
        return None
    finally:
        if conn:
            conn.close()


def list_resources(limit: int = 20) -> List[Dict[str, Any]]:
    ensure_content_engine_tables()
    conn = None
    try:
        conn = _connect_rows()
        cur = conn.execute(
            """
            SELECT * FROM content_engine_resources
            ORDER BY created_at DESC
            LIMIT ?;
            """,
            (int(limit),),
        )
        return [_row_to_dict(row) for row in cur.fetchall()]
    except Exception:
        logger.exception("list_resources failed")
        return []
    finally:
        if conn:
            conn.close()


def choose_resource() -> Optional[Dict[str, Any]]:
    ensure_content_engine_tables()
    conn = None
    try:
        conn = _connect_rows()
        cur = conn.execute(
            """
            SELECT * FROM content_engine_resources
            ORDER BY COALESCE(last_used_at, 0) ASC, created_at DESC
            LIMIT 1;
            """
        )
        row = cur.fetchone()
        return _row_to_dict(row) if row else None
    except Exception:
        logger.exception("choose_resource failed")
        return None
    finally:
        if conn:
            conn.close()


def mark_resource_used(resource_id: int) -> None:
    ensure_content_engine_tables()
    conn = None
    try:
        conn = _connect()
        with conn:
            conn.execute(
                "UPDATE content_engine_resources SET last_used_at = ? WHERE id = ?;",
                (_now_ts(), int(resource_id)),
            )
    except Exception:
        logger.exception("mark_resource_used failed")
    finally:
        if conn:
            conn.close()


def save_channel_post(chat_id: int, message_id: int, text: str) -> bool:
    ensure_content_engine_tables()
    if not text:
        return False
    conn = None
    try:
        conn = _connect()
        with conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO content_engine_channel_posts
                (chat_id, message_id, text, received_at)
                VALUES (?, ?, ?, ?);
                """,
                (int(chat_id), int(message_id), text[:4000], _now_ts()),
            )
        return True
    except Exception:
        logger.exception("save_channel_post failed")
        return False
    finally:
        if conn:
            conn.close()


def recent_channel_examples(limit: int = 5) -> List[str]:
    ensure_content_engine_tables()
    conn = None
    try:
        conn = _connect()
        cur = conn.execute(
            """
            SELECT text FROM content_engine_channel_posts
            ORDER BY received_at DESC
            LIMIT ?;
            """,
            (int(limit),),
        )
        return [row[0] for row in cur.fetchall() if row and row[0]]
    except Exception:
        logger.exception("recent_channel_examples failed")
        return []
    finally:
        if conn:
            conn.close()


ensure_content_engine_tables()
