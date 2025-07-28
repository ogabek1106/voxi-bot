# utils.py

import asyncio
import logging

logger = logging.getLogger(__name__)

async def delete_after_delay(bot, chat_id, file_message_id, countdown_message_id, delay=900):
    try:
        for remaining in range(delay, 0, -1):
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=countdown_message_id,
                    text=f"⏳ File will be deleted in {remaining} seconds."
                )
            except Exception as e:
                logger.warning(f"Edit failed at {remaining}s: {e}")
            await asyncio.sleep(1)

        await bot.delete_message(chat_id=chat_id, message_id=file_message_id)
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=countdown_message_id,
            text="✅ File deleted after 15 minutes."
        )
    except Exception as e:
        logger.error(f"Error in delete_after_delay: {e}")
