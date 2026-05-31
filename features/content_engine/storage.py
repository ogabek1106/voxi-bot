import json
import logging
import os
import sqlite3
import time
from typing import Any, Dict, Iterable, List, Optional

from database import _connect

from .style_analysis import analyze_style

logger = logging.getLogger(__name__)


def _now_ts() -> int:
    return int(time.time())


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _connect_rows():
    conn = _connect()
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    try:
        cur = conn.execute(f"PRAGMA table_info({table});")
        return [row[1] for row in cur.fetchall()]
    except Exception:
        logger.exception("Could not read columns for %s", table)
        return []


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: Dict[str, str]) -> None:
    existing = set(_table_columns(conn, table))
    for name, ddl in columns.items():
        if name not in existing:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl};")
            except Exception:
                logger.exception("Could not add column %s.%s", table, name)


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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS content_engine_resource_ideas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    resource_id INTEGER NOT NULL,
                    idea_type TEXT,
                    title TEXT NOT NULL,
                    content TEXT,
                    source_excerpt TEXT,
                    page_start INTEGER,
                    page_end INTEGER,
                    used_count INTEGER NOT NULL DEFAULT 0,
                    last_used INTEGER,
                    created_at INTEGER NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS content_engine_style_examples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'General',
                    source TEXT NOT NULL DEFAULT 'manual_admin_example',
                    created_at INTEGER NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS content_engine_hashtags (
                    category TEXT NOT NULL,
                    hashtag TEXT NOT NULL,
                    source TEXT NOT NULL,
                    use_count INTEGER NOT NULL DEFAULT 1,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (category, hashtag)
                );
                """
            )
            _ensure_columns(
                conn,
                "content_engine_drafts",
                {
                    "topic": "TEXT",
                    "source_chunk_id": "TEXT",
                    "generation_prompt": "TEXT",
                    "style_examples_used": "TEXT",
                    "hashtags_used": "TEXT",
                },
            )
            _ensure_columns(
                conn,
                "content_engine_resources",
                {
                    "status": "TEXT DEFAULT 'uploaded'",
                    "processed_at": "INTEGER",
                    "processing_error": "TEXT",
                    "source_type": "TEXT",
                    "book_code": "TEXT",
                    "source_caption": "TEXT",
                },
            )
            _ensure_columns(
                conn,
                "content_engine_style_examples",
                {
                    "original_draft": "TEXT",
                    "hashtags": "TEXT",
                    "emoji_count": "INTEGER DEFAULT 0",
                    "bold_count": "INTEGER DEFAULT 0",
                    "italic_count": "INTEGER DEFAULT 0",
                    "formatting_pattern": "TEXT",
                    "footer_pattern": "TEXT",
                    "cta_pattern": "TEXT",
                    "language_ratio": "TEXT",
                },
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
    topic: Optional[str] = None,
    source_chunk_id: Optional[str] = None,
    generation_prompt: Optional[str] = None,
    style_examples_used: Optional[Iterable[int]] = None,
    hashtags_used: Optional[Iterable[str]] = None,
) -> Optional[int]:
    ensure_content_engine_tables()
    conn = None
    now = _now_ts()
    vocab = json.dumps(list(used_vocabulary or []), ensure_ascii=False)
    style_ids = json.dumps(list(style_examples_used or []), ensure_ascii=False)
    hashtags = json.dumps(list(hashtags_used or []), ensure_ascii=False)
    try:
        conn = _connect()
        with conn:
            cur = conn.execute(
                """
                INSERT INTO content_engine_drafts
                (draft_text, generated_date, weekday, slot, content_category,
                 source_resource_id, source_title, status, used_topic,
                 used_vocabulary, topic, source_chunk_id, generation_prompt,
                 style_examples_used, hashtags_used, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending_review', ?, ?, ?, ?, ?, ?, ?, ?, ?);
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
                    topic or used_topic,
                    source_chunk_id,
                    generation_prompt,
                    style_ids,
                    hashtags,
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


def get_resource(resource_id: int) -> Optional[Dict[str, Any]]:
    ensure_content_engine_tables()
    conn = None
    try:
        conn = _connect_rows()
        cur = conn.execute(
            "SELECT * FROM content_engine_resources WHERE id = ? LIMIT 1;",
            (int(resource_id),),
        )
        row = cur.fetchone()
        return _row_to_dict(row) if row else None
    except Exception:
        logger.exception("get_resource failed")
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
    source_type: str = "",
    book_code: str = "",
    source_caption: str = "",
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
                 local_path, extracted_text, status, source_type, book_code,
                 source_caption, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'uploaded', ?, ?, ?, ?);
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
                    source_type,
                    book_code,
                    source_caption,
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


def get_existing_book_resource(book_code: str) -> Optional[Dict[str, Any]]:
    ensure_content_engine_tables()
    conn = None
    try:
        conn = _connect_rows()
        cur = conn.execute(
            """
            SELECT *
            FROM content_engine_resources
            WHERE source_type = 'existing_book' AND book_code = ?
            LIMIT 1;
            """,
            (str(book_code),),
        )
        row = cur.fetchone()
        return _row_to_dict(row) if row else None
    except Exception:
        logger.exception("get_existing_book_resource failed")
        return None
    finally:
        if conn:
            conn.close()


def update_resource_file(
    resource_id: int,
    local_path: str,
    mime_type: str = "",
    file_name: str = "",
) -> bool:
    ensure_content_engine_tables()
    conn = None
    try:
        conn = _connect()
        with conn:
            cur = conn.execute(
                """
                UPDATE content_engine_resources
                SET local_path = ?,
                    mime_type = COALESCE(NULLIF(?, ''), mime_type),
                    file_name = COALESCE(NULLIF(?, ''), file_name),
                    processing_error = NULL
                WHERE id = ?;
                """,
                (local_path, mime_type, file_name, int(resource_id)),
            )
        return cur.rowcount > 0
    except Exception:
        logger.exception("update_resource_file failed")
        return False
    finally:
        if conn:
            conn.close()


def reset_failed_book_resource(resource_id: int, clear_local_path: bool = False) -> bool:
    ensure_content_engine_tables()
    conn = None
    try:
        conn = _connect()
        with conn:
            if clear_local_path:
                cur = conn.execute(
                    """
                    UPDATE content_engine_resources
                    SET status = 'uploaded',
                        processing_error = NULL,
                        processed_at = NULL,
                        local_path = ''
                    WHERE id = ? AND source_type = 'existing_book';
                    """,
                    (int(resource_id),),
                )
            else:
                cur = conn.execute(
                    """
                    UPDATE content_engine_resources
                    SET status = 'uploaded',
                        processing_error = NULL,
                        processed_at = NULL
                    WHERE id = ? AND source_type = 'existing_book';
                    """,
                    (int(resource_id),),
                )
        return cur.rowcount > 0
    except Exception:
        logger.exception("reset_failed_book_resource failed")
        return False
    finally:
        if conn:
            conn.close()


def list_existing_book_resources_with_idea_counts(limit: int = 100) -> List[Dict[str, Any]]:
    ensure_content_engine_tables()
    conn = None
    try:
        conn = _connect_rows()
        cur = conn.execute(
            """
            SELECT r.*, COUNT(i.id) AS idea_count
            FROM content_engine_resources r
            LEFT JOIN content_engine_resource_ideas i ON i.resource_id = r.id
            WHERE r.source_type = 'existing_book'
            GROUP BY r.id
            ORDER BY CAST(r.book_code AS INTEGER), r.book_code
            LIMIT ?;
            """,
            (int(limit),),
        )
        return [_row_to_dict(row) for row in cur.fetchall()]
    except Exception:
        logger.exception("list_existing_book_resources_with_idea_counts failed")
        return []
    finally:
        if conn:
            conn.close()


def list_resources_with_idea_counts(limit: int = 20) -> List[Dict[str, Any]]:
    ensure_content_engine_tables()
    conn = None
    try:
        conn = _connect_rows()
        cur = conn.execute(
            """
            SELECT r.*, COUNT(i.id) AS idea_count
            FROM content_engine_resources r
            LEFT JOIN content_engine_resource_ideas i ON i.resource_id = r.id
            GROUP BY r.id
            ORDER BY r.created_at DESC
            LIMIT ?;
            """,
            (int(limit),),
        )
        return [_row_to_dict(row) for row in cur.fetchall()]
    except Exception:
        logger.exception("list_resources_with_idea_counts failed")
        return []
    finally:
        if conn:
            conn.close()


def list_resources_by_status(statuses: List[str], limit: int = 50) -> List[Dict[str, Any]]:
    ensure_content_engine_tables()
    if not statuses:
        return []
    placeholders = ",".join("?" for _ in statuses)
    conn = None
    try:
        conn = _connect_rows()
        cur = conn.execute(
            f"""
            SELECT *
            FROM content_engine_resources
            WHERE status IN ({placeholders})
            ORDER BY created_at ASC
            LIMIT ?;
            """,
            [*statuses, int(limit)],
        )
        return [_row_to_dict(row) for row in cur.fetchall()]
    except Exception:
        logger.exception("list_resources_by_status failed")
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


def update_resource_status(resource_id: int, status: str, error: Optional[str] = None) -> bool:
    ensure_content_engine_tables()
    conn = None
    try:
        conn = _connect()
        processed_at = _now_ts() if status in {"ready", "failed"} else None
        with conn:
            cur = conn.execute(
                """
                UPDATE content_engine_resources
                SET status = ?,
                    processed_at = COALESCE(?, processed_at),
                    processing_error = ?
                WHERE id = ?;
                """,
                (status, processed_at, error, int(resource_id)),
            )
        return cur.rowcount > 0
    except Exception:
        logger.exception("update_resource_status failed")
        return False
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


def add_resource_idea(
    resource_id: int,
    idea_type: str,
    title: str,
    content: str,
    source_excerpt: str,
    page_start: Optional[int] = None,
    page_end: Optional[int] = None,
) -> Optional[int]:
    ensure_content_engine_tables()
    if not title:
        return None
    conn = None
    try:
        conn = _connect()
        with conn:
            cur = conn.execute(
                """
                INSERT INTO content_engine_resource_ideas
                (resource_id, idea_type, title, content, source_excerpt,
                 page_start, page_end, used_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?);
                """,
                (
                    int(resource_id),
                    idea_type or "resource_tip",
                    title[:240],
                    (content or "")[:3000],
                    (source_excerpt or "")[:2000],
                    page_start,
                    page_end,
                    _now_ts(),
                ),
            )
            return int(cur.lastrowid)
    except Exception:
        logger.exception("add_resource_idea failed")
        return None
    finally:
        if conn:
            conn.close()


def count_resource_ideas(resource_id: int) -> int:
    ensure_content_engine_tables()
    conn = None
    try:
        conn = _connect()
        cur = conn.execute(
            "SELECT COUNT(*) FROM content_engine_resource_ideas WHERE resource_id = ?;",
            (int(resource_id),),
        )
        row = cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        logger.exception("count_resource_ideas failed")
        return 0
    finally:
        if conn:
            conn.close()


def choose_resource_idea(style_category: str = "General") -> Optional[Dict[str, Any]]:
    ensure_content_engine_tables()
    type_map = {
        "Word of the Day": ["word"],
        "Phrase": ["phrase", "phrasal_verb", "academic_phrase"],
        "Grammar Tip": ["grammar_tip", "common_mistake"],
        "Collocations": ["collocation"],
        "Resource": ["resource_tip", "ielts_verb"],
        "Quiz/Poll": ["common_mistake", "resource_tip"],
        "Quote/Music": ["quote"],
        "Mistakes": ["common_mistake"],
    }
    wanted = type_map.get(style_category, [])
    conn = None
    try:
        conn = _connect_rows()
        params = []
        where = "r.status = 'ready'"
        if wanted:
            placeholders = ",".join("?" for _ in wanted)
            where += f" AND i.idea_type IN ({placeholders})"
            params.extend(wanted)
        cur = conn.execute(
            f"""
            SELECT i.*, r.title AS resource_title, r.category AS resource_category
            FROM content_engine_resource_ideas i
            JOIN content_engine_resources r ON r.id = i.resource_id
            WHERE {where}
            ORDER BY i.used_count ASC, COALESCE(i.last_used, 0) ASC, i.created_at ASC
            LIMIT 1;
            """,
            params,
        )
        row = cur.fetchone()
        if row:
            return _row_to_dict(row)
        if wanted:
            cur = conn.execute(
                """
                SELECT i.*, r.title AS resource_title, r.category AS resource_category
                FROM content_engine_resource_ideas i
                JOIN content_engine_resources r ON r.id = i.resource_id
                WHERE r.status = 'ready'
                ORDER BY i.used_count ASC, COALESCE(i.last_used, 0) ASC, i.created_at ASC
                LIMIT 1;
                """
            )
            row = cur.fetchone()
            return _row_to_dict(row) if row else None
        return None
    except Exception:
        logger.exception("choose_resource_idea failed")
        return None
    finally:
        if conn:
            conn.close()


def mark_resource_idea_used(idea_id: int) -> None:
    ensure_content_engine_tables()
    conn = None
    try:
        conn = _connect()
        with conn:
            conn.execute(
                """
                UPDATE content_engine_resource_ideas
                SET used_count = used_count + 1, last_used = ?
                WHERE id = ?;
                """,
                (_now_ts(), int(idea_id)),
            )
    except Exception:
        logger.exception("mark_resource_idea_used failed")
    finally:
        if conn:
            conn.close()


def _learn_hashtags(category: str, hashtags: Iterable[str], source: str) -> None:
    tags = list(hashtags or [])
    if not tags:
        return
    conn = None
    try:
        conn = _connect()
        now = _now_ts()
        with conn:
            for tag in tags:
                conn.execute(
                    """
                    INSERT INTO content_engine_hashtags
                    (category, hashtag, source, use_count, updated_at)
                    VALUES (?, ?, ?, 1, ?)
                    ON CONFLICT(category, hashtag) DO UPDATE SET
                        use_count = content_engine_hashtags.use_count + 1,
                        updated_at = excluded.updated_at;
                    """,
                    (category or "General", tag, source, now),
                )
    except Exception:
        logger.exception("_learn_hashtags failed")
    finally:
        if conn:
            conn.close()


def get_learned_hashtags(category: str, limit: int = 12) -> List[str]:
    ensure_content_engine_tables()
    conn = None
    try:
        conn = _connect()
        tags = []
        for wanted in (category or "General", "General"):
            if len(tags) >= limit:
                break
            cur = conn.execute(
                """
                SELECT hashtag
                FROM content_engine_hashtags
                WHERE lower(category) = lower(?)
                ORDER BY use_count DESC, updated_at DESC
                LIMIT ?;
                """,
                (wanted, int(limit - len(tags))),
            )
            for row in cur.fetchall():
                tag = row[0]
                if tag not in tags:
                    tags.append(tag)
        return tags[:limit]
    except Exception:
        logger.exception("get_learned_hashtags failed")
        return []
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
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO content_engine_channel_posts
                (chat_id, message_id, text, received_at)
                VALUES (?, ?, ?, ?);
                """,
                (int(chat_id), int(message_id), text[:4000], _now_ts()),
            )
        if cur.rowcount:
            add_style_example(
                text=text,
                category="General",
                source="captured_channel_post",
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


def add_style_example(
    text: str,
    category: str = "General",
    source: str = "manual_admin_example",
    original_draft: Optional[str] = None,
) -> Optional[int]:
    ensure_content_engine_tables()
    if not text or not text.strip():
        return None
    conn = None
    metadata = analyze_style(text)
    hashtags = metadata["hashtags"]
    try:
        conn = _connect()
        with conn:
            cur = conn.execute(
                """
                INSERT INTO content_engine_style_examples
                (text, category, source, created_at, original_draft,
                 hashtags, emoji_count, bold_count, italic_count,
                 formatting_pattern, footer_pattern, cta_pattern, language_ratio)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    text.strip()[:4000],
                    category or "General",
                    source,
                    _now_ts(),
                    original_draft,
                    json.dumps(hashtags, ensure_ascii=False),
                    int(metadata["emoji_count"]),
                    int(metadata["bold_count"]),
                    int(metadata["italic_count"]),
                    metadata["formatting_pattern"],
                    metadata["footer_pattern"],
                    metadata["cta_pattern"],
                    metadata["language_ratio"],
                ),
            )
            example_id = int(cur.lastrowid)
        _learn_hashtags(category or "General", hashtags, source)
        return example_id
    except Exception:
        logger.exception("add_style_example failed")
        return None
    finally:
        if conn:
            conn.close()


def list_style_examples(limit: int = 20) -> List[Dict[str, Any]]:
    ensure_content_engine_tables()
    conn = None
    try:
        conn = _connect_rows()
        cur = conn.execute(
            """
            SELECT id, text, category, source, created_at, hashtags,
                   emoji_count, bold_count, italic_count, formatting_pattern,
                   footer_pattern, cta_pattern, language_ratio, original_draft
            FROM content_engine_style_examples
            ORDER BY created_at DESC
            LIMIT ?;
            """,
            (int(limit),),
        )
        return [_row_to_dict(row) for row in cur.fetchall()]
    except Exception:
        logger.exception("list_style_examples failed")
        return []
    finally:
        if conn:
            conn.close()


def delete_style_example(example_id: int) -> bool:
    ensure_content_engine_tables()
    conn = None
    try:
        conn = _connect()
        with conn:
            cur = conn.execute(
                "DELETE FROM content_engine_style_examples WHERE id = ?;",
                (int(example_id),),
            )
        deleted = cur.rowcount > 0
        if deleted:
            rebuild_learned_hashtags()
        return deleted
    except Exception:
        logger.exception("delete_style_example failed")
        return False
    finally:
        if conn:
            conn.close()


def rebuild_learned_hashtags() -> None:
    ensure_content_engine_tables()
    conn = None
    try:
        conn = _connect_rows()
        cur = conn.execute(
            """
            SELECT category, source, hashtags
            FROM content_engine_style_examples
            WHERE hashtags IS NOT NULL AND hashtags != '';
            """
        )
        rows = [_row_to_dict(row) for row in cur.fetchall()]
        with conn:
            conn.execute("DELETE FROM content_engine_hashtags;")
        for row in rows:
            try:
                hashtags = json.loads(row.get("hashtags") or "[]")
            except Exception:
                hashtags = []
            _learn_hashtags(row.get("category") or "General", hashtags, row.get("source") or "unknown")
    except Exception:
        logger.exception("rebuild_learned_hashtags failed")
    finally:
        if conn:
            conn.close()


def choose_style_examples(category: str, limit: int = 5) -> List[Dict[str, Any]]:
    ensure_content_engine_tables()
    wanted = (category or "General").strip() or "General"
    conn = None
    try:
        conn = _connect_rows()
        rows: List[Dict[str, Any]] = []
        seen = set()
        for wanted_category in (wanted, "General"):
            if len(rows) >= limit:
                break
            cur = conn.execute(
                """
                SELECT id, text, category, source, created_at,
                       hashtags, emoji_count, bold_count, italic_count,
                       formatting_pattern, footer_pattern, cta_pattern, language_ratio
                FROM content_engine_style_examples
                WHERE lower(category) = lower(?)
                ORDER BY created_at DESC
                LIMIT ?;
                """,
                (wanted_category, int(limit * 3)),
            )
            candidates = [_row_to_dict(row) for row in cur.fetchall()]
            source_rank = {
                "admin_edited_post": 0,
                "manual_admin_example": 1,
                "captured_channel_post": 2,
            }
            candidates.sort(
                key=lambda row: (
                    source_rank.get(row.get("source"), 9),
                    -int(row.get("created_at") or 0),
                )
            )
            for row in candidates:
                if row["id"] in seen:
                    continue
                seen.add(row["id"])
                rows.append(row)
                if len(rows) >= limit:
                    break
        return rows[:limit]
    except Exception:
        logger.exception("choose_style_examples failed")
        return []
    finally:
        if conn:
            conn.close()


ensure_content_engine_tables()
