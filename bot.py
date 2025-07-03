import os
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# 🔐 Your actual bot token
BOT_TOKEN = "7687239994:AAFAD9tHc3bJWOgOx6G5SB82CWboveKmKko"

# 📁 Folder containing all your book files
BOOKS_FOLDER = "books"

# 📚 Map book codes to real filenames
BOOKS = {
    "445": {
        "file": "445.pdf",
        "title": "Atomic_Habits.pdf"
    },
    "446": {
        "file": "446.pdf",
        "title": "IELTS_Speaking_Band_9.pdf"
    }
    # ➕ Add more books here
}

# ⏱ Deletes the message after delay
async def delete_later(context, chat_id, message_id, delay):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except:
        pass

# 🚀 Handles /start <code>
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("❌ Please send a valid book code. Example:\n/start 445")
        return

    code = context.args[0]
    book = BOOKS.get(code)

    if book:
        file_path = os.path.join(BOOKS_FOLDER, book["file"])

        try:
            with open(file_path, "rb") as doc:
                sent = await update.message.reply_document(
                    document=doc,
                    filename=book["title"],
                    caption=f"📘 Book #{code} — {book['title'].replace('_', ' ').replace('.pdf', '')}\nVoxi: It will self-destruct in 15 minutes ⏳"
                )

            # 🧠 Start background delete task
            asyncio.create_task(delete_later(context, sent.chat_id, sent.message_id, delay=900))

        except Exception as e:
            await update.message.reply_text(f"❌ Failed to send the file: {e}")
    else:
        await update.message.reply_text("❌ Book not found. Please check the code.")

# 🔁 Start the bot
if __name__ == "__main__":
    print("🚀 Starting Voxi Bot...")
    try:
        app = ApplicationBuilder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        print("✅ Voxi Bot is running... Try /start 445")
        app.run_polling()
    except Exception as e:
        print(f"❌ Error starting the bot: {e}")
