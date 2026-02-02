# bot.py
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from features.global_cancel import router as global_cancel_router
from features.user_tracker import setup_middleware

from handlers import router as core_router
from features.sub_check import router as sub_check_router

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


# ─────────────────────────────
# Main entry
# ─────────────────────────────

async def main():
    bot = Bot(token=TOKEN, parse_mode="HTML")

    dp = Dispatcher(storage=MemoryStorage())

     # ── MIDDLEWARES ──
    setup_middleware(dp)
    
    # ── Core routers ──
    dp.include_router(core_router)

    # ── Feature routers ──
    dp.include_router(sub_check_router)   # ✅ REQUIRED

    if register_all_features:
        try:
            register_all_features(dp)
            logger.info("Loaded feature modules from features/")
        except Exception as e:
            logger.exception("Failed to load features: %s", e)
    else:
        logger.warning("features.register_all_features not available. No feature modules loaded.")

    # ── GLOBAL routers (MUST BE LAST) ──
    #dp.include_router(global_cancel_router)

    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Botni ishga tushirish"),
            BotCommand(command="all_books", description="Mavjud kitoblar ro'yxati"),
        ])
    except Exception:
        pass

    logger.info("Bot starting polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
