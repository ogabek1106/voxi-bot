# bot.py
import os
import logging

from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
import handlers

# import our features autoloader (must exist: features/__init__.py with register_all_features)
try:
    from features import register_all_features
except Exception:
    register_all_features = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    logger.error("BOT_TOKEN env var is not set. Exiting.")
    raise SystemExit("BOT_TOKEN missing")


def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # core handlers (unchanged)
    dp.add_handler(CommandHandler("start", handlers.start_handler, pass_args=True))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handlers.numeric_message_handler))

    # ONE-TIME: load all features from features/ (each feature should expose setup(dp, bot) or register_handlers(dp))
    if register_all_features:
        try:
            register_all_features(dp)
            logger.info("Loaded feature modules from features/")
        except Exception as e:
            logger.exception("Failed to load features: %s", e)
    else:
        logger.warning("features.register_all_features not available. No feature modules loaded.")

    logger.info("Bot starting polling...")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
