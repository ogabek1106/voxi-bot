# features/asd_command.py
"""
/asd — Admin debug command (Aiogram 3)

Shows:
1) Commands registered in Telegram (bot command menu)
2) Static scan of repo for Command(...) occurrences (debug only)

NOTE:
Aiogram 3 has NO dispatcher handler introspection like PTB.
Telegram command registry is the ONLY reliable runtime source.
"""

import os
import re
import logging
from typing import List, Tuple, Set

from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from admins import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router()

TG_MSG_MAX = 3800
SKIP_DIRS = {
    "venv", ".venv", ".git", "__pycache__", "node_modules",
    ".nixpacks", ".mypy_cache"
}

# Static patterns (PTB + Aiogram)
CMD_PATTERNS = [
    re.compile(r"Command\(\s*[\"']([a-zA-Z0-9_]+)[\"']"),
    re.compile(r"CommandHandler\(\s*[\"']/?([a-zA-Z0-9_]+)[\"']"),
]


# ─────────────────────────────
# utils
# ─────────────────────────────

def is_admin(user_id: int) -> bool:
    return int(user_id) in set(map(int, ADMIN_IDS))


def chunk_text(text: str, limit: int = TG_MSG_MAX) -> List[str]:
    parts = []
    while text:
        if len(text) <= limit:
            parts.append(text)
            break
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip()
    return parts


def scan_file(path: str) -> List[Tuple[str, int]]:
    found = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f, start=1):
                for pat in CMD_PATTERNS:
                    m = pat.search(line)
                    if m:
                        found.append((m.group(1), i))
    except Exception:
        pass
    return found


def scan_repo(root=".") -> List[Tuple[str, str, int]]:
    out = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in fns:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, root)
            for cmd, ln in scan_file(full):
                out.append((cmd, rel, ln))
    return out


# ─────────────────────────────
# /asd
# ─────────────────────────────

@router.message(Command("asd"))
async def asd_handler(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await message.answer("🔎 Collecting command info…")

    # 1️⃣ Runtime commands (Telegram is the truth in Aiogram 3)
    tg_cmds = await message.bot.get_my_commands()
    runtime_cmds: Set[str] = {c.command for c in tg_cmds}

    lines = ["📡 *Telegram-registered commands:*"]
    if runtime_cmds:
        for c in sorted(tg_cmds, key=lambda x: x.command):
            lines.append(f"/{c.command} — {c.description or 'no description'}")
    else:
        lines.append("_No commands registered via set_my_commands()_")

    # 2️⃣ Static repo scan
    scan = scan_repo(os.getcwd())
    missing = [(cmd, f, ln) for cmd, f, ln in scan if cmd not in runtime_cmds]

    lines.append("")
    lines.append("📁 *Static scan (commands NOT in Telegram registry):*")

    if missing:
        for cmd, f, ln in sorted(missing, key=lambda x: x[0]):
            lines.append(f"/{cmd} — {f}:{ln}")
    else:
        lines.append("_No extra commands found._")

    report = "\n".join(lines)
    for part in chunk_text(report):
        await message.answer(part)

