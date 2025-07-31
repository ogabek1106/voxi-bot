# utils.py

import asyncio

def get_progress_bar(current, total, length=12):
    filled = int(length * current / total)
    bar = "█" * filled + "-" * (length - filled)
    return bar

async def countdown_timer(bot, chat_id, message_id, duration, final_text=None, update_interval=30):
    print(f"Starting countdown: {duration} seconds for message {message_id}")
    try:
        interval = 30  # Update every 30 seconds
        interval = update_interval  # Use provided interval
            current = max(remaining, 0)
            minutes = current // 60
            seconds = current % 60
            bar = get_progress_bar(current, duration)
            text = f"⏳ [{bar}] {minutes:02}:{seconds:02} remaining"
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
            await asyncio.sleep(interval)

        # Final message
        if final_text is None:
            final_text = (
                "♻️ This file was deleted for your privacy.\n"
                "To get it again, send the *code of the book*."
            )

        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=final_text,
            parse_mode="Markdown"
        )
        print(f"✅ Countdown ended. Final message updated for message {message_id}")

    except Exception as e:
        print(f"[countdown_timer ERROR] {e}")

async def delete_after_delay(bot, chat_id, message_id, delay):
    try:
        print(f"⏳ Scheduled deletion of file message {message_id} in {delay} seconds.")
        await asyncio.sleep(delay)
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        print(f"✅ Deleted file message {message_id}")
    except Exception as e:
        print(f"[delete_after_delay ERROR] {e}")
