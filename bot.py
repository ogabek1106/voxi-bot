# bot.py
import os
import logging
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
import handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")


def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", handlers.start_handler, pass_args=True))

    # 🔥 NEW: user sends "3" → bot sends book 3
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handlers.numeric_message_handler))

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
