# bot.py
import os
import logging
from telegram.ext import CallbackQueryHandler
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
import handlers
from global_checker import allow
from handlers import numeric_message_handler
from features.sub_check import check_subscription_callback
#from debug_dispatcher import enable_dispatcher_debug
#enable_dispatcher_debug()

#from features.track_commands import track_command   

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

def numeric_message_router(update, context):
    user = update.effective_user
    if not user:
        return

    # ✅ ONLY FREE / NONE STATE
    if not allow(user.id, mode=None):
        return

    return numeric_message_handler(update, context)

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", handlers.start_handler, pass_args=True))

    dp.add_handler(
        MessageHandler(Filters.text & ~Filters.command, numeric_message_router)
    )

    dp.add_handler(
        CallbackQueryHandler(check_subscription_callback, pattern="^check_sub$")
    )
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
