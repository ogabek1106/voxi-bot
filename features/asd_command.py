# features/asd_command.py
"""
Admin-only /asd command: discover available commands in the repo.

Usage:
 - /asd        -> bot will scan the repository for CommandHandler(...) usages
                 and return a report to the admin who invoked it.

Notes:
 - This is read-only and only available to admin IDs defined in admins.ADMIN_IDS.
 - Scans recursively from current working directory (os.getcwd()) and skips common
   directories that would be noisy (venv, .git, __pycache__, node_modules).
 - Output is chunked into Telegram-safe message sizes.
"""

import os
import re
import logging
from typing import List, Tuple

from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

import admins

logger = logging.getLogger(__name__)

ADMIN_IDS = set(int(x) for x in getattr(admins, "ADMIN_IDS", getattr(admins, "ADMINS", [])) if x)

# directories to skip during recursive scan
SKIP_DIRS = {"venv", ".venv", ".git", "__pycache__", "node_modules", ".nixpacks", ".mypy_cache"}

# regex patterns to find CommandHandler definitions and dispatcher.add_handler usages.
# It handles simple cases like:
#   CommandHandler("stats", stats_handler)
#   dispatcher.add_handler(CommandHandler("stats", stats_handler))
#   CommandHandler('start', handlers.start_handler, pass_args=True)
CMD_PATTERNS = [
    re.compile(r"CommandHandler\(\s*['\"]/?([a-zA-Z0-9_/]+)['\"]"),  # CommandHandler("cmd"
    re.compile(r"add_handler\([^)]*CommandHandler\(\s*['\"]/?([a-zA-Z0-9_/]+)['\"]"),  # add_handler(...CommandHandler("cmd"
]


TG_MSG_MAX = 3800  # safe chunk for Telegram message payload


def _is_admin(user_id: int) -> bool:
    try:
        return int(user_id) in ADMIN_IDS
    except Exception:
        return False


def _scan_file_for_commands(path: str) -> List[Tuple[str, int, str]]:
    """
    Scan a single file for command patterns.
    Returns list of tuples: (command, lineno, excerpt)
    """
    found = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f, start=1):
                for pat in CMD_PATTERNS:
                    m = pat.search(line)
                    if m:
                        cmd = m.group(1).lstrip("/")
                        # include a small excerpt
                        excerpt = line.strip()[:240]
                        found.append((cmd, i, excerpt))
    except Exception as e:
        logger.debug("asd_command: failed to scan %s: %s", path, e)
    return found


def _scan_repo(root: str) -> Tuple[List[str], List[Tuple[str, int, str, str]]]:
    """
    Recursively scan root for .py files and return:
      - list_of_files (for quick overview)
      - list_of_results: tuples (filepath, lineno, command, excerpt)
    """
    files = []
    results = []
    for dirpath, dirnames, filenames in os.walk(root):
        # mutate dirnames in-place to skip certain dirs
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(dirpath, fn)
            # small filter: ignore installed libs if path includes site-packages
            if "/site-packages/" in full or "\\site-packages\\" in full:
                continue
            files.append(os.path.relpath(full, root))
            cmds = _scan_file_for_commands(full)
            for cmd, lineno, excerpt in cmds:
                results.append((os.path.relpath(full, root), lineno, cmd, excerpt))
    return files, results


def _chunk_text(text: str, limit: int = TG_MSG_MAX) -> List[str]:
    parts = []
    while text:
        if len(text) <= limit:
            parts.append(text)
            break
        # try to split at newline before limit
        idx = text.rfind("\n", 0, limit)
        if idx <= 0:
            idx = limit
        parts.append(text[:idx])
        text = text[idx:].lstrip("\n")
    return parts


def asd_handler(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user:
        return
    if not _is_admin(user.id):
        logger.info("asd_command: non-admin %s attempted /asd", user.id)
        # silent for non-admins
        return

    chat_id = update.effective_chat.id
    # Inform admin we're scanning
    try:
        context.bot.send_message(chat_id=chat_id, text="🔎 Scanning repository for CommandHandler usages... This may take a few seconds.")
    except Exception:
        pass

    root = os.getcwd() or "."

    files, results = _scan_repo(root)

    # Build report
    lines = []
    lines.append(f"Repository root: `{root}`")
    lines.append(f"Total python files scanned: {len(files)}")
    lines.append("")
    if not results:
        lines.append("No CommandHandler(...) occurrences found by basic scanner.")
        lines.append("Note: the scanner looks for simple `CommandHandler(\"cmd\", ...)` patterns in .py files.")
        lines.append("If your features register commands dynamically or use variables, they may not be detected.")
    else:
        lines.append(f"Found {len(results)} CommandHandler occurrences:\n")
        for filepath, lineno, cmd, excerpt in results:
            lines.append(f"- `{cmd}`  — {filepath}:{lineno}")
            # optionally include excerpt for debugging (short)
            lines.append(f"    `{excerpt}`")

    # Also include a quick list of top-level files in features/ (if exists)
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

    report = "\n".join(lines)

    # chunk and send
    for part in _chunk_text(report):
        try:
            context.bot.send_message(chat_id=chat_id, text=part, parse_mode="Markdown")
        except Exception as e:
            # fallback: send without markdown if parse error
            try:
                context.bot.send_message(chat_id=chat_id, text=part)
            except Exception:
                logger.exception("asd_command: failed to send report chunk: %s", e)


def setup(dispatcher, bot=None):
    dispatcher.add_handler(CommandHandler("asd", asd_handler))
    logger.info("asd_command loaded. Admins=%r", sorted(list(ADMIN_IDS)))
