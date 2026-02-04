# features/__init__.py
import os
import importlib
import logging
from aiogram import Router
#from aiogram.dispatcher.dispatcher import Dispatcher
from aiogram import Dispatcher

logger = logging.getLogger(__name__)


def register_all_features(dp: Dispatcher):
    """
    Aiogram 3 feature loader.

    Rules:
    - A feature is loaded ONLY if it exposes `router: Router`
    - No setup(), no register_handlers()
    - Import failures are logged and skipped
    - Safe for mixed (PTB + Aiogram) migration stage
    """

    folder = os.path.dirname(__file__)
    logger.info("Feature loader scanning folder: %s", folder)

    for root, _, files in os.walk(folder):
        for file in sorted(files):
            if not file.endswith(".py") or file == "__init__.py":
                continue

            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, folder)
            module_name = rel_path.replace(os.sep, ".")[:-3]
            full_name = f"features.{module_name}"

            try:
                module = importlib.import_module(full_name)
            except Exception as e:
                logger.exception("Failed to import feature module %s: %s", full_name, e)
                continue

            # ─────────────────────────────
            # Aiogram 3 rule: router only
            # ─────────────────────────────
            router = getattr(module, "router", None)

            if isinstance(router, Router):
                dp.include_router(router)
                logger.info("Loaded feature router: %s", full_name)
            else:
                logger.info(
                    "Skipped module %s (no aiogram router found)",
                    full_name,
                )
