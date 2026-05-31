import logging
import os
from pathlib import Path
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove

from admins import ADMIN_IDS
from database import DB_PATH

from . import ai, resource_processor, scheduler, storage

logger = logging.getLogger(__name__)
router = Router()


class ResourceUploadState(StatesGroup):
    waiting_file = State()
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


async def _save_document(message: Message, state: FSMContext) -> bool:
    doc = message.document
    if not doc:
        return False
    safe_name = (doc.file_name or f"resource_{doc.file_unique_id}").replace("\\", "_").replace("/", "_")
    local_path = _resource_dir() / f"{doc.file_unique_id}_{safe_name}"

    file = await message.bot.get_file(doc.file_id)
    await message.bot.download_file(file.file_path, destination=local_path)

    extracted_text = ""
    mime = doc.mime_type or ""
    if mime.startswith("text/") or safe_name.lower().endswith((".txt", ".md", ".csv")):
        try:
            extracted_text = local_path.read_text(encoding="utf-8", errors="ignore")[:12000]
        except Exception:
            logger.exception("Could not read uploaded text resource")

    await state.update_data(
        file_id=doc.file_id,
        file_unique_id=doc.file_unique_id,
        file_name=safe_name,
        mime_type=mime,
        local_path=str(local_path),
        extracted_text=extracted_text,
    )
    return True


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


@router.message(Command("cancel"), ResourceUploadState.waiting_file)
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
