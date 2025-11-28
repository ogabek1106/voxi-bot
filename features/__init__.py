#__init__.py
import os
import importlib

def register_all_features(dp):
    folder = os.path.dirname(__file__)

    for file in os.listdir(folder):
        if file.endswith(".py") and file not in ("__init__.py"):
            module_name = file[:-3]  # remove .py
            module = importlib.import_module(f"features.{module_name}")

            if hasattr(module, "register_handlers"):
                module.register_handlers(dp)
            elif hasattr(module, "register_stats_handlers"):
                module.register_stats_handlers(dp)
