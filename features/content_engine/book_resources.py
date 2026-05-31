import asyncio
import logging
import os
from pathlib import Path
from typing import Dict, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from books import BOOKS
from database import DB_PATH

from . import resource_processor, storage

logger = logging.getLogger(__name__)

_tasks: Dict[int, asyncio.Task] = {}
_all_books_task: Optional[asyncio.Task] = None


def _resource_dir() -> Path:
    base = os.getenv("CONTENT_RESOURCE_DIR")
    if base:
        path = Path(base)
    else:
        db_dir = Path(DB_PATH).parent if DB_PATH else Path(".")
        path = db_dir / "content_resources"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_file_name(name: str) -> str:
    safe = (name or "").strip().replace("\\", "_").replace("/", "_")
    safe = "".join(ch if ch.isalnum() or ch in "._- ()" else "_" for ch in safe)
    return safe.strip("._ ") or "book_resource.pdf"


def _book_title(book: Dict) -> str:
    return str(book.get("filename") or book.get("title") or "Untitled book").strip()


def _is_too_big_error(exc: Exception) -> bool:
    return "file is too big" in str(exc).lower()


def get_book(book_code: str) -> Optional[Dict]:
    return BOOKS.get(str(book_code).strip())


def import_book_record(book_code: str) -> tuple[Optional[int], bool, str]:
    code = str(book_code).strip()
    book = get_book(code)
    if not book:
        return None, False, "Book code not found."

    existing = storage.get_existing_book_resource(code)
    if existing:
        return int(existing["id"]), False, "Book resource already exists."

    title = _book_title(book)
    resource_id = storage.add_resource(
        title=title,
        category="existing_book",
        file_id=str(book.get("file_id") or ""),
        file_unique_id=f"book_{code}",
        file_name=title,
        mime_type="application/pdf" if title.lower().endswith(".pdf") else "",
        local_path="",
        extracted_text="",
        source_type="existing_book",
        book_code=code,
        source_caption=str(book.get("caption") or ""),
    )
    if not resource_id:
        return None, False, "Could not create resource record."
    return int(resource_id), True, "Book resource imported."


def start_book_processing(resource_id: int, bot: Bot) -> None:
    if resource_id in _tasks and not _tasks[resource_id].done():
        return
    _tasks[resource_id] = asyncio.create_task(_download_and_process(resource_id, bot))


def start_all_books_import(bot: Bot) -> tuple[int, int]:
    global _all_books_task
    imported = 0
    reused = 0
    resource_ids = []
    for code in BOOKS.keys():
        resource_id, created, _ = import_book_record(code)
        if not resource_id:
            continue
        resource_ids.append(resource_id)
        if created:
            imported += 1
        else:
            reused += 1

    if _all_books_task is None or _all_books_task.done():
        _all_books_task = asyncio.create_task(_process_many(resource_ids, bot))
    return imported, reused


async def _process_many(resource_ids: list[int], bot: Bot) -> None:
    for resource_id in resource_ids:
        start_book_processing(resource_id, bot)
        task = _tasks.get(resource_id)
        if task:
            await task
        await asyncio.sleep(1)


async def _download_and_process(resource_id: int, bot: Bot) -> None:
    resource = storage.get_resource(resource_id)
    if not resource:
        return
    if resource.get("local_path") and Path(str(resource["local_path"])).exists():
        await resource_processor.process_resource(resource_id)
        return

    storage.update_resource_status(resource_id, "processing")
    file_id = str(resource.get("file_id") or "")
    if not file_id:
        storage.update_resource_status(resource_id, "failed", "Existing book has no Telegram file_id.")
        return

    safe_name = _safe_file_name(str(resource.get("file_name") or f"book_{resource.get('book_code')}.pdf"))
    local_path = _resource_dir() / f"existing_book_{resource.get('book_code')}_{safe_name}"

    try:
        tg_file = await bot.get_file(file_id)
        await bot.download_file(tg_file.file_path, destination=local_path)
    except TelegramBadRequest as exc:
        if _is_too_big_error(exc):
            storage.update_resource_status(
                resource_id,
                "failed",
                "Telegram Bot API cannot download this existing book because the file is too big.",
            )
            return
        logger.exception("Existing book download failed for resource %s", resource_id)
        storage.update_resource_status(resource_id, "failed", str(exc)[:1000])
        return
    except Exception as exc:
        logger.exception("Existing book download failed for resource %s", resource_id)
        storage.update_resource_status(resource_id, "failed", str(exc)[:1000])
        return

    storage.update_resource_file(
        resource_id,
        local_path=str(local_path),
        mime_type=str(resource.get("mime_type") or ""),
        file_name=safe_name,
    )
    await resource_processor.process_resource(resource_id)
