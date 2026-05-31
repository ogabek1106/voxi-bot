import asyncio
import logging
import os
import random
from datetime import datetime, time as dtime
from typing import Dict, Optional
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from admins import ADMIN_IDS

from . import ai, storage

logger = logging.getLogger(__name__)

TIMEZONE = os.getenv("CONTENT_ENGINE_TZ", os.getenv("TZ", "Asia/Tashkent"))
CHECK_INTERVAL_SECONDS = int(os.getenv("CONTENT_ENGINE_CHECK_INTERVAL", "60"))
_task: Optional[asyncio.Task] = None

WINDOWS = {
    "morning": (dtime(9, 0), dtime(11, 0)),
    "afternoon": (dtime(14, 0), dtime(16, 0)),
    "evening": (dtime(18, 0), dtime(19, 0)),
}


def tz() -> ZoneInfo:
    try:
        return ZoneInfo(TIMEZONE)
    except Exception:
        logger.warning("Invalid CONTENT_ENGINE_TZ=%s; falling back to Asia/Tashkent", TIMEZONE)
        return ZoneInfo("Asia/Tashkent")


def local_now() -> datetime:
    return datetime.now(tz())


def quiet_hours(now: Optional[datetime] = None) -> bool:
    now = now or local_now()
    return now.time() >= dtime(19, 0)


def _random_time(start: dtime, end: dtime) -> str:
    start_minutes = start.hour * 60 + start.minute
    end_minutes = end.hour * 60 + end.minute
    minute = random.randint(start_minutes, end_minutes)
    return f"{minute // 60:02d}:{minute % 60:02d}"


def ensure_today_schedule(now: Optional[datetime] = None) -> None:
    now = now or local_now()
    schedule: Dict[str, str] = {
        slot: _random_time(start, end)
        for slot, (start, end) in WINDOWS.items()
    }
    storage.upsert_daily_slots(now.date().isoformat(), schedule)


def review_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Approve", callback_data=f"vc:approve:{draft_id}"),
                InlineKeyboardButton(text="🔁 Regenerate", callback_data=f"vc:regen:{draft_id}"),
            ],
            [
                InlineKeyboardButton(text="❌ Reject", callback_data=f"vc:reject:{draft_id}"),
                InlineKeyboardButton(text="📌 Mark as Posted/Used", callback_data=f"vc:posted:{draft_id}"),
            ],
        ]
    )


async def send_draft_to_admins(bot: Bot, draft_id: int, draft_text: str) -> None:
    text = (
        "Voxi Content Engine draft\n"
        f"Draft ID: {draft_id}\n\n"
        f"{draft_text}"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                chat_id=int(admin_id),
                text=text[:4000],
                reply_markup=review_keyboard(draft_id),
                parse_mode=None,
            )
        except Exception:
            logger.exception("Failed to send content draft to admin %s", admin_id)


async def generate_one_draft(bot: Bot, slot: str = "manual", notify: bool = True) -> Optional[int]:
    now = local_now()
    source = storage.choose_resource()
    weekday = ai.weekday_name(now.weekday())
    category = ai.category_for_weekday(now.weekday())
    result = await ai.generate_draft_text(now.weekday(), slot, source)
    draft_id = storage.create_draft(
        draft_text=result["text"],
        generated_date=now.date().isoformat(),
        weekday=weekday,
        slot=slot,
        content_category=category,
        source_resource_id=source.get("id") if source else None,
        source_title=source.get("title") if source else None,
        used_topic=result.get("topic"),
        used_vocabulary=[result.get("vocabulary")] if result.get("vocabulary") else [],
    )
    if not draft_id:
        return None
    if source:
        storage.mark_resource_used(int(source["id"]))
    if notify:
        await send_draft_to_admins(bot, draft_id, result["text"])
    return draft_id


async def _maybe_generate_due_slot(bot: Bot) -> None:
    now = local_now()
    ensure_today_schedule(now)
    if storage.is_paused() or quiet_hours(now):
        return
    if storage.get_pending_drafts(1):
        return

    current_hhmm = now.strftime("%H:%M")
    today = now.date().isoformat()
    for slot_row in storage.get_slots_for_date(today):
        if slot_row.get("status") != "scheduled":
            continue
        scheduled = str(slot_row.get("scheduled_time") or "")
        if scheduled and scheduled <= current_hhmm:
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
