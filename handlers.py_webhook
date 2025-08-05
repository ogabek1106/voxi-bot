from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hello! Bot is working.")

def register_handlers(app):
    app.add_handler(CommandHandler("start", start))
