from telegram.ext.dispatcher import Dispatcher
from functools import wraps

_original_process_update = Dispatcher.process_update

def patched_process_update(self, update):
    for group in sorted(self.handlers.keys()):
        for handler in self.handlers[group]:
            try:
                if handler.check_update(update):
                    cb = handler.callback
                    name = getattr(cb, "__name__", str(cb))
                    module = getattr(cb, "__module__", "unknown")

                    print(
                        f"🔥 UPDATE CONSUMED\n"
                        f"  group: {group}\n"
                        f"  handler: {handler.__class__.__name__}\n"
                        f"  callback: {name}\n"
                        f"  module: {module}"
                    )

                    handler.handle_update(update, self, check_result=None)
                    return  # ← EXACT consumer, stop here
            except Exception as e:
                print("DEBUG PATCH ERROR:", e)

    # fallback (should not happen)
    _original_process_update(self, update)

def enable_dispatcher_debug():
    Dispatcher.process_update = patched_process_update
