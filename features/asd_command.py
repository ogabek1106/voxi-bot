# features/asd_command.py
"""
Improved /asd: show runtime-registered commands (human-friendly) and optionally scan repo for CommandHandler occurrences.

Behavior:
 1. Inspect dispatcher handlers to list *actual* CommandHandler-registered commands.
 2. Deduplicate and present: /cmd — module.function  (group: N)
 3. Then run a lightweight scan of .py files to find CommandHandler("name", ...) occurrences
    that are not present in runtime list (helps debug why an expected command isn't active).
 4. Admin-only.

Works for PTB v13/v12-ish (uses introspection, not private internals).
"""

import os
import re
import logging
from typing import List, Tuple, Dict, Set
from global_checker import allow
from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

import admins

logger = logging.getLogger(__name__)

ADMIN_IDS = set(int(x) for x in getattr(admins, "ADMIN_IDS", getattr(admins, "ADMINS", [])) or [])

SKIP_DIRS = {"venv", ".venv", ".git", "__pycache__", "node_modules", ".nixpacks", ".mypy_cache"}
TG_MSG_MAX = 3800

CMD_PATTERNS = [
    re.compile(r"CommandHandler\(\s*['\"]/?([a-zA-Z0-9_/]+)['\"]"),
    re.compile(r"add_handler\([^)]*CommandHandler\(\s*['\"]/?([a-zA-Z0-9_/]+)['\"]"),
]


def _is_admin(user_id: int) -> bool:
    try:
        return int(user_id) in ADMIN_IDS
    except Exception:
        return False


def _chunk_text(text: str, limit: int = TG_MSG_MAX) -> List[str]:
    parts = []
    while text:
        if len(text) <= limit:
            parts.append(text)
            break
        idx = text.rfind("\n", 0, limit)
        if idx <= 0:
            idx = limit
        parts.append(text[:idx])
        text = text[idx:].lstrip("\n")
    return parts


def _scan_file_for_commands(path: str) -> List[Tuple[str, int, str]]:
    found = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f, start=1):
                for pat in CMD_PATTERNS:
                    m = pat.search(line)
                    if m:
                        cmd = m.group(1).lstrip("/")
                        excerpt = line.strip()[:240]
                        found.append((cmd, i, excerpt))
    except Exception:
        logger.debug("asd_command: failed to scan %s", path, exc_info=True)
    return found


def _scan_repo(root: str = ".") -> Tuple[List[str], List[Tuple[str, int, str, str]]]:
    files = []
    results = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(dirpath, fn)
            if "/site-packages/" in full or "\\site-packages\\" in full:
                continue
            rel = os.path.relpath(full, root)
            files.append(rel)
            cmds = _scan_file_for_commands(full)
            for cmd, lineno, excerpt in cmds:
                results.append((rel, lineno, cmd, excerpt))
    return files, results


def _get_runtime_commands(dispatcher) -> Dict[str, Dict]:
    """
    Inspect dispatcher and return mapping:
      command -> { 'handlers': [(module, qualname, group), ...], 'groups': set(...) }
    This tries to be robust across PTB versions by introspecting handler objects.
    """
    out: Dict[str, Dict] = {}
    try:
        # dispatcher.handlers is a dict of group -> [handlers...]
        handlers_map = getattr(dispatcher, "handlers", None)
        if handlers_map is None:
            # older/newer PTB differences: try dispatcher._handlers or dispatcher._queue? fallback: empty
            handlers_map = getattr(dispatcher, "handler_list", None) or {}
        if isinstance(handlers_map, dict):
            items = handlers_map.items()
        else:
            # sometimes dispatcher.handlers is list-like; try enumerating
            try:
                items = list(enumerate(handlers_map))  # type: ignore[arg-type]
            except Exception:
                items = []

        for group, handlers in items:
            try:
                for h in handlers:
                    # Identify CommandHandler by class name (robust)
                    clsname = h.__class__.__name__
                    if clsname not in ("CommandHandler", "PrefixHandler", "RegexHandler", "Handler"):
                        # still check for common CommandHandler attributes
                        pass
                    # many CommandHandler instances have attribute .command or .commands
                    cmds = []
                    if hasattr(h, "command"):
                        c = getattr(h, "command")
                        if isinstance(c, (list, tuple)):
                            cmds.extend([str(x).lstrip("/") for x in c])
                        else:
                            try:
                                cmds.append(str(c).lstrip("/"))
                            except Exception:
                                pass
                    if not cmds and hasattr(h, "commands"):
                        c = getattr(h, "commands")
                        if isinstance(c, (list, tuple)):
                            cmds.extend([str(x).lstrip("/") for x in c])
                    # fallback: inspect handler.callback function name if it's a wrapper that registers a single command
                    if not cmds:
                        # some setups store the command in .filters or .pattern: skip for now
                        pass

                    # If this looks like a command handler, register it
                    if cmds:
                        for cmd in cmds:
                            rec = out.setdefault(cmd, {"handlers": [], "groups": set()})
                            # try to get callback info
                            modname = None
                            qual = None
                            try:
                                cb = getattr(h, "callback", None) or getattr(h, "handler", None) or getattr(h, "callback", None)
                                if cb:
                                    f = cb
                                    # for Handler objects in PTB sometimes .callback is a function or a tuple
                                    if hasattr(f, "__module__") and hasattr(f, "__name__"):
                                        modname = f.__module__
                                        qual = f.__name__
                                    else:
                                        # try to get callable's __call__
                                        call = getattr(f, "__call__", None)
                                        if call and hasattr(call, "__module__"):
                                            modname = call.__module__
                                            qual = getattr(call, "__name__", None)
                            except Exception:
                                pass
                            rec["handlers"].append((modname or "<unknown>", qual or "<callable>", int(group)))
                            rec["groups"].add(int(group))
                    else:
                        # some CommandHandler implementations might store command names in .patterns or .filters
                        # best-effort: if class name is CommandHandler but no command attr found, still record as unknown
                        if h.__class__.__name__ == "CommandHandler":
                            cmdname = "<unknown>"
                            rec = out.setdefault(cmdname, {"handlers": [], "groups": set()})
                            rec["handlers"].append((None, None, int(group)))
                            rec["groups"].add(int(group))
            except Exception:
                logger.debug("Error processing handlers in group %r", group, exc_info=True)
        return out
    except Exception:
        logger.exception("Failed to introspect dispatcher handlers", exc_info=True)
        return out


def asd_handler(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user:
        return

    # 🔐 FREE-STATE REQUIRED (ADMIN TOOL)
    if not allow(user.id, mode=None):
        return

    if not _is_admin(user.id):
        logger.info("asd: unauthorized /asd by %r", getattr(user, "id", None))
        return

    chat_id = update.effective_chat.id
    dispatcher = context.dispatcher

    try:
        context.bot.send_message(chat_id=chat_id, text="🔎 Gathering runtime commands... please wait.")
    except Exception:
        pass

    runtime = _get_runtime_commands(dispatcher)
    # create human-friendly summary
    if runtime:
        lines = ["📡 Runtime-registered commands:"]
        seen_cmds: Set[str] = set()
        for cmd in sorted(runtime.keys()):
            info = runtime[cmd]
            handlers = info.get("handlers", [])
            groups = sorted(info.get("groups", []))
            # choose the first handler as canonical for display
            first = handlers[0] if handlers else (None, None, None)
            mod, qual, grp = first
            mod = mod or "<unknown>"
            qual = qual or "<callable>"
            lines.append(f"/{cmd}  — {mod}.{qual}  (groups: {','.join(map(str, groups))})")
            seen_cmds.add(cmd)
    else:
        lines = ["No runtime CommandHandler instances found (dispatcher introspection returned empty)."]

    # now do a repo scan to find CommandHandler("name", ...) occurrences not present at runtime
    try:
        root = os.getcwd() or "."
        files, scan_results = _scan_repo(root)
        missing = []
        for filepath, lineno, cmd, excerpt in scan_results:
            if cmd not in seen_cmds:
                missing.append((cmd, filepath, lineno, excerpt))
        if missing:
            lines.append("")
            lines.append("📁 Scanner found CommandHandler(...) usages NOT present in runtime list:")
            for cmd, filepath, lineno, excerpt in sorted(missing, key=lambda x: x[0]):
                lines.append(f"/{cmd}  — {filepath}:{lineno}")
        else:
            lines.append("")
            lines.append("Scanner found no extra CommandHandler(...) occurrences missing from runtime registry.")
        # also show features/ files (quick view)
        feat_dir = os.path.join(root, "features")
        if os.path.isdir(feat_dir):
            try:
                feat_files = sorted([f for f in os.listdir(feat_dir) if f.endswith(".py")])
                lines.append("")
                lines.append("Files in features/:")
                for f in feat_files:
                    lines.append(f"- {f}")
            except Exception:
                pass
    except Exception:
        logger.exception("asd: repo scan failed", exc_info=True)

    report = "\n".join(lines)
    for part in _chunk_text(report):
        try:
            context.bot.send_message(chat_id=chat_id, text=part, parse_mode="Markdown")
        except Exception:
            try:
                context.bot.send_message(chat_id=chat_id, text=part)
            except Exception:
                logger.exception("asd: failed to send report chunk")

def setup(dispatcher, bot=None):
    dispatcher.add_handler(CommandHandler("asd", ))
    logger.info("asd_command loaded. Admins=%r", sorted(list(ADMIN_IDS)))
