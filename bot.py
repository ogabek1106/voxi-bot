# bot.py
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramNetworkError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
#from features.global_cancel import router as global_cancel_router
from features.user_tracker import setup_middleware

from handlers import router as core_router
# from features.sub_check import router as sub_check_router
from features.content_engine.api_server import start_api_server
from features.content_engine.resource_processor import start_pending_processing
from features.content_engine.scheduler import start_scheduler

try:
    from features import register_all_features
except Exception:
    register_all_features = None


# ─────────────────────────────
# Logging
# ─────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


# ─────────────────────────────
# Environment
# ─────────────────────────────

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    logger.error("BOT_TOKEN env var is not set. Exiting.")
    raise SystemExit("BOT_TOKEN missing")

POLLING_RETRY_SECONDS = int(os.getenv("POLLING_RETRY_SECONDS", "15"))
CONTENT_ENGINE_BACKGROUND_START_DELAY = int(
    os.getenv("CONTENT_ENGINE_BACKGROUND_START_DELAY", "20")
)


async def _start_content_engine_background(bot: Bot):
    await asyncio.sleep(CONTENT_ENGINE_BACKGROUND_START_DELAY)
    start_scheduler(bot)
    start_pending_processing()


async def _start_content_engine_api():
    runner = None
    try:
        runner = await start_api_server()
        await asyncio.Event().wait()
    except Exception as e:
        logger.exception("Content Engine API server failed to start: %s", e)
    finally:
        if runner:
            await runner.cleanup()


# ─────────────────────────────
# Main entry
# ─────────────────────────────

async def main():
    bot = Bot(token=TOKEN, parse_mode="HTML")

    dp = Dispatcher(storage=MemoryStorage())

    # ── MIDDLEWARES ──
    setup_middleware(dp)

    # ── Feature routers ──
    if register_all_features:
        try:
            register_all_features(dp)
            logger.info("Loaded feature modules from features/")
        except Exception as e:
            logger.exception("Failed to load features: %s", e)
    else:
        logger.warning("features.register_all_features not available. No feature modules loaded.")

    # ── Core routers ──
    dp.include_router(core_router)

    # ── GLOBAL routers (MUST BE LAST) ──
    #dp.include_router(global_cancel_router)

    try:
        await asyncio.wait_for(
            bot.set_my_commands([
                BotCommand(command="start", description="Botni ishga tushirish"),
                BotCommand(command="all_books", description="Mavjud kitoblar ro'yxati"),
                BotCommand(command="content_status", description="Content Engine status"),
                BotCommand(command="generate_content_now", description="Generate one content draft"),
                BotCommand(command="content_queue", description="Pending content drafts"),
                BotCommand(command="pause_content", description="Pause content drafts"),
                BotCommand(command="resume_content", description="Resume content drafts"),
                BotCommand(command="upload_resource", description="Upload content resource"),
                BotCommand(command="upload_resource_link", description="Upload resource by URL"),
                BotCommand(command="upload_resource_local", description="Upload local resource"),
                BotCommand(command="resources", description="List content resources"),
                BotCommand(command="resource_status", description="Show resource processing status"),
                BotCommand(command="import_book_resource", description="Import one existing book"),
                BotCommand(command="import_all_books_resources", description="Import all existing books"),
                BotCommand(command="retry_book_resource", description="Retry failed book resource"),
                BotCommand(command="book_resources_status", description="Imported book resource status"),
                BotCommand(command="learn_post", description="Save a post style example"),
                BotCommand(command="style_examples", description="List saved style examples"),
                BotCommand(command="delete_style_example", description="Delete a style example"),
            ]),
            timeout=10,
        )
    except Exception as e:
        logger.warning("Could not set bot commands during startup: %s", e)

    asyncio.create_task(_start_content_engine_background(bot))
    asyncio.create_task(_start_content_engine_api())

    while True:
        try:
            logger.info("Bot starting polling...")
            await dp.start_polling(bot)
            return
        except TelegramNetworkError as e:
            logger.warning(
                "Telegram network error during polling: %s. Retrying in %s seconds.",
                e,
                POLLING_RETRY_SECONDS,
            )
            await asyncio.sleep(POLLING_RETRY_SECONDS)
        except asyncio.CancelledError:
            raise


if __name__ == "__main__":
    asyncio.run(main())

