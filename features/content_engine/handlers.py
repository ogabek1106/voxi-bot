import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse
from uuid import uuid4

import aiohttp
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove

from admins import ADMIN_IDS
from database import DB_PATH

from . import ai, book_resources, resource_processor, scheduler, storage

logger = logging.getLogger(__name__)
router = Router()


class ResourceUploadState(StatesGroup):
    waiting_file = State()
    waiting_link = State()
    waiting_local_file = State()
    waiting_title = State()


class StyleExampleState(StatesGroup):
    waiting_post = State()
    waiting_category = State()


class DraftEditState(StatesGroup):
    waiting_corrected = State()


STYLE_CATEGORIES = [
    "Word of the Day",
    "Phrase",
    "Grammar Tip",
    "Collocations",
    "Resource",
    "Quiz/Poll",
    "Quote/Music",
    "Mistakes",
    "General",
]


def is_admin(user_id: Optional[int]) -> bool:
    return user_id is not None and int(user_id) in {int(x) for x in ADMIN_IDS}


def _resource_dir() -> Path:
    base = os.getenv("CONTENT_RESOURCE_DIR")
    if base:
        path = Path(base)
    else:
        db_dir = Path(DB_PATH).parent if DB_PATH else Path(".")
        path = db_dir / "content_resources"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _parse_title_category(text: str) -> tuple[str, str]:
    raw = (text or "").strip()
    if "|" in raw:
        title, category = raw.split("|", 1)
        return title.strip() or "Untitled resource", category.strip()
    return raw or "Untitled resource", ""


def _max_resource_bytes() -> int:
    try:
        max_mb = int(os.getenv("CONTENT_RESOURCE_MAX_MB", "300"))
    except ValueError:
        max_mb = 300
    return max(1, max_mb) * 1024 * 1024


def _safe_file_name(name: str) -> str:
    safe = (name or "").strip().replace("\\", "_").replace("/", "_")
    safe = "".join(ch if ch.isalnum() or ch in "._- ()" else "_" for ch in safe)
    return safe.strip("._ ") or f"resource_{uuid4().hex}"


def _file_name_from_url(url: str) -> str:
    parsed = urlparse(url)
    name = unquote(Path(parsed.path).name or "")
    return _safe_file_name(name or f"resource_{uuid4().hex}.bin")


def _server_local_root() -> Optional[Path]:
    raw = os.getenv("CONTENT_RESOURCE_LOCAL_IMPORT_DIR", "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _style_category_keyboard() -> ReplyKeyboardMarkup:
    rows = []
    for i in range(0, len(STYLE_CATEGORIES), 2):
        rows.append([KeyboardButton(text=name) for name in STYLE_CATEGORIES[i:i + 2]])
    rows.append([KeyboardButton(text="/cancel")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, one_time_keyboard=True)


def _preview(text: str, limit: int = 80) -> str:
    text = " ".join((text or "").split())
    return text[:limit] + ("..." if len(text) > limit else "")


def _message_html_text(message: Message) -> str:
    html_text = getattr(message, "html_text", None)
    if html_text:
        return html_text
    return message.text or ""


def _message_html_content(message: Message) -> str:
    html_text = getattr(message, "html_text", None)
    if html_text:
        return html_text
    html_caption = getattr(message, "html_caption", None)
    if html_caption:
        return html_caption
    return message.text or message.caption or ""


def _read_text_preview(local_path: Path, safe_name: str, mime: str) -> str:
    if mime.startswith("text/") or safe_name.lower().endswith((".txt", ".md", ".csv")):
        try:
            return local_path.read_text(encoding="utf-8", errors="ignore")[:12000]
        except Exception:
            logger.exception("Could not read uploaded text resource")
    return ""


async def _save_document(message: Message, state: FSMContext) -> bool:
    doc = message.document
    if not doc:
        return False
    safe_name = _safe_file_name(doc.file_name or f"resource_{doc.file_unique_id}")
    local_path = _resource_dir() / f"{doc.file_unique_id}_{safe_name}"

    file = await message.bot.get_file(doc.file_id)
    await message.bot.download_file(file.file_path, destination=local_path)

    mime = doc.mime_type or ""
    extracted_text = _read_text_preview(local_path, safe_name, mime)

    await state.update_data(
        file_id=doc.file_id,
        file_unique_id=doc.file_unique_id,
        file_name=safe_name,
        mime_type=mime,
        local_path=str(local_path),
        extracted_text=extracted_text,
    )
    return True


async def _download_resource_link(url: str, state: FSMContext) -> tuple[bool, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False, "Please send a direct download link that starts with http:// or https://."

    max_bytes = _max_resource_bytes()
    unique_id = f"link_{uuid4().hex}"
    safe_name = _file_name_from_url(url)
    local_path = _resource_dir() / f"{unique_id}_{safe_name}"
    tmp_path = local_path.with_suffix(local_path.suffix + ".tmp")
    timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_connect=30, sock_read=120)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, allow_redirects=True) as response:
                if response.status >= 400:
                    return False, f"Download failed with HTTP status {response.status}."

                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        if int(content_length) > max_bytes:
                            return False, (
                                f"This file is larger than the configured limit "
                                f"({max_bytes // 1024 // 1024} MB)."
                            )
                    except ValueError:
                        pass

                mime = (response.headers.get("Content-Type") or "").split(";", 1)[0].strip()
                downloaded = 0
                with tmp_path.open("wb") as handle:
                    async for chunk in response.content.iter_chunked(1024 * 1024):
                        if not chunk:
                            continue
                        downloaded += len(chunk)
                        if downloaded > max_bytes:
                            handle.close()
                            tmp_path.unlink(missing_ok=True)
                            return False, (
                                f"This file is larger than the configured limit "
                                f"({max_bytes // 1024 // 1024} MB)."
                            )
                        handle.write(chunk)
    except aiohttp.ClientError as exc:
        tmp_path.unlink(missing_ok=True)
        logger.warning("Resource link download failed: %s", exc)
        return False, "Could not download this link. Please check that it is publicly accessible."
    except asyncio.TimeoutError:
        tmp_path.unlink(missing_ok=True)
        return False, "Download timed out. Please try another direct link."
    except Exception:
        tmp_path.unlink(missing_ok=True)
        logger.exception("Unexpected resource link download failure")
        return False, "Failed to download this resource link."

    tmp_path.replace(local_path)
    extracted_text = _read_text_preview(local_path, safe_name, mime)
    await state.update_data(
        file_id="",
        file_unique_id=unique_id,
        file_name=safe_name,
        mime_type=mime,
        local_path=str(local_path),
        extracted_text=extracted_text,
    )
    return True, ""


def _copy_local_resource_path(raw_path: str) -> tuple[bool, str, dict]:
    value = (raw_path or "").strip().strip('"')
    if value.startswith("file://"):
        value = value[7:]
    if not value:
        return False, "Please send a local server file path.", {}

    source = Path(value).expanduser().resolve()
    allowed_root = _server_local_root()
    if allowed_root:
        try:
            source.relative_to(allowed_root)
        except ValueError:
            return False, f"Local imports are restricted to {allowed_root}.", {}

    if not source.exists() or not source.is_file():
        return False, "Local file was not found on the server.", {}

    max_bytes = _max_resource_bytes()
    size = source.stat().st_size
    if size > max_bytes:
        return False, f"This file is larger than the configured limit ({max_bytes // 1024 // 1024} MB).", {}

    safe_name = _safe_file_name(source.name)
    unique_id = f"local_{uuid4().hex}"
    local_path = _resource_dir() / f"{unique_id}_{safe_name}"
    tmp_path = local_path.with_suffix(local_path.suffix + ".tmp")
    try:
        with source.open("rb") as src, tmp_path.open("wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
        tmp_path.replace(local_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        logger.exception("Local resource copy failed")
        return False, "Failed to copy this local resource file.", {}

    mime = "application/pdf" if safe_name.lower().endswith(".pdf") else ""
    return True, "", {
        "file_id": "",
        "file_unique_id": unique_id,
        "file_name": safe_name,
        "mime_type": mime,
        "local_path": str(local_path),
        "extracted_text": _read_text_preview(local_path, safe_name, mime),
    }


@router.message(Command("content_status"))
async def content_status(message: Message):
    if not is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Admins only.")
        return

    now = scheduler.local_now()
    scheduler.ensure_today_schedule(now)
    slots = storage.get_slots_for_date(now.date().isoformat())
    pending = storage.get_pending_drafts(5)
    paused = storage.is_paused()

    lines = [
        "Voxi Content Engine status",
        f"Date: {now.date().isoformat()} ({scheduler.TIMEZONE})",
        f"Automatic generation: {'paused' if paused else 'active'}",
        "",
        "Today's slots:",
    ]
    for slot in slots:
        lines.append(
            f"- {slot['slot']}: {slot['scheduled_time']} | {slot['status']}"
            + (f" | draft #{slot['generated_draft_id']}" if slot.get("generated_draft_id") else "")
        )
    lines += ["", f"Pending drafts: {len(pending)}"]
    for draft in pending:
        lines.append(f"- #{draft['id']} {draft['content_category']} ({draft['slot']})")

    await message.answer("\n".join(lines), parse_mode=None)


@router.message(Command("generate_content_now"))
async def generate_content_now(message: Message):
    if not is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Admins only.")
        return
    if scheduler.quiet_hours():
        await message.answer("Content Engine is in quiet hours after 19:00. No draft generated.")
        return
    if storage.is_paused():
        await message.answer("Content Engine is paused. Use /resume_content first.")
        return
    if storage.get_pending_drafts(1):
        await message.answer("A draft is still pending review. Resolve it before generating another one.")
        return

    await message.answer("Generating one draft for review...")
    draft_id = await scheduler.generate_one_draft(message.bot, slot="manual", notify=True)
    if draft_id:
        await message.answer(f"Draft #{draft_id} generated and sent for review.")
    else:
        await message.answer("Failed to generate draft. Check logs/OpenAI configuration.")


@router.message(Command("content_queue"))
async def content_queue(message: Message):
    if not is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Admins only.")
        return
    pending = storage.get_pending_drafts(10)
    if not pending:
        await message.answer("No pending content drafts.")
        return
    lines = ["Pending content drafts:"]
    for draft in pending:
        lines.append(
            f"#{draft['id']} | {draft['generated_date']} | {draft['content_category']} | "
            f"source: {draft.get('source_title') or 'weekly plan'}"
        )
    await message.answer("\n".join(lines), parse_mode=None)


@router.message(Command("pause_content"))
async def pause_content(message: Message):
    if not is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Admins only.")
        return
    storage.set_paused(True)
    await message.answer("Automatic content generation paused.")


@router.message(Command("resume_content"))
async def resume_content(message: Message):
    if not is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Admins only.")
        return
    storage.set_paused(False)
    scheduler.ensure_today_schedule()
    await message.answer("Automatic content generation resumed.")


@router.message(Command("resources"))
async def resources(message: Message):
    if not is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Admins only.")
        return
    rows = storage.list_resources_with_idea_counts(20)
    if not rows:
        await message.answer("No uploaded resources yet. Use /upload_resource.")
        return
    lines = ["Uploaded resources:"]
    for row in rows:
        lines.append(
            f"#{row['id']} | {row['title']} | {row.get('status') or 'uploaded'} | "
            f"ideas: {row.get('idea_count') or 0}"
        )
    await message.answer("\n".join(lines), parse_mode=None)


@router.message(Command("resource_status"))
async def resource_status(message: Message):
    if not is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Admins only.")
        return
    rows = storage.list_resources_with_idea_counts(30)
    if not rows:
        await message.answer("No uploaded resources yet. Use /upload_resource.")
        return
    lines = ["Resource processing status:"]
    for row in rows:
        status = row.get("status") or "uploaded"
        line = f"- {row['title']}\n  Status: {status}\n  Ideas: {row.get('idea_count') or 0}"
        if status == "failed" and row.get("processing_error"):
            line += f"\n  Error: {row['processing_error'][:180]}"
        lines.append(line)
    await message.answer("\n\n".join(lines), parse_mode=None)


@router.message(Command("import_book_resource"))
async def import_book_resource(message: Message):
    if not is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Admins only.")
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip():
        await message.answer("Usage: /import_book_resource <book_code>")
        return

    book_code = parts[1].strip()
    resource_id, created, note = book_resources.import_book_record(book_code)
    if not resource_id:
        await message.answer(note)
        return
    book_resources.start_book_processing(resource_id, message.bot)
    await message.answer(
        f"{note}\n"
        f"Book code: {book_code}\n"
        f"Resource #{resource_id}\n"
        "Processing will continue in background."
    )


@router.message(Command("import_all_books_resources"))
async def import_all_books_resources(message: Message):
    if not is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Admins only.")
        return
    imported, reused = book_resources.start_all_books_import(message.bot)
    await message.answer(
        "Existing books import started.\n"
        f"New resources: {imported}\n"
        f"Already imported: {reused}\n"
        "Downloads and idea-card processing will continue gradually in background."
    )


@router.message(Command("book_resources_status"))
async def book_resources_status(message: Message):
    if not is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Admins only.")
        return
    rows = storage.list_existing_book_resources_with_idea_counts(100)
    if not rows:
        await message.answer("No existing books have been imported as content resources yet.")
        return

    lines = ["Imported book resources:"]
    for row in rows:
        line = (
            f"#{row['id']} | code {row.get('book_code') or '-'} | "
            f"{row.get('file_name') or row.get('title') or 'Untitled'}\n"
            f"Status: {row.get('status') or 'uploaded'} | Ideas: {row.get('idea_count') or 0}"
        )
        if row.get("processing_error"):
            line += f"\nError: {str(row['processing_error'])[:180]}"
        lines.append(line)
    await message.answer("\n\n".join(lines), parse_mode=None)


@router.message(Command("learn_post"))
async def learn_post(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Admins only.")
        return
    await state.clear()
    await state.set_state(StyleExampleState.waiting_post)
    await message.answer("Send me one post example.\nSend /cancel to abort.", reply_markup=ReplyKeyboardRemove())


@router.message(Command("style_examples"))
async def style_examples(message: Message):
    if not is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Admins only.")
        return
    examples = storage.list_style_examples(20)
    if not examples:
        await message.answer("No manual style examples saved yet. Use /learn_post.")
        return
    lines = ["Saved style examples:"]
    for example in examples:
        lines.append(f"#{example['id']} | {example['category']} | {_preview(example['text'])}")
    await message.answer("\n".join(lines), parse_mode=None)


@router.message(Command("delete_style_example"))
async def delete_style_example(message: Message):
    if not is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Admins only.")
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip().isdigit():
        await message.answer("Usage: /delete_style_example <id>")
        return
    example_id = int(parts[1].strip())
    if storage.delete_style_example(example_id):
        await message.answer(f"Style example #{example_id} deleted.")
    else:
        await message.answer(f"Style example #{example_id} was not found.")


@router.message(Command("cancel"), StyleExampleState.waiting_post)
@router.message(Command("cancel"), StyleExampleState.waiting_category)
@router.message(Command("cancel"), DraftEditState.waiting_corrected)
async def cancel_style_example(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    await state.clear()
    await message.answer("Cancelled.", reply_markup=ReplyKeyboardRemove())


@router.message(StyleExampleState.waiting_post, F.text)
async def receive_style_example_text(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    text = _message_html_text(message).strip()
    if len(text) < 20:
        await message.answer("Please send a full post example, not a short note.")
        return
    await state.update_data(style_text=text)
    await state.set_state(StyleExampleState.waiting_category)
    await message.answer(
        "Choose optional category for this example:",
        reply_markup=_style_category_keyboard(),
    )


@router.message(StyleExampleState.waiting_post)
async def receive_style_example_wrong(message: Message):
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    await message.answer("Please send the post example as text, or /cancel.")


@router.message(StyleExampleState.waiting_category, F.text)
async def receive_style_example_category(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    category = (message.text or "General").strip()
    if category not in STYLE_CATEGORIES:
        category = "General"
    data = await state.get_data()
    example_id = storage.add_style_example(data.get("style_text", ""), category)
    await state.clear()
    if example_id:
        await message.answer(
            f"Style example #{example_id} saved as {category}.",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        await message.answer("Failed to save style example.", reply_markup=ReplyKeyboardRemove())


@router.message(DraftEditState.waiting_corrected, F.text)
async def receive_corrected_draft(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    corrected = _message_html_text(message).strip()
    if len(corrected) < 20:
        await message.answer("Please send the full corrected version, or /cancel.")
        return

    data = await state.get_data()
    draft_id = data.get("edit_draft_id")
    draft = storage.get_draft(int(draft_id)) if draft_id else None
    if not draft:
        await state.clear()
        await message.answer("Draft not found. Please start again.", reply_markup=ReplyKeyboardRemove())
        return

    style_category = ai.style_category_for_plan(draft.get("content_category") or "General")
    example_id = storage.add_style_example(
        text=corrected,
        category=style_category,
        source="admin_edited_post",
        original_draft=draft.get("draft_text"),
    )
    storage.update_draft_status(int(draft["id"]), "approved")
    await state.clear()
    if example_id:
        await message.answer(
            f"Corrected draft saved as premium style example #{example_id}.\n"
            f"Draft #{draft['id']} marked approved.",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        await message.answer(
            "Corrected version received, but saving style example failed.",
            reply_markup=ReplyKeyboardRemove(),
        )


@router.message(Command("upload_resource"))
async def upload_resource(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Admins only.")
        return
    await state.clear()
    await state.set_state(ResourceUploadState.waiting_file)
    await message.answer(
        "Send a PDF/document/text file for the content resource library.\n"
        "Send /cancel to abort."
    )


@router.message(Command("upload_resource_link"))
async def upload_resource_link(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Admins only.")
        return
    await state.clear()
    await state.set_state(ResourceUploadState.waiting_link)
    await message.answer(
        "Send a direct download URL to a PDF/document/text file.\n"
        f"Max size: {_max_resource_bytes() // 1024 // 1024} MB.\n"
        "Send /cancel to abort."
    )


@router.message(Command("upload_resource_local"))
async def upload_resource_local(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Admins only.")
        return
    await state.clear()
    await state.set_state(ResourceUploadState.waiting_local_file)
    local_root = _server_local_root()
    root_note = f"\nAllowed local folder: {local_root}" if local_root else ""
    await message.answer(
        "Send a PDF/document for local content-engine storage, or send a local server file path.\n"
        "Server file paths bypass Telegram Bot API download limits."
        f"{root_note}\n"
        "Send /cancel to abort."
    )


@router.message(Command("cancel"), ResourceUploadState.waiting_file)
@router.message(Command("cancel"), ResourceUploadState.waiting_link)
@router.message(Command("cancel"), ResourceUploadState.waiting_local_file)
@router.message(Command("cancel"), ResourceUploadState.waiting_title)
async def cancel_resource_upload(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    await state.clear()
    await message.answer("Resource upload cancelled.")


@router.message(ResourceUploadState.waiting_file, F.document)
async def receive_resource_file(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    try:
        ok = await _save_document(message, state)
    except TelegramBadRequest as exc:
        if "file is too big" in str(exc).lower():
            await message.answer(
                "This file is too large for normal Telegram Bot API download.\n\n"
                "Send a smaller file OR use external link upload:\n"
                "/upload_resource_link\n\n"
                "Then send a direct download link."
            )
            return
        logger.exception("Resource file save failed")
        await message.answer("Failed to save this resource file.")
        return
    except Exception:
        logger.exception("Resource file save failed")
        await message.answer("Failed to save this resource file.")
        return
    if not ok:
        await message.answer("Please send a document, PDF, or text file.")
        return
    await state.set_state(ResourceUploadState.waiting_title)
    await message.answer(
        "File saved. Send the resource title.\n"
        "Optional format: Title | category"
    )


@router.message(ResourceUploadState.waiting_file)
async def receive_resource_wrong_file(message: Message):
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    await message.answer("Please send a document/PDF/text file, or /cancel.")


@router.message(ResourceUploadState.waiting_link, F.text)
async def receive_resource_link(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    url = (message.text or "").strip()
    await message.answer("Downloading resource link...")
    ok, error = await _download_resource_link(url, state)
    if not ok:
        await message.answer(f"{error}\n\nSend another direct link, or /cancel.")
        return
    await state.set_state(ResourceUploadState.waiting_title)
    await message.answer(
        "File downloaded. Send the resource title.\n"
        "Optional format: Title | category"
    )


@router.message(ResourceUploadState.waiting_link)
async def receive_resource_wrong_link(message: Message):
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    await message.answer("Please send a direct download URL, or /cancel.")


@router.message(ResourceUploadState.waiting_local_file, F.document)
async def receive_resource_local_document(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    try:
        ok = await _save_document(message, state)
    except TelegramBadRequest as exc:
        if "file is too big" in str(exc).lower():
            await message.answer(
                "Telegram cannot provide this file through the normal Bot API because it is too large.\n\n"
                "Reliable options:\n"
                "/upload_resource_link with a direct download URL\n"
                "/upload_resource_local with a file path that already exists on the server"
            )
            return
        logger.exception("Local resource Telegram document save failed")
        await message.answer("Failed to save this resource file.")
        return
    except Exception:
        logger.exception("Local resource Telegram document save failed")
        await message.answer("Failed to save this resource file.")
        return
    if not ok:
        await message.answer("Please send a document/PDF/text file, a server file path, or /cancel.")
        return
    await state.set_state(ResourceUploadState.waiting_title)
    await message.answer(
        "File saved locally. Send the resource title.\n"
        "Optional format: Title | category"
    )


@router.message(ResourceUploadState.waiting_local_file, F.text)
async def receive_resource_local_path(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    ok, error, data = await asyncio.to_thread(
        _copy_local_resource_path,
        message.text or "",
    )
    if not ok:
        await message.answer(f"{error}\n\nSend another local server file path, a document, or /cancel.")
        return
    await state.update_data(**data)
    await state.set_state(ResourceUploadState.waiting_title)
    await message.answer(
        "Local file copied. Send the resource title.\n"
        "Optional format: Title | category"
    )


@router.message(ResourceUploadState.waiting_local_file)
async def receive_resource_wrong_local(message: Message):
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    await message.answer("Please send a document/PDF/text file, a local server file path, or /cancel.")


@router.message(ResourceUploadState.waiting_title, F.text)
async def receive_resource_title(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    title, category = _parse_title_category(message.text or "")
    data = await state.get_data()
    resource_id = storage.add_resource(
        title=title,
        category=category,
        file_id=data.get("file_id", ""),
        file_unique_id=data.get("file_unique_id", ""),
        file_name=data.get("file_name", ""),
        mime_type=data.get("mime_type", ""),
        local_path=data.get("local_path", ""),
        extracted_text=data.get("extracted_text", ""),
    )
    await state.clear()
    if resource_id:
        resource_processor.start_processing(int(resource_id))
        await message.answer(
            f"Resource #{resource_id} saved: {title}\n"
            "Processing will continue in background."
        )
    else:
        await message.answer("Failed to save resource metadata.")


@router.callback_query(F.data.startswith("vc:"))
async def content_callback(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id if callback.from_user else None):
        await callback.answer("Admins only.", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer("Invalid action.", show_alert=True)
        return
    action, raw_id = parts[1], parts[2]
    try:
        draft_id = int(raw_id)
    except ValueError:
        await callback.answer("Invalid draft.", show_alert=True)
        return

    draft = storage.get_draft(draft_id)
    if not draft:
        await callback.answer("Draft not found.", show_alert=True)
        return

    status_map = {
        "approve": "approved",
        "reject": "rejected",
        "posted": "posted_used",
    }
    if action in status_map:
        storage.update_draft_status(draft_id, status_map[action])
        await callback.answer(f"Draft marked {status_map[action]}.")
        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer(f"Draft #{draft_id} status: {status_map[action]}", parse_mode=None)
        return

    if action == "edit":
        await state.clear()
        await state.set_state(DraftEditState.waiting_corrected)
        await state.update_data(edit_draft_id=draft_id)
        await callback.answer("Edit mode started.")
        if callback.message:
            await callback.message.answer("Send the corrected version.\nSend /cancel to abort.", parse_mode=None)
        return

    if action == "regen":
        if scheduler.quiet_hours():
            await callback.answer("Quiet hours after 19:00.", show_alert=True)
            return
        new_id = await scheduler.regenerate_existing_draft(callback.bot, draft, notify=True)
        if new_id:
            storage.update_draft_status(draft_id, "regenerated")
        await callback.answer("Regenerated." if new_id else "Regeneration failed.", show_alert=not bool(new_id))
        if callback.message:
            if new_id:
                await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer(
                (
                    f"Draft #{draft_id} marked regenerated. New draft: #{new_id}"
                    if new_id
                    else f"Draft #{draft_id} was kept pending because regeneration failed."
                ),
                parse_mode=None,
            )
        return

    await callback.answer("Unknown action.", show_alert=True)


@router.channel_post()
async def store_channel_post(message: Message):
    text = _message_html_content(message)
    if text:
        storage.save_channel_post(message.chat.id, message.message_id, text)
