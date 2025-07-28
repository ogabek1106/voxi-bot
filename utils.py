# utils.py
import asyncio
import logging

logger = logging.getLogger(__name__)

async def delete_after_delay(bot, chat_id, message_id, delay):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.warning(f"Couldn't delete message: {e}")

async def countdown_timer(bot, chat_id, message_id, delay):
    for remaining in range(delay, 0, -1):
        mins, secs = divmod(remaining, 60)
        text = f"⏳ {mins:02d}:{secs:02d} remaining"
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
        except Exception:
            pass
        await asyncio.sleep(1)
