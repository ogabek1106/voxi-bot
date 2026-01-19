"""
features/bold_font.py

Small helper that monkey-patches Bot methods so text/captions containing
Markdown-style bold markers (*...*) are sent/edited with parse_mode="Markdown".

It is intentionally conservative:
 - if caller explicitly provided parse_mode (not None) we don't touch it.
 - only injects parse_mode when it detects a simple '*text*' pattern.
 - preserves original method signatures and behavior otherwise.

Usage:
 - Place this file in features/
 - The bot's features autoloader should call setup(dispatcher) automatically.
"""

import logging
import re
from functools import wraps
from telegram import Bot
from telegram.ext import Dispatcher

logger = logging.getLogger(__name__)

# Simple regex: looks for *some text* (not greedy). Avoid matching lone asterisks.
_BOLD_SIMPLE_RE = re.compile(r"\*[^*\n]+\*")

# List of Bot methods to patch and where the textual payload lives:
# method_name -> (argument_name_for_text_or_caption,)
# send_message -> text
# edit_message_text -> text
# send_document -> caption
# send_photo, send_audio, send_video, send_animation -> caption (often used)
PATCH_TARGETS = {
    "send_message": ("text",),
    "edit_message_text": ("text",),
    "send_document": ("caption",),
    "send_photo": ("caption",),
    "send_audio": ("caption",),
    "send_video": ("caption",),
    "send_animation": ("caption",),
    "edit_message_caption": ("caption",),
    "send_media_group": (),  # media group is a bit special — skip automatic handling
}


def _contains_bold_marker(s: str) -> bool:
    try:
        if not s:
            return False
        return bool(_BOLD_SIMPLE_RE.search(s))
    except Exception:
        return False


def _patch_method(func_name: str):
    """
    Return a decorator that wraps Bot.<func_name>.
    The wrapper will insert parse_mode='Markdown' when:
      - caller did NOT provide parse_mode (or provided None)
      - the text/caption argument contains '*...*' pattern
    """
    def decorator(orig_fn):
        @wraps(orig_fn)
        def wrapper(*args, **kwargs):
            try:
                # --- LISTENING / AI SAFE BYPASS ---
                if kwargs.get("_no_bold_patch", False):
                    return orig_fn(*args, **kwargs)

                # If parse_mode explicitly set (and not None), respect caller
                if "parse_mode" in kwargs and kwargs.get("parse_mode") is not None:
                    return orig_fn(*args, **kwargs)

                # Find textual argument(s) (kwargs first)
                targets = PATCH_TARGETS.get(func_name, ())
                text_val = None
                for name in targets:
                    if name in kwargs:
                        text_val = kwargs.get(name)
                        break

                # If not in kwargs, try to infer from positional args by signature position:
                # This is heuristic: for send_message(chat_id, text, ...), text is pos 1 (args[1])
                if text_val is None and args:
                    # map common signatures heuristically
                    if func_name in ("send_message", "edit_message_text"):
                        # typical signature: (bot, chat_id, text, ...)
                        # but when bound method called via instance, args[0] is self (Bot)
                        if len(args) >= 3:
                            text_val = args[2]
                    elif func_name in ("send_document", "send_photo", "send_audio", "send_video", "send_animation"):
                        # typical signature: (bot, chat_id, document/photo, caption=...)
                        # can't reliably get caption from positional args for media; rely on kwargs
                        text_val = None
                    elif func_name == "edit_message_caption":
                        # signature: (bot, caption=..., chat_id=..., message_id=...)
                        # rely on kwargs
                        text_val = None

                if isinstance(text_val, str) and _contains_bold_marker(text_val):
                    # inject parse_mode only if not set
                    kwargs.setdefault("parse_mode", "Markdown")

            except Exception:
                # Be safe: on any error do not break original behaviour
                logger.exception("bold_font: patch wrapper error for %s", func_name)

            return orig_fn(*args, **kwargs)
        return wrapper
    return decorator


_originals = {}


def enable_bold_on_bot():
    """
    Apply monkey-patch to telegram.Bot methods listed in PATCH_TARGETS.
    Safe to call multiple times (idempotent).
    """
    for method_name in list(PATCH_TARGETS.keys()):
        try:
            orig = getattr(Bot, method_name, None)
            if not orig:
                continue

            # If already patched (we stored original), skip
            if method_name in _originals:
                continue

            wrapped = _patch_method(method_name)(orig)
            _originals[method_name] = orig
            setattr(Bot, method_name, wrapped)
            logger.info("bold_font: patched Bot.%s", method_name)
        except Exception:
            logger.exception("bold_font: failed to patch Bot.%s", method_name)


def disable_bold_on_bot():
    """Restore original Bot methods (if we patched them)."""
    for method_name, orig in list(_originals.items()):
        try:
            setattr(Bot, method_name, orig)
            logger.info("bold_font: restored Bot.%s", method_name)
            _originals.pop(method_name, None)
        except Exception:
            logger.exception("bold_font: failed to restore Bot.%s", method_name)


# feature setup called by your feature loader
def setup(dispatcher: Dispatcher):
    try:
        enable_bold_on_bot()
    except Exception:
        logger.exception("bold_font setup failed")
