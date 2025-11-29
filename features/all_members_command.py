# features/all_members_command.py

import logging
from telegram import Update
from telegram.ext import CallbackContext, CommandHandler
from admins import ADMINS
from database import get_all_users
import asyncio

logger = logging.getLogger(__name__)

def setup(dispatcher):
    logger.info("all_members_simple feature loaded. Admins=%s", ADMINS)
    dispatcher.add_handler(CommandHandler("all_members", all_members_handler))


async def all_members_handler(update: Update, context: CallbackContext):
    user_id = update.effective_user.id

    # 1️⃣ first confirmation (instant reply)
    await update.message.reply_text("📩 *Command received!*\n\nPreparing to send your message to all users...", parse_mode="Markdown")

    # 2️⃣ Check admin
    if user_id not in ADMINS:
        return await update.message.reply_text("❌ You are not allowed to use this command.")

    try:
        # Get the text user wants to send
        parts = update.message.text.split(" ", 1)
        if len(parts) < 2:
            return await update.message.reply_text("⚠️ Please type:\n`/all_members Your message`", parse_mode="Markdown")

        broadcast_text = parts[1]

        users = get_all_users()

        # Debug message: show how many users
        await update.message.reply_text(f"👥 Found **{len(users)}** users.\nStarting broadcast...")

        success = 0
        failed = 0

        # Live countdown trackers
        last_success_report = 0
        last_fail_report = 0

        for uid in users:
            try:
                await context.bot.send_message(chat_id=uid, text=broadcast_text)
                success += 1
            except Exception as e:
                logger.warning(f"Failed to send to {uid}: {e}")
                failed += 1

            # Send update every 10 successes
            if success - last_success_report >= 10:
                last_success_report = success
                await update.message.reply_text(f"✅ Sent: {success}")

            # Send update every 10 failures
            if failed - last_fail_report >= 10:
                last_fail_report = failed
                await update.message.reply_text(f"❌ Failed: {failed}")

            await asyncio.sleep(0.05)

        # Final message
        await update.message.reply_text(
            f"🎉 Broadcast finished!\n\n"
            f"✅ Successful: {success}\n"
            f"❌ Failed: {failed}"
        )

    except Exception as e:
        logger.error(f"Error in all_members_handler: {e}")
        await update.message.reply_text("⚠️ Error during broadcast. Check logs.")
