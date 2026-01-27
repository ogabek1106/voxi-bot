# bot.py
import os
import logging
from telegram.ext import CallbackQueryHandler
from handlers import global_text_gate
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
import handlers
from features.sub_check import check_subscription_callback
from debug_dispatcher import enable_dispatcher_debug
enable_dispatcher_debug()
from handlers import numeric_message_handler, global_fallback_handler

from features.track_commands import track_command   # ✅ ADD THIS

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

    # 🚪 GLOBAL COMMAND DOOR (MUST BE FIRST)
    #dp.add_handler(
    #    MessageHandler(Filters.command, track_command),
    #    group=0
    #)
    # 🔒 GLOBAL SUBSCRIPTION GATE (MUST BE FIRST)
    dp.add_handler(
        MessageHandler(Filters.text & ~Filters.command, global_text_gate),
        group=-100
    )
    # core handlers (unchanged)
    # 2601dp.add_handler(CommandHandler("start", handlers.start_handler, pass_args=True))
    # 2601dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handlers.numeric_message_handler))
    # /start
    dp.add_handler(CommandHandler("start", handlers.start_handler, pass_args=True), group=0)

    # FREE numeric input (books)
    dp.add_handler(
        MessageHandler(Filters.text & ~Filters.command, numeric_message_handler),
        group=10
    )

    # GLOBAL FALLBACK — MUST BE LAST
    # subscription check callback (ONE-TIME global)
    dp.add_handler(
        CallbackQueryHandler(check_subscription_callback, pattern="^check_sub$")
    )

    # ONE-TIME: load all features from features/ (each feature should expose setup(dp, bot) or register_handlers(dp))
    if register_all_features:
        try:
            register_all_features(dp)
            logger.info("Loaded feature modules from features/")
        except Exception as e:
            logger.exception("Failed to load features: %s", e)
    else:
        logger.warning("features.register_all_features not available. No feature modules loaded.")

    # 🔚 GLOBAL FALLBACK — ABSOLUTELY LAST
    #dp.add_handler(
    #    MessageHandler(Filters.text & ~Filters.command, global_fallback_handler),
    #    group=99
    #)
    
    logger.info("Bot starting polling...")
    updater.start_polling()
    updater.idle()


# ENTRY POINT
if __name__ == "__main__":
    main()
