import os
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ✅ Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🔐 Bot token
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ✅ Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"/start from {update.effective_user.id}")
    await update.message.reply_text("I hear you 👂")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Echo from {update.effective_user.id}: {update.message.text}")
    await update.message.reply_text("📩 I received your message!")

# 🚀 Create app and add handlers
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

logger.info("Starting polling...")

# 🔁 Run polling instead of webhook
app.run_polling()
