import os
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)

# ✅ Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🔐 Env vars
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_DOMAIN = os.getenv("WEBHOOK_DOMAIN")

# 🔗 Webhook setup
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_DOMAIN}{WEBHOOK_PATH}"

logger.info(f"Bot token loaded: {BOT_TOKEN[:10]}...")
logger.info(f"Webhook URL will be: {WEBHOOK_URL}")

# ✅ Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("I hear you 👂")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📩 I received your message!")

# 🚀 Build app and add handlers
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

logger.info("Starting webhook application...")

# 🌐 Run webhook server
app.run_webhook(
    listen="0.0.0.0",
    port=int(os.environ.get("PORT", 8000)),
    webhook_url=WEBHOOK_URL,
    allowed_updates=["message", "callback_query"]
)
