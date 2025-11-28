# features/__init__.py
import os
import importlib
import logging

logger = logging.getLogger(__name__)

def register_all_features(dispatcher):
    folder = os.path.dirname(__file__)
    logger.info("Feature loader scanning folder: %s", folder)

    for file in sorted(os.listdir(folder)):
        if not file.endswith(".py") or file == "__init__.py":
            continue
        module_name = file[:-3]
        full_name = f"features.{module_name}"
        try:
            module = importlib.import_module(full_name)
        except Exception as e:
            logger.exception("Failed to import feature module %s: %s", full_name, e)
            continue

        # try common entrypoints
        try:
            if hasattr(module, "setup"):
                module.setup(dispatcher)
                logger.info("Loaded feature %s via setup()", full_name)
            elif hasattr(module, "register_handlers"):
                module.register_handlers(dispatcher)
                logger.info("Loaded feature %s via register_handlers()", full_name)
            elif hasattr(module, "register_stats_handlers"):
                module.register_stats_handlers(dispatcher)
                logger.info("Loaded feature %s via register_stats_handlers()", full_name)
            else:
                logger.info("Imported feature %s but no entrypoint found (setup/register_handlers)", full_name)
        except Exception as e:
            logger.exception("Feature %s setup failed: %s", full_name, e)
