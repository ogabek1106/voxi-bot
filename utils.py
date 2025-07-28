# utils.py

import asyncio
import logging

logger = logging.getLogger(__name__)

# Delete message after delay
async def delete_after_delay(bot, chat_id, message_id, delay=900):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.warning(f"Couldn't delete message: {e}")

# Send and update countdown timer
async def countdown_timer(bot, chat_id, delay_seconds=900, file_code=None):
    countdown_msg = await bot.send_message(chat_id=chat_id, text=f"⏳ *Deleting in:* {delay_seconds} seconds", parse_mode="Markdown")

    for remaining in range(delay_seconds - 1, -1, -1):
        await asyncio.sleep(1)
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=countdown_msg.message_id,
                text=f"⏳ *Deleting in:* {remaining} seconds",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Countdown update failed: {e}")
            break

    # After countdown ends, update message with final info
    final_msg = (
        f"♻️ *The file was deleted for your privacy.*\n"
        f"To see it again, send: *{file_code}*"
    )
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=countdown_msg.message_id,
            text=final_msg,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning(f"Couldn't update final countdown message: {e}")
