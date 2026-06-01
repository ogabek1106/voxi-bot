import asyncio
import logging
import math
import os
import random
from datetime import datetime, time as dtime
from typing import Dict, Optional
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from admins import ADMIN_IDS

from . import ai, storage
from .html_format import sanitize_telegram_html

logger = logging.getLogger(__name__)

TIMEZONE = os.getenv("CONTENT_ENGINE_TZ", "Europe/Moscow")
CHECK_INTERVAL_SECONDS = int(os.getenv("CONTENT_ENGINE_CHECK_INTERVAL", "60"))
_task: Optional[asyncio.Task] = None

WINDOWS = {
    "morning": (dtime(9, 0), dtime(11, 0)),
    "afternoon": (dtime(14, 0), dtime(16, 0)),
    "evening": (dtime(18, 0), dtime(19, 0)),
}


def _check_interval_minutes() -> int:
    return max(1, math.ceil(CHECK_INTERVAL_SECONDS / 60))


def tz() -> ZoneInfo:
    try:
        return ZoneInfo(TIMEZONE)
    except Exception:
        logger.warning("Invalid CONTENT_ENGINE_TZ=%s; falling back to Europe/Moscow", TIMEZONE)
        return ZoneInfo("Europe/Moscow")


def local_now() -> datetime:
    return datetime.now(tz())


def quiet_hours(now: Optional[datetime] = None) -> bool:
    now = now or local_now()
    return now.time() >= dtime(19, 0)


def _minutes_to_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _hhmm_to_minutes(value: str) -> Optional[int]:
    try:
        hour, minute = str(value).split(":", 1)
        return int(hour) * 60 + int(minute)
    except (TypeError, ValueError):
        return None


def _latest_due_minute(slot: str, end: dtime) -> int:
    end_minutes = end.hour * 60 + end.minute
    if slot == "evening":
        return end_minutes - (_check_interval_minutes() + 1)
    return end_minutes - 1


def _effective_scheduled_time(slot: str, scheduled: str) -> str:
    window = WINDOWS.get(slot)
    scheduled_minutes = _hhmm_to_minutes(scheduled)
    if not window or scheduled_minutes is None:
        return scheduled
    latest = _latest_due_minute(slot, window[1])
    if scheduled_minutes > latest:
        return _minutes_to_hhmm(latest)
    return scheduled


def _random_time(slot: str, start: dtime, end: dtime) -> str:
    start_minutes = start.hour * 60 + start.minute
    end_minutes = _latest_due_minute(slot, end)
    if end_minutes < start_minutes:
        end_minutes = start_minutes
    minute = random.randint(start_minutes, end_minutes)
    return _minutes_to_hhmm(minute)


def ensure_today_schedule(now: Optional[datetime] = None) -> None:
    now = now or local_now()
    schedule: Dict[str, str] = {
        slot: _random_time(slot, start, end)
        for slot, (start, end) in WINDOWS.items()
    }
    storage.upsert_daily_slots(now.date().isoformat(), schedule)


def review_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Approve", callback_data=f"vc:approve:{draft_id}"),
                InlineKeyboardButton(text="✏️ Edit", callback_data=f"vc:edit:{draft_id}"),
            ],
            [
                InlineKeyboardButton(text="🔁 Regenerate", callback_data=f"vc:regen:{draft_id}"),
                InlineKeyboardButton(text="❌ Reject", callback_data=f"vc:reject:{draft_id}"),
            ],
            [
                InlineKeyboardButton(text="📌 Mark as Posted/Used", callback_data=f"vc:posted:{draft_id}"),
            ],
        ]
    )


async def send_draft_to_admins(bot: Bot, draft_id: int, draft_text: str) -> None:
    text = (
        "<b>Voxi Content Engine draft</b>\n"
        f"Draft ID: {draft_id}\n\n"
        f"{sanitize_telegram_html(draft_text)}"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                chat_id=int(admin_id),
                text=text[:4000],
                reply_markup=review_keyboard(draft_id),
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("Failed to send content draft to admin %s", admin_id)


async def generate_one_draft(bot: Bot, slot: str = "manual", notify: bool = True) -> Optional[int]:
    now = local_now()
    weekday = ai.weekday_name(now.weekday())
    category = ai.category_for_slot(now.weekday(), slot)
    contract = ai.generation_contract_for_category(category)
    allowed_idea_types = contract.get("allowed_idea_types") or []
    idea_card = storage.choose_resource_idea_by_types(allowed_idea_types, allow_fallback=False)
    source = None if (idea_card or allowed_idea_types) else storage.choose_resource()
    result = await ai.generate_draft_text(now.weekday(), slot, source, idea_card, category=category)
    draft_text = sanitize_telegram_html(str(result["text"]))
    draft_id = storage.create_draft(
        draft_text=draft_text,
        generated_date=now.date().isoformat(),
        weekday=weekday,
        slot=slot,
        content_category=category,
        source_resource_id=(idea_card.get("resource_id") if idea_card else source.get("id") if source else None),
        source_title=(idea_card.get("resource_title") if idea_card else source.get("title") if source else None),
        used_topic=result.get("topic"),
        used_vocabulary=[result.get("vocabulary")] if result.get("vocabulary") else [],
        topic=result.get("topic"),
        source_chunk_id=str(idea_card.get("id")) if idea_card else None,
        generation_prompt=result.get("generation_prompt"),
        style_examples_used=result.get("style_examples_used") or [],
        hashtags_used=result.get("hashtags_used") or [],
    )
    if not draft_id:
        return None
    if result.get("failed"):
        storage.update_draft_status(int(draft_id), "failed")
        logger.warning(
            "Content draft generation failed validation for draft %s (%s/%s): %s",
            draft_id,
            slot,
            category,
            result.get("error") or "validation failed",
        )
        return draft_id
    if source:
        storage.mark_resource_used(int(source["id"]))
    if idea_card:
        storage.mark_resource_idea_used(int(idea_card["id"]))
    if notify:
        await send_draft_to_admins(bot, draft_id, draft_text)
    return draft_id


async def regenerate_existing_draft(bot: Bot, draft: dict, notify: bool = True) -> Optional[int]:
    now = local_now()
    source = None
    if draft.get("source_resource_id"):
        source = storage.get_resource(int(draft["source_resource_id"]))
    result = await ai.regenerate_draft_text(draft, source)
    draft_text = sanitize_telegram_html(str(result["text"]))
    draft_id = storage.create_draft(
        draft_text=draft_text,
        generated_date=now.date().isoformat(),
        weekday=draft.get("weekday") or ai.weekday_name(now.weekday()),
        slot=draft.get("slot") or "manual",
        content_category=draft.get("content_category") or ai.category_for_weekday(now.weekday()),
        source_resource_id=draft.get("source_resource_id"),
        source_title=draft.get("source_title"),
        used_topic=result.get("topic") or draft.get("used_topic"),
        used_vocabulary=[],
        topic=result.get("topic") or draft.get("topic"),
        source_chunk_id=draft.get("source_chunk_id"),
        generation_prompt=result.get("generation_prompt"),
        style_examples_used=result.get("style_examples_used") or [],
        hashtags_used=result.get("hashtags_used") or [],
    )
    if not draft_id:
        return None
    if notify:
        await send_draft_to_admins(bot, draft_id, draft_text)
    return draft_id


async def _maybe_generate_due_slot(bot: Bot) -> None:
    now = local_now()
    ensure_today_schedule(now)
    if storage.is_paused() or quiet_hours(now):
        return

    current_hhmm = now.strftime("%H:%M")
    today = now.date().isoformat()
    for slot_row in storage.get_slots_for_date(today):
        if slot_row.get("status") != "scheduled":
            continue
        scheduled = str(slot_row.get("scheduled_time") or "")
        effective_scheduled = _effective_scheduled_time(str(slot_row["slot"]), scheduled)
        if effective_scheduled and effective_scheduled <= current_hhmm:
            draft_id = await generate_one_draft(bot, slot=str(slot_row["slot"]), notify=True)
            if draft_id:
                storage.mark_slot_generated(today, str(slot_row["slot"]), draft_id)
            return


async def _scheduler_loop(bot: Bot) -> None:
    logger.info("Voxi Content Engine scheduler started (tz=%s)", TIMEZONE)
    while True:
        try:
            await _maybe_generate_due_slot(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Content engine scheduler tick failed")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def start_scheduler(bot: Bot) -> None:
    global _task
    if _task and not _task.done():
        return
    ensure_today_schedule()
    _task = asyncio.create_task(_scheduler_loop(bot))
