import re
from typing import Dict, List


HASHTAG_RE = re.compile(r"(?<![\w])#[A-Za-z0-9_]+")
EMOJI_RE = re.compile(
    "["
    "\U0001f300-\U0001f5ff"
    "\U0001f600-\U0001f64f"
    "\U0001f680-\U0001f6ff"
    "\U0001f700-\U0001f77f"
    "\U0001f780-\U0001f7ff"
    "\U0001f800-\U0001f8ff"
    "\U0001f900-\U0001f9ff"
    "\U0001fa00-\U0001fa6f"
    "\U0001fa70-\U0001faff"
    "\u2600-\u27bf"
    "]"
)


CTA_HINTS = (
    "?",
    "comment",
    "share",
    "save",
    "write",
    "send",
    "try",
    "which",
    "what",
    "qaysi",
    "yozing",
    "izoh",
    "saqlab",
)

FOOTER_HINTS = (
    "telegram",
    "vocabulary",
    "voxi",
    "web-site",
    "website",
    "sharing is caring",
)


def count_tag(text: str, tag_names: tuple[str, ...]) -> int:
    names = "|".join(re.escape(name) for name in tag_names)
    return len(re.findall(rf"<\s*({names})(\s+[^>]*)?>", text or "", flags=re.IGNORECASE))


def detect_formatting_pattern(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    patterns = []
    for index, line in enumerate(lines[:12], start=1):
        tags = []
        if re.search(r"<\s*(b|strong)(\s+[^>]*)?>", line, flags=re.IGNORECASE):
            tags.append("bold")
        if re.search(r"<\s*(i|em)(\s+[^>]*)?>", line, flags=re.IGNORECASE):
            tags.append("italic")
        if tags:
            clean = re.sub(r"<[^>]+>", "", line)
            patterns.append(f"line {index}: {','.join(tags)} -> {clean[:80]}")
    return "\n".join(patterns)[-700:]


def extract_hashtags(text: str) -> List[str]:
    seen = set()
    out = []
    for tag in HASHTAG_RE.findall(text or ""):
        normalized = tag.strip()
        key = normalized.lower()
        if key not in seen:
            seen.add(key)
            out.append(normalized)
    return out


def count_emoji(text: str) -> int:
    return len(EMOJI_RE.findall(text or ""))


def detect_footer_pattern(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    tail = lines[-5:]
    matches = [
        line
        for line in tail
        if any(hint in line.lower() for hint in FOOTER_HINTS)
    ]
    return "\n".join(matches)[-700:]


def detect_cta_pattern(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    matches = [
        line
        for line in lines[-8:]
        if any(hint in line.lower() for hint in CTA_HINTS)
    ]
    return "\n".join(matches[-3:])[-500:]


def estimate_language_ratio(text: str) -> str:
    words = re.findall(r"[A-Za-z']+|[A-Za-z\u02bc']+", text or "")
    latin = len(words)
    uzbek_markers = len(
        re.findall(
            r"\b(degani|ma'nosi|misol|ya'ni|uchun|bilan|qanday|qachon|bo'ladi|ishlatiladi|tarjima)\b",
            text or "",
            flags=re.IGNORECASE,
        )
    )
    if not text:
        return "unknown"
    if uzbek_markers <= max(1, latin // 35):
        return "mostly_english"
    if uzbek_markers <= max(2, latin // 18):
        return "english_with_short_uzbek"
    return "uzbek_heavy"


def analyze_style(text: str) -> Dict[str, object]:
    return {
        "hashtags": extract_hashtags(text),
        "emoji_count": count_emoji(text),
        "bold_count": count_tag(text, ("b", "strong")),
        "italic_count": count_tag(text, ("i", "em")),
        "formatting_pattern": detect_formatting_pattern(text),
        "footer_pattern": detect_footer_pattern(text),
        "cta_pattern": detect_cta_pattern(text),
        "language_ratio": estimate_language_ratio(text),
    }
