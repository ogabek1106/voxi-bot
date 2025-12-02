# features/deep_link.py
"""
Small feature to reliably handle deep links like:
  https://t.me/YOUR_BOT_USERNAME?start=get_test

Approach:
 - Register an early /start handler (group=-50) that handles payload "get_test"
 - Monkey-patch core handlers.start_handler to route "get_test" payloads to the
   test_form.get_test_handler as well (covers cases where core already referenced
   the original function).
This is minimally invasive and only affects start/deep-link routing.
"""

import logging
from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

logger = logging.getLogger(__name__)


def _dispatch_get_test(update: Update, context: CallbackContext):
    """
    Call the test_form.get_test_handler if available.
    """
    try:
        # import lazily to avoid import cycles during feature discovery
        from features import test_form
    except Exception:
        logger.exception("deep_link: cannot import features.test_form")
        return

    try:
        # call the same handler used for /get_test
        return test_form.get_test_handler(update, context)
    except Exception:
        logger.exception("deep_link: test_form.get_test_handler raised an exception")


def _new_start_handler_factory(original_start_fn):
    """
    Create a start handler that intercepts payload 'get_test' and forwards to
    test_form.get_test_handler. If payload is not 'get_test', call original_start_fn.
    """
    def _start_handler(update: Update, context: CallbackContext):
        args = context.args if getattr(context, "args", None) is not None else []
        if args and str(args[0]).strip().lower() == "get_test":
            # intercepted deep link -> dispatch to test form
            try:
                return _dispatch_get_test(update, context)
            except Exception:
                logger.exception("deep_link: failed dispatching get_test")
                # fall through to original handler as a fallback
        # not our payload -> call original (safe)
        try:
            return original_start_fn(update, context)
        except Exception:
            # If original fails, at least ensure we don't crash the bot
            logger.exception("deep_link: original start handler raised an exception")
    return _start_handler


def setup(dispatcher):
    """
    Install the deep link handler and monkey-patch core handlers.start_handler.
    Register our /start handler in an early group so it runs before core's numeric handler.
    """
    # 1) Register early /start handler that only handles '?start=get_test'
    try:
        # Use a lightweight handler that checks payload and dispatches.
        dispatcher.add_handler(CommandHandler("start", _start_for_dispatch), group=-50)
    except Exception:
        # older PTB versions may not accept group arg here; still attempt to register normally
        try:
            dispatcher.add_handler(CommandHandler("start", _start_for_dispatch))
        except Exception:
            logger.exception("deep_link: failed to register start handler")

    # 2) Monkey-patch core handlers.start_handler if possible so any direct calls go through our dispatcher
    try:
        import handlers as core_handlers  # core file you showed earlier
        original = getattr(core_handlers, "start_handler", None)
        if original and original is not _start_for_dispatch:
            # replace core start_handler with a wrapper that intercepts get_test
            setattr(core_handlers, "start_handler", _new_start_handler_factory(original))
            logger.info("deep_link: patched core handlers.start_handler to intercept 'get_test' payload")
    except Exception:
        logger.exception("deep_link: failed to monkey-patch core handlers.start_handler")


# helper used for registering with dispatcher above
def _start_for_dispatch(update: Update, context: CallbackContext):
    """
    Dispatcher-registered start handler that only reacts to 'get_test' payload.
    If payload is different, do nothing so core's start_handler can still reply.
    """
    args = context.args if getattr(context, "args", None) is not None else []
    if args and str(args[0]).strip().lower() == "get_test":
        return _dispatch_get_test(update, context)
    # otherwise do nothing (allow core handler to respond)
    return
