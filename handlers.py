# utils.py

import asyncio

def get_progress_bar(current, total, length=12):
    filled = int(length * current / total)
    bar = "█" * filled + "-" * (length - filled)
    return bar

async def countdown_timer(bot, chat_id, message_id, duration, final_text=None):
    for remaining in range(duration, 0, -1):
        minutes = remaining // 60
        seconds = remaining % 60
        bar = get_progress_bar(remaining, duration)
        text = f"⏳ [{bar}] {minutes:02}:{seconds:02} remaining"
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
        except:
            break
        await asyncio.sleep(1)

    if final_text is None:
        final_text = (
            "♻️ This file was deleted for your privacy.\n"
            "To get it again, send the *code of the book*."
        )

    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=final_text, parse_mode="Markdown")
    except:
        pass

async def delete_after_delay(bot, chat_id, message_id, delay):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except:
        pass
