# utils.py

import asyncio
import logging

logger = logging.getLogger(__name__)

async def delete_after_delay(bot, chat_id, message_id, delay=900):
    """Deletes a message after a delay (default: 15 minutes = 900 sec)."""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.warning(f"Couldn't delete message: {e}")
