import logging
import os
import re
from difflib import SequenceMatcher
from html import unescape
from typing import Dict, List, Optional

import openai

from . import storage
from .html_format import normalize_ai_output_html
from .style_analysis import extract_hashtags

logger = logging.getLogger(__name__)

MODEL = os.getenv("CONTENT_ENGINE_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
openai.api_key = os.getenv("OPENAI_API_KEY")


WEEKLY_PLAN = {
    0: "Word of the Day + 5 Underrated IELTS Collocations",
    1: "Grammar Tip + 5 High-Band Words/Phrases",
    2: "Idiom/Phrase + 5 Useful Academic Phrases",
    3: "PDF/Video Resource + 5 Powerful IELTS Verbs",
    4: "Quiz/Poll + Weekly Review + 5 Common IELTS Mistakes",
    5: "Music/Quote + 5 Advanced Synonyms",
    6: "Useful English Tip + Weekly Revision",
}

SLOT_WEEKLY_PLAN = {
    0: {
        "morning": "Word of the Day",
        "afternoon": "5 Underrated IELTS Collocations",
        "evening": "Light engagement/revision task based on Monday content",
    },
    1: {
        "morning": "Grammar Tip",
        "afternoon": "5 High-Band Words/Phrases",
        "evening": "Light quiz/task based on Tuesday content",
    },
    2: {
        "morning": "Idiom/Phrase",
        "afternoon": "5 Useful Academic Phrases",
        "evening": "Light practice/question based on Wednesday content",
    },
    3: {
        "morning": "PDF/Video Resource",
        "afternoon": "5 Powerful IELTS Verbs",
        "evening": "Light resource/practice task",
    },
    4: {
        "morning": "Quiz/Poll",
        "afternoon": "Weekly Review",
        "evening": "5 Common IELTS Mistakes",
    },
    5: {
        "morning": "Music/Quote",
        "afternoon": "5 Advanced Synonyms",
        "evening": "Light reflection/question",
    },
    6: {
        "morning": "Useful English Tip",
        "afternoon": "Weekly Revision",
        "evening": "Light weekly task/challenge",
    },
}

WEEKDAY_NAMES = {
    0: "Monday",
    1: "Tuesday",
    2: "Wednesday",
    3: "Thursday",
    4: "Friday",
    5: "Saturday",
    6: "Sunday",
}


def category_for_weekday(weekday_index: int) -> str:
    return WEEKLY_PLAN.get(weekday_index, WEEKLY_PLAN[0])


def category_for_slot(weekday_index: int, slot: str) -> str:
    clean_slot = (slot or "").strip().lower()
    if clean_slot in SLOT_WEEKLY_PLAN.get(weekday_index, {}):
        return SLOT_WEEKLY_PLAN[weekday_index][clean_slot]
    return category_for_weekday(weekday_index)


def weekday_name(weekday_index: int) -> str:
    return WEEKDAY_NAMES.get(weekday_index, "Monday")


def style_category_for_plan(category: str) -> str:
    text = (category or "").lower()
    if "word of the day" in text:
        return "Word of the Day"
    if "grammar" in text:
        return "Grammar Tip"
    if "collocation" in text:
        return "Collocations"
    if "resource" in text or "pdf" in text or "video" in text:
        return "Resource"
    if "quiz" in text or "poll" in text:
        return "Quiz/Poll"
    if "music" in text or "quote" in text:
        return "Quote/Music"
    if "mistake" in text:
        return "Mistakes"
    if "idiom" in text or "phrase" in text:
        return "Phrase"
    return "General"


GENERIC_CONTRACT = {
    "allowed_sections": ["hook/title", "main lesson/task", "examples or practice", "CTA", "hashtags", "footer"],
    "forbidden_sections": [],
    "required_output_shape": "One focused Telegram post matching the strict slot category.",
    "allowed_idea_types": [],
    "preferred_style_example_categories": ["General"],
}


CATEGORY_CONTRACTS = {
    "Word of the Day": {
        "allowed_sections": ["emoji header/title", "target word", "pronunciation", "meaning", "usage", "examples", "synonyms", "IELTS note", "CTA", "hashtags", "footer"],
        "forbidden_sections": ["5 collocations", "5 high-band words/phrases", "weekly review", "common mistakes list"],
        "required_output_shape": "One Word of the Day post about exactly one word.",
        "allowed_idea_types": ["word"],
        "preferred_style_example_categories": ["Word of the Day", "General"],
    },
    "5 Underrated IELTS Collocations": {
        "allowed_sections": ["emoji/list title", "exactly five numbered collocations", "short Uzbek meanings/use notes", "CTA", "hashtags", "footer"],
        "forbidden_sections": ["Word of the Day", "pronunciation", "single word meaning", "usage section", "synonyms section", "IELTS level section", "Grammar Tip"],
        "required_output_shape": "A focused five-item collocations post only: title, five numbered collocations with short notes, CTA, separator/hashtags/footer if learned.",
        "allowed_idea_types": ["collocation"],
        "preferred_style_example_categories": ["Collocations", "General"],
    },
    "Grammar Tip": {
        "allowed_sections": ["emoji/title", "one grammar concept", "short grammar explanation", "at least 2 correct example sentences", "short common mistake or mini task", "CTA", "footer"],
        "forbidden_sections": ["Word of the Day", "5 high-band words/phrases", "collocations list", "vocabulary learning advice", "study methods", "motivation", "resource recommendations", "generic English-learning tips"],
        "required_output_shape": "One actual grammar concept only: name the concept, explain the rule/structure briefly, give at least 2 correct example sentences, then add a short common mistake or mini task.",
        "allowed_idea_types": ["grammar_tip"],
        "preferred_style_example_categories": ["Grammar Tip", "General"],
    },
    "5 High-Band Words/Phrases": {
        "allowed_sections": ["emoji/list title", "exactly five numbered words/phrases", "short meanings", "example/use note", "CTA", "footer"],
        "forbidden_sections": ["Grammar Tip", "Word of the Day", "long single-word lesson"],
        "required_output_shape": "A focused five-item high-band words/phrases post only.",
        "allowed_idea_types": ["word", "phrase"],
        "preferred_style_example_categories": ["Phrase", "Word of the Day", "General"],
    },
    "Idiom/Phrase": {
        "allowed_sections": ["emoji/title", "target idiom/phrase", "meaning", "examples", "practice question", "footer"],
        "forbidden_sections": ["5 academic phrases", "Word of the Day"],
        "required_output_shape": "One idiom or phrase post only.",
        "allowed_idea_types": ["phrase", "phrasal_verb"],
        "preferred_style_example_categories": ["Phrase", "General"],
    },
    "5 Useful Academic Phrases": {
        "allowed_sections": ["emoji/list title", "exactly five numbered academic phrases", "short use notes", "CTA", "footer"],
        "forbidden_sections": ["Idiom/Phrase", "Word of the Day", "long single phrase lesson"],
        "required_output_shape": "A focused five-item academic phrases post only.",
        "allowed_idea_types": ["academic_phrase", "phrase"],
        "preferred_style_example_categories": ["Phrase", "General"],
    },
    "PDF/Video Resource": {
        "allowed_sections": ["resource title", "why useful", "how to use", "mini task", "footer"],
        "forbidden_sections": ["5 verbs", "Word of the Day"],
        "required_output_shape": "One resource recommendation/tip only.",
        "allowed_idea_types": ["resource_tip"],
        "preferred_style_example_categories": ["Resource", "General"],
    },
    "5 Powerful IELTS Verbs": {
        "allowed_sections": ["emoji/list title", "exactly five numbered verbs", "meaning/use note", "example", "CTA", "footer"],
        "forbidden_sections": ["PDF/Video Resource", "Word of the Day"],
        "required_output_shape": "A focused five-item IELTS verbs post only.",
        "allowed_idea_types": ["ielts_verb", "word"],
        "preferred_style_example_categories": ["Word of the Day", "General"],
    },
    "Quiz/Poll": {
        "allowed_sections": ["quiz question", "answer options", "CTA", "footer"],
        "forbidden_sections": ["Weekly Review", "5 common mistakes"],
        "required_output_shape": "One quiz/poll post only.",
        "allowed_idea_types": ["common_mistake", "resource_tip"],
        "preferred_style_example_categories": ["Quiz/Poll", "General"],
    },
    "Weekly Review": {
        "allowed_sections": ["weekly review title", "short review points", "practice task", "CTA", "footer"],
        "forbidden_sections": ["Quiz/Poll", "5 common mistakes list"],
        "required_output_shape": "One weekly review post only.",
        "allowed_idea_types": ["resource_tip", "academic_phrase", "collocation"],
        "preferred_style_example_categories": ["General"],
    },
    "5 Common IELTS Mistakes": {
        "allowed_sections": ["emoji/list title", "exactly five numbered mistakes", "correction", "CTA", "footer"],
        "forbidden_sections": ["Quiz/Poll", "Weekly Review", "Word of the Day"],
        "required_output_shape": "A focused five-item common mistakes post only.",
        "allowed_idea_types": ["common_mistake"],
        "preferred_style_example_categories": ["Mistakes", "General"],
    },
    "Music/Quote": {
        "allowed_sections": ["quote/song line", "meaning", "short reflection", "question", "footer"],
        "forbidden_sections": ["5 advanced synonyms", "Word of the Day"],
        "required_output_shape": "One music/quote post only.",
        "allowed_idea_types": ["quote"],
        "preferred_style_example_categories": ["Quote/Music", "General"],
    },
    "5 Advanced Synonyms": {
        "allowed_sections": ["emoji/list title", "exactly five numbered synonyms", "basic word comparison", "example/use note", "CTA", "footer"],
        "forbidden_sections": ["Music/Quote", "Word of the Day"],
        "required_output_shape": "A focused five-item advanced synonyms post only.",
        "allowed_idea_types": ["word"],
        "preferred_style_example_categories": ["Word of the Day", "General"],
    },
}


def generation_contract_for_category(category: str) -> Dict[str, object]:
    category = category or "General"
    if category in CATEGORY_CONTRACTS:
        return CATEGORY_CONTRACTS[category]
    if category.startswith("Light "):
        return {
            "allowed_sections": ["short task/challenge", "one question or prompt", "CTA", "footer"],
            "forbidden_sections": ["new full lesson", "Word of the Day", "five-item list"],
            "required_output_shape": "A short light engagement/practice task only.",
            "allowed_idea_types": ["resource_tip", "collocation", "phrase", "common_mistake"],
            "preferred_style_example_categories": ["General"],
        }
    return GENERIC_CONTRACT


def _fallback_draft(category: str, source: Optional[Dict], used_topics: List[str]) -> str:
    source_line = f"\nSource: {source['title']}" if source else ""
    return (
        f"<b>Voxi draft idea</b>\n\n"
        f"<i>Category: {category}{source_line}</i>\n\n"
        "IELTS learners often know a word, but not the phrase around it.\n\n"
        "Try this mini-set today:\n"
        "1. a significant improvement\n"
        "2. a growing concern\n"
        "3. a practical solution\n"
        "4. a direct impact\n"
        "5. a clear advantage\n\n"
        "Mini task: write one sentence with any two of these phrases."
    )


def _clip(text: str, limit: int = 1600) -> str:
    text = (text or "").strip()
    return text[:limit]


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")


_GENERIC_TOPIC_LINES = {
    "examples",
    "example",
    "synonyms",
    "meaning",
    "usage",
    "quiz",
    "task",
    "mini task",
    "cta",
    "hashtags",
    "footer",
    "sharing is caring",
    "telegram",
    "vocabulary",
    "voxi",
    "web-site",
    "ielts level",
    "ielts note",
}

_GENERIC_TOPIC_PREFIXES = (
    "word of the day",
    "grammar tip",
    "5 underrated ielts collocations",
    "5 high-band words",
    "5 useful academic phrases",
    "5 powerful ielts verbs",
    "5 common ielts mistakes",
    "5 advanced synonyms",
    "weekly review",
    "weekly revision",
    "useful english tip",
    "pdf/video resource",
    "music/quote",
    "quiz/poll",
)


def _clean_topic_label(text: str) -> str:
    clean = unescape(_strip_html(text or ""))
    clean = re.sub(r"https?://\S+", " ", clean, flags=re.IGNORECASE)
    clean = re.sub(r"/[^/\n]{1,40}/", " ", clean)
    clean = re.sub(r"^\s*(?:\d+[\ufe0f\u20e3]*|[①-⑳➊-➓])\s*", "", clean)
    clean = re.sub(r"^[\W_]+", "", clean, flags=re.UNICODE)
    clean = re.sub(r"^\d+[\).:-]\s*", "", clean)
    clean = re.sub(r"^[-•*]\s*", "", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    if ":" in clean:
        before, after = clean.split(":", 1)
        if before.strip().lower() in {
            "grammar tip",
            "word of the day",
            "phrase",
            "idiom",
            "collocation",
            "collocations",
            "quote",
            "mistake",
            "common mistake",
        } and after.strip():
            clean = after.strip()
    for separator in (" — ", " – ", " - "):
        if separator in clean:
            clean = clean.split(separator, 1)[0].strip()
            break
    return clean[:140].strip()


def _normalize_topic_key(topic: str) -> str:
    clean = _clean_topic_label(topic).lower()
    if any(clean.startswith(prefix) for prefix in _GENERIC_TOPIC_PREFIXES):
        return ""
    clean = re.sub(r"#\d+\b", " ", clean)
    clean = re.sub(r"\b(day|daily|lesson|tip|post)\b", " ", clean)
    clean = re.sub(r"[^\w\s]+", " ", clean, flags=re.UNICODE)
    clean = re.sub(r"\s+", " ", clean).strip()
    if any(clean.startswith(prefix) for prefix in _GENERIC_TOPIC_PREFIXES):
        return ""
    comparison = re.split(r"\b(?:vs|versus)\b", clean)
    if len(comparison) > 1:
        parts = sorted(part.strip() for part in comparison if part.strip())
        clean = " vs ".join(parts)
    return clean


def _topic_candidates_from_text(text: str, fallback: str = "") -> List[str]:
    candidates: List[str] = []
    if fallback:
        candidates.append(fallback)
    plain = unescape(_strip_html(text or ""))
    for line in plain.splitlines():
        candidate = _clean_topic_label(line)
        lower = candidate.lower().strip(" .:-")
        if not candidate or len(candidate) < 3:
            continue
        if lower.startswith("#") or "http" in lower:
            continue
        if lower in _GENERIC_TOPIC_LINES:
            continue
        if any(lower.startswith(prefix) for prefix in _GENERIC_TOPIC_PREFIXES):
            continue
        if any(lower.startswith(f"{generic}:") for generic in _GENERIC_TOPIC_LINES):
            continue
        candidates.append(candidate)

    seen = set()
    unique = []
    for candidate in candidates:
        key = _normalize_topic_key(candidate)
        if key and key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique[:12]


def _topics_overlap(new_key: str, old_key: str) -> bool:
    if not new_key or not old_key:
        return False
    if new_key == old_key:
        return True
    shorter, longer = sorted((new_key, old_key), key=len)
    if len(shorter) >= 8 and re.search(rf"\b{re.escape(shorter)}\b", longer):
        return True
    new_tokens = set(new_key.split())
    old_tokens = set(old_key.split())
    if new_tokens and old_tokens:
        overlap = len(new_tokens & old_tokens) / max(1, min(len(new_tokens), len(old_tokens)))
        if overlap >= 0.8 and min(len(new_tokens), len(old_tokens)) >= 2:
            return True
    return SequenceMatcher(None, new_key, old_key).ratio() >= 0.88


def _used_topic_records() -> List[Dict[str, str]]:
    records: List[Dict[str, str]] = []
    for row in storage.get_topic_history():
        raw_candidates = []
        if row.get("used_topic"):
            raw_candidates.append(str(row.get("used_topic")))
        if row.get("topic"):
            raw_candidates.append(str(row.get("topic")))
        raw_candidates.extend(_topic_candidates_from_text(str(row.get("draft_text") or "")))
        seen = set()
        for candidate in raw_candidates:
            key = _normalize_topic_key(candidate)
            if not key or key in seen:
                continue
            seen.add(key)
            records.append(
                {
                    "key": key,
                    "label": _clean_topic_label(candidate) or key,
                    "draft_id": str(row.get("id") or ""),
                }
            )
    return records


def _used_topic_labels(records: List[Dict[str, str]], limit: int = 80) -> List[str]:
    labels = []
    seen = set()
    for record in records:
        key = record["key"]
        if key in seen:
            continue
        seen.add(key)
        labels.append(record["label"])
        if len(labels) >= limit:
            break
    return labels


def _topic_duplication_reason(text: str, topic: str, used_records: List[Dict[str, str]]) -> Optional[str]:
    for candidate in _topic_candidates_from_text(text, topic):
        new_key = _normalize_topic_key(candidate)
        if not new_key:
            continue
        for record in used_records:
            if _topics_overlap(new_key, record["key"]):
                record_id = str(record.get("draft_id") or "")
                if record_id.isdigit():
                    suffix = f" in draft #{record_id}"
                elif record_id:
                    suffix = f" in {record_id}"
                else:
                    suffix = ""
                return f"topic duplicates previously used idea '{record['label']}'{suffix}"
    return None


def _infer_topic(text: str, fallback: str) -> str:
    for line in _strip_html(text).splitlines():
        clean = re.sub(r"^[^\w#]+", "", line.strip())
        if clean and not clean.lower().startswith(("draft id", "voxi content engine")):
            return clean[:120]
    return fallback


def _style_block(examples: List[Dict]) -> str:
    if not examples:
        return "No style examples yet."
    parts = []
    for example in examples:
        meta = []
        if example.get("hashtags"):
            meta.append(f"hashtags={example['hashtags']}")
        if example.get("emoji_count") is not None:
            meta.append(f"emoji_count={example['emoji_count']}")
        if example.get("bold_count") is not None:
            meta.append(f"bold_count={example['bold_count']}")
        if example.get("italic_count") is not None:
            meta.append(f"italic_count={example['italic_count']}")
        if example.get("formatting_pattern"):
            meta.append(f"formatting={_clip(example['formatting_pattern'], 260)}")
        if example.get("language_ratio"):
            meta.append(f"language_ratio={example['language_ratio']}")
        if example.get("cta_pattern"):
            meta.append(f"cta={_clip(example['cta_pattern'], 180)}")
        if example.get("footer_pattern"):
            meta.append(f"footer={_clip(example['footer_pattern'], 220)}")
        parts.append(
            f"Example #{example['id']} | source={example.get('source')} | "
            f"category={example.get('category')}\n"
            f"Style metadata: {'; '.join(meta) if meta else 'none'}\n"
            f"{_clip(example.get('text') or '', 1200)}"
        )
    return "\n\n---\n\n".join(parts)


def _allowed_hashtag_block(style_category: str) -> tuple[str, List[str]]:
    allowed = storage.get_learned_hashtags(style_category, 12)
    if not allowed:
        return (
            "No approved hashtags exist for this category or General. Do not include any hashtags.",
            [],
        )
    return (
        "Only these learned hashtags are approved. Use a natural subset if needed, "
        "and do not invent any other hashtags:\n" + " ".join(allowed),
        allowed,
    )


def _remove_unapproved_hashtags(text: str, allowed: List[str]) -> str:
    allowed_lower = {tag.lower() for tag in allowed}
    if not allowed_lower:
        return re.sub(r"(?<![\w])#[A-Za-z0-9_]+", "", text or "")

    def replace(match):
        tag = match.group(0)
        return tag if tag.lower() in allowed_lower else ""

    return re.sub(r"(?<![\w])#[A-Za-z0-9_]+", replace, text or "")


def _normalize_result(raw_text: str, allowed_hashtags: List[str]) -> tuple[str, List[str]]:
    text = normalize_ai_output_html(raw_text.strip())
    text = _remove_unapproved_hashtags(text, allowed_hashtags)
    text = _ensure_mandatory_formatting(text)
    used_hashtags = [
        tag
        for tag in extract_hashtags(text)
        if tag.lower() in {allowed.lower() for allowed in allowed_hashtags}
    ]
    return text.strip(), used_hashtags


def _category_boundary_rules(category: str, slot: str) -> str:
    contract = generation_contract_for_category(category)
    text = (category or "").lower()
    base = [
        f"This post is ONLY for the {slot} slot category: {category}.",
        f"Required output shape: {contract.get('required_output_shape')}",
        "Allowed sections: " + ", ".join(contract.get("allowed_sections") or []),
        "Forbidden sections: " + (", ".join(contract.get("forbidden_sections") or []) or "none"),
        "Use FORMAT EXAMPLES only for visual style, CTA, footer, emoji rhythm, and tone.",
        "Do not copy extra content sections from examples when they belong to another slot.",
    ]
    other_main_sections = (
        "Word of the Day, Grammar Tip, Idiom/Phrase, PDF/Video Resource, "
        "Quiz/Poll, Weekly Review, Music/Quote, Useful English Tip"
    )
    if text.startswith("5 ") or "5 " in text:
        base.extend(
            [
                "Generate a focused 5-item post only.",
                "Use exactly five numbered learning items.",
                f"Do not include these other main sections unless the strict category literally asks for them: {other_main_sections}.",
                "Do not include a separate target word lesson, pronunciation line, long meaning section, usage section, synonyms section, or IELTS level section.",
            ]
        )
    if "collocation" in text:
        base.extend(
            [
                "The whole post must be about five underrated IELTS collocations only.",
                "Do not write 'Word of the Day'.",
                "Do not teach one vocabulary word first.",
                "Each numbered item must be a collocation with a short Uzbek meaning or use note.",
            ]
        )
    elif "high-band words" in text or "words/phrases" in text:
        base.append("The whole post must be a five-item list of high-band words/phrases only.")
    elif "academic phrases" in text:
        base.append("The whole post must be a five-item list of useful academic phrases only.")
    elif "powerful ielts verbs" in text:
        base.append("The whole post must be a five-item list of powerful IELTS verbs only.")
    elif "common ielts mistakes" in text:
        base.append("The whole post must be a five-item list of common IELTS mistakes only.")
    elif "advanced synonyms" in text:
        base.append("The whole post must be a five-item list of advanced synonyms only.")
    elif text.startswith("word of the day"):
        base.append("Generate one Word of the Day post only. Do not add a separate five-item afternoon list.")
    elif text.startswith("grammar tip"):
        base.append(
            """Generate ONE Grammar Tip only.

A Grammar Tip must teach ONE formal English grammar concept.

Allowed topics:

* Present Perfect
* Past Simple
* Present Continuous
* Past Continuous
* Future Forms
* Articles (a/an/the)
* Prepositions
* Conditionals
* Passive Voice
* Reported Speech
* Relative Clauses
* Subject-Verb Agreement
* Gerunds vs Infinitives
* Countable vs Uncountable Nouns
* Comparatives and Superlatives
* Modal Verbs
* Linking Words
* Since vs For
* Used to vs Be Used to
* Much vs Many
* Fewer vs Less

Required structure:

1. Grammar Tip title
2. Short explanation of the rule
3. At least 2 correct example sentences
4. One common mistake OR one mini task

Forbidden topics:

* word meanings
* vocabulary lessons
* synonyms
* antonyms
* collocations
* phrases
* phrasal verbs
* pronunciation
* word comparisons
* noun vs verb lessons
* adjective vs adverb lessons
* parts of speech
* words with multiple meanings
* words with multiple parts of speech

Do not teach vocabulary. Teach grammar only."""
        )
    elif "idiom" in text or text == "phrase":
        base.append("Generate one Idiom/Phrase post only. Do not add academic phrases.")
    elif text.startswith("weekly review"):
        base.append("Generate a Weekly Review post only. Do not add common mistakes unless used briefly inside the review.")
    elif text.startswith("light "):
        base.append("Generate a short engagement/practice task only. Do not introduce a new full lesson.")
    return "\n".join(f"- {line}" for line in base)


def _category_violation(category: str, text: str) -> Optional[str]:
    category_lower = (category or "").lower()
    plain = _strip_html(text).lower()
    contract = generation_contract_for_category(category)
    for marker in contract.get("forbidden_sections") or []:
        clean_marker = str(marker).lower()
        if clean_marker and clean_marker in plain:
            return f"contains forbidden section: {marker}"
    if "collocation" in category_lower:
        forbidden = [
            "word of the day",
            "pronunciation",
            "synonyms:",
            "ielts level",
            " ma’nosi:",
            " ma'nosi:",
            " qo‘llanilishi:",
            " qo'llanilishi:",
        ]
        for marker in forbidden:
            if marker in plain:
                return f"contains forbidden non-collocation section: {marker.strip()}"
    if category_lower == "grammar tip":
        vocabulary_markers = [
            "synonym",
            "synonyms",
            "antonym",
            "antonyms",
            "vocabulary",
            "word meaning",
            "word meanings",
            "pronunciation",
            "collocation",
            "collocations",
            "phrasal verb",
            "phrasal verbs",
            "part of speech",
            "parts of speech",
            "noun vs verb",
            "noun and verb",
            "adjective vs adverb",
            "multiple parts of speech",
            "multiple meanings",
        ]
        for marker in vocabulary_markers:
            if marker in plain:
                return "Grammar Tip is vocabulary-focused, not grammar-focused"

        advice_markers = [
            "learn words",
            "learn vocabulary",
            "improve your vocabulary",
            "vocabulary learning",
            "use flashcards",
            "flashcards",
            "read more books",
            "sample sentences",
            "write sample sentences",
            "study advice",
            "study method",
            "study methods",
            "motivation",
            "stay motivated",
            "resource recommendation",
            "resources to use",
        ]
        for marker in advice_markers:
            if marker in plain:
                return f"Grammar Tip is study/vocabulary advice, not grammar: {marker}"

        grammar_markers = [
            "present perfect",
            "past simple",
            "present continuous",
            "past continuous",
            "tense",
            "future",
            "article",
            "articles",
            "preposition",
            "prepositions",
            "conditional",
            "conditionals",
            "passive voice",
            "reported speech",
            "relative clause",
            "relative clauses",
            "sentence structure",
            "subject-verb agreement",
            "subject verb agreement",
            "clause",
            "pronoun",
            "gerund",
            "gerunds",
            "infinitive",
            "infinitives",
            "modal verb",
            "modal verbs",
            "countable",
            "uncountable",
            "singular",
            "plural",
            "comparative",
            "comparatives",
            "superlative",
            "superlatives",
            "linking words",
            "since vs for",
            "used to",
            "be used to",
            "much vs many",
            "fewer vs less",
            "grammar rule",
            "grammar concept",
            "grammar structure",
            "common mistake",
            "correct:",
            "incorrect:",
        ]
        if not any(marker in plain for marker in grammar_markers):
            return "Grammar Tip does not clearly teach a grammar concept"
    if category_lower.startswith("5 ") or "5 " in category_lower:
        forbidden_main_sections = [
            "word of the day",
            "grammar tip",
            "idiom of the day",
            "phrase of the day",
            "pdf/video resource",
            "music/quote",
            "useful english tip",
        ]
        for marker in forbidden_main_sections:
            if marker in plain and marker not in category_lower:
                return f"contains another slot category: {marker}"
    return None


def _contract_failed_payload(category: str, slot: str, reason: str, prompt: str) -> Dict[str, object]:
    return {
        "text": (
            f"Content generation failed validation for {slot} / {category}.\n"
            f"Reason: {reason}"
        ),
        "topic": category,
        "vocabulary": "",
        "generation_prompt": prompt,
        "style_examples_used": [],
        "hashtags_used": [],
        "failed": True,
        "error": reason,
    }


def _ensure_mandatory_formatting(text: str) -> str:
    text = text or ""
    if not re.search(r"<\s*b(\s+[^>]*)?>", text, flags=re.IGNORECASE):
        lines = text.splitlines()
        for index, line in enumerate(lines):
            clean = line.strip()
            if clean and not clean.startswith("#") and "http" not in clean.lower():
                lines[index] = line.replace(clean, f"<b>{clean}</b>", 1)
                text = "\n".join(lines)
                break
    if not re.search(r"<\s*i(\s+[^>]*)?>", text, flags=re.IGNORECASE):
        lines = text.splitlines()
        for index, line in enumerate(lines):
            clean = line.strip()
            if clean and "<b>" not in clean.lower() and not clean.startswith("#") and "http" not in clean.lower():
                lines[index] = line.replace(clean, f"<i>{clean}</i>", 1)
                text = "\n".join(lines)
                break
        else:
            text = text + "\n\n<i>Review before posting.</i>"
    return text


async def generate_draft_text(
    weekday_index: int,
    slot: str,
    source: Optional[Dict] = None,
    idea_card: Optional[Dict] = None,
    category: Optional[str] = None,
) -> Dict[str, str]:
    category = category or category_for_slot(weekday_index, slot)
    contract = generation_contract_for_category(category)
    used_topic_records = _used_topic_records()
    used_topics = _used_topic_labels(used_topic_records)
    style_category = style_category_for_plan(category)
    preferred_categories = contract.get("preferred_style_example_categories") or [style_category, "General"]
    style_examples = storage.choose_style_examples_from_categories(preferred_categories, 5)
    hashtag_rule, allowed_hashtags = _allowed_hashtag_block(style_category)

    if not openai.api_key:
        logger.warning("OPENAI_API_KEY missing; using content engine fallback draft")
        text, used_hashtags = _normalize_result(_fallback_draft(category, source, used_topics), allowed_hashtags)
        topic = _infer_topic(text, f"{category} / {slot}")
        duplicate = _topic_duplication_reason(text, topic, used_topic_records)
        if duplicate:
            return _contract_failed_payload(category, slot, duplicate, "fallback")
        return {
            "text": text,
            "topic": topic,
            "vocabulary": "",
            "generation_prompt": "fallback",
            "style_examples_used": [],
            "hashtags_used": used_hashtags,
        }

    source_block = "No uploaded resource idea selected. Generate from the weekly plan only."
    if idea_card:
        source_block = (
            "Use exactly this one idea card as the source. Do not mix it with other resources.\n"
            f"Idea card ID: {idea_card.get('id')}\n"
            f"Idea type: {idea_card.get('idea_type')}\n"
            f"Idea title: {idea_card.get('title')}\n"
            f"Idea content: {idea_card.get('content')}\n"
            f"Source resource: {idea_card.get('resource_title')}\n"
            f"Source pages: {idea_card.get('page_start') or ''}-{idea_card.get('page_end') or ''}\n"
            f"Source excerpt: {idea_card.get('source_excerpt') or ''}"
        )
    elif source:
        extracted = _clip(source.get("extracted_text") or "")
        source_block = (
            f"Use exactly one source for this draft.\n"
            f"Source title: {source.get('title')}\n"
            f"Source category: {source.get('category') or 'uncategorized'}\n"
            f"Source text excerpt: {extracted or '[File is saved, but no extractable text is available.]'}"
        )

    style_block = _style_block(style_examples)
    boundary_rules = _category_boundary_rules(category, slot)

    prompt = f"""
Create ONE Telegram channel post draft for Uzbek IELTS/English learners.

STRICT weekly content category for this draft:
{category}

Draft slot:
{slot}

CATEGORY BOUNDARY RULES:
{boundary_rules}

Source rule:
{source_block}

Recent/used ideas to avoid:
{used_topics or 'None yet'}

FORMAT EXAMPLES:
{style_block}

HASHTAG RULE:
{hashtag_rule}

Requirements:
- Short enough for Telegram.
- Practical, concrete, and not generic.
- Enforce the STRICT weekly content category. Do not switch to another content type.
- Use normal Unicode emojis only.
- Never use Telegram custom emoji tags such as <tg-emoji> or </tg-emoji>.
- Language ratio target: about 80% English and 20% Uzbek.
- English should carry the title, phrase/word, explanation, examples, synonyms, CTA, and most structure.
- Uzbek should be limited to translation and short clarification only.
- Sound like a real channel post ready for admin review.
- Use Telegram-safe HTML formatting only: <b>, <i>, <u>, <s>, <code>, <pre>, and valid <a href="https://..."> links.
- Every post MUST include both <b>bold</b> and <i>italic</i> formatting.
- Learn where to place bold/italic from FORMAT EXAMPLES and Style metadata. Usually bold the main title, target word/phrase, section labels, or key IELTS note; italicize pronunciation, Uzbek translation, short clarification, or subtle emphasis where examples do so.
- Do not make the whole post bold or italic. Use formatting in relevant places only.
- Do NOT use Markdown formatting. Never use **bold**, __underline__, or [text](url).
- Strongly follow the structure, tone, emoji rhythm, branding, hook style, CTA, separator, and footer pattern from FORMAT EXAMPLES when present.
- FORMAT EXAMPLES are style examples only. If an example combines multiple daily categories, do not copy the extra categories. Follow CATEGORY BOUNDARY RULES instead.
- Do NOT copy the exact example wording. Generate fresh content.
- If examples include branding/footer links such as Telegram | Vocabulary | Voxi | Web-Site, include a similar footer.
- Use only approved hashtags from HASHTAG RULE. If none are approved, include no hashtags.
- Do not say it was posted.
- Do not generate images.
- Do not mix multiple books/resources or unrelated ideas.
- If an idea card is provided, base the whole post on that one idea card only.
- Avoid repeating any used idea/topic above.
- Treat every used idea/topic above as permanently consumed. A weaker but new topic is better than a strong repeated topic.
- Do not include other same-day main categories unless the strict category explicitly asks for revision/engagement based on them.
- Include 5 items when the weekly plan asks for 5 items.
- Fallback channel pattern if examples are weak: emoji header, clear title, English word/phrase with transcription when relevant, Uzbek meaning, usage explanation, examples, synonyms, IELTS band note, question/CTA, separator line, hashtags, "Sharing is caring ⭐", and Telegram | Vocabulary | Voxi | Web-Site footer links.

Return only the draft post text. No JSON. No commentary.
""".strip()

    response = await openai.ChatCompletion.acreate(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are Voxi Content Engine, an assistant for a Telegram "
                    "channel teaching IELTS and English to Uzbek learners. "
                    "Use normal Unicode emojis only; never use Telegram custom emoji tags."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=750,
        temperature=0.85,
    )
    text, used_hashtags = _normalize_result(
        response["choices"][0]["message"]["content"],
        allowed_hashtags,
    )
    violation = _category_violation(category, text)
    if violation:
        logger.warning("Content draft violated category boundary for %s: %s", category, violation)
        retry_style_examples = storage.choose_style_examples_from_categories(["General"], 3)
        retry_style_block = _style_block(retry_style_examples)
        retry_prompt = f"""
The previous draft was rejected because it {violation}.

Regenerate from scratch.

STRICT CATEGORY:
{category}

SLOT:
{slot}

CATEGORY BOUNDARY RULES:
{boundary_rules}

Hard requirements:
- Generate ONLY this strict category.
- Do not include Word of the Day or any other daily section unless it is the strict category.
- Use the limited FORMAT EXAMPLES below only for footer/tone/emoji rhythm, not content sections.
- Keep Telegram HTML with both <b> and <i>.
- Return only the corrected post.

LIMITED FORMAT EXAMPLES:
{retry_style_block}

Original full instructions:
{prompt}
""".strip()
        response = await openai.ChatCompletion.acreate(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Voxi Content Engine. Strictly obey the requested slot category. "
                        "Never include unrelated daily sections."
                    ),
                },
                {"role": "user", "content": retry_prompt},
            ],
            max_tokens=650,
            temperature=0.55,
        )
        text, used_hashtags = _normalize_result(
            response["choices"][0]["message"]["content"],
            allowed_hashtags,
        )
        prompt = retry_prompt
        style_examples = retry_style_examples
        violation = _category_violation(category, text)
        if violation:
            logger.warning("Content draft failed validation after retry for %s: %s", category, violation)
            return _contract_failed_payload(category, slot, violation, retry_prompt)
    topic = _infer_topic(text, f"{category} / {slot}")
    duplicate = _topic_duplication_reason(text, topic, used_topic_records)
    if duplicate:
        logger.warning("Content draft duplicated a used topic for %s: %s", category, duplicate)
        retry_style_examples = storage.choose_style_examples_from_categories(["General"], 3)
        retry_style_block = _style_block(retry_style_examples)
        retry_prompt = f"""
The previous draft was rejected because it repeated a permanently consumed topic:
{duplicate}

Regenerate from scratch with a completely different main learning idea.

STRICT CATEGORY:
{category}

SLOT:
{slot}

CATEGORY BOUNDARY RULES:
{boundary_rules}

Forbidden used topics:
{used_topics or 'None yet'}

Hard requirements:
- Generate ONLY this strict category.
- Choose a fresh topic that does not duplicate, reword, compare, or substantially overlap with any forbidden used topic.
- Preserve category first, but prefer a weaker new topic over an excellent repeated topic.
- Keep Telegram HTML with both <b> and <i>.
- Return only the corrected post.

LIMITED FORMAT EXAMPLES:
{retry_style_block}

Original full instructions:
{prompt}
""".strip()
        response = await openai.ChatCompletion.acreate(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Voxi Content Engine. Never repeat a permanently consumed topic. "
                        "Strictly obey the requested slot category."
                    ),
                },
                {"role": "user", "content": retry_prompt},
            ],
            max_tokens=650,
            temperature=0.7,
        )
        text, used_hashtags = _normalize_result(
            response["choices"][0]["message"]["content"],
            allowed_hashtags,
        )
        prompt = retry_prompt
        style_examples = retry_style_examples
        violation = _category_violation(category, text)
        if violation:
            logger.warning("Content draft failed validation after uniqueness retry for %s: %s", category, violation)
            return _contract_failed_payload(category, slot, violation, retry_prompt)
        topic = _infer_topic(text, f"{category} / {slot}")
        duplicate = _topic_duplication_reason(text, topic, used_topic_records)
        if duplicate:
            logger.warning("Content draft failed uniqueness after retry for %s: %s", category, duplicate)
            return _contract_failed_payload(category, slot, duplicate, retry_prompt)
    return {
        "text": text,
        "topic": topic,
        "vocabulary": "",
        "generation_prompt": prompt,
        "style_examples_used": [int(row["id"]) for row in style_examples],
        "hashtags_used": used_hashtags,
    }


async def regenerate_draft_text(draft: Dict, source: Optional[Dict] = None) -> Dict[str, object]:
    category = draft.get("content_category") or "General"
    style_category = style_category_for_plan(category)
    style_examples = storage.choose_style_examples(style_category, 5)
    hashtag_rule, allowed_hashtags = _allowed_hashtag_block(style_category)
    topic = draft.get("topic") or draft.get("used_topic") or category
    source_block = "No source resource was used for this draft."
    if source:
        source_block = (
            f"Use the same single source as the original draft.\n"
            f"Source title: {source.get('title')}\n"
            f"Source category: {source.get('category') or 'uncategorized'}\n"
            f"Source text excerpt: {_clip(source.get('extracted_text') or '')}"
        )

    if not openai.api_key:
        text, used_hashtags = _normalize_result(draft.get("draft_text") or "", allowed_hashtags)
        return {
            "text": text,
            "topic": topic,
            "generation_prompt": "fallback_regenerate",
            "style_examples_used": [],
            "hashtags_used": used_hashtags,
        }

    prompt = f"""
Improve this existing Telegram post draft without changing its idea.

KEEP EXACTLY:
- category: {category}
- style category: {style_category}
- weekday: {draft.get('weekday') or ''}
- slot: {draft.get('slot') or ''}
- topic/idea: {topic}
- source/resource context, if any
- content type

CHANGE ONLY:
- wording
- examples
- structure details
- quality and channel fit

Original draft:
{draft.get('draft_text') or ''}

Source rule:
{source_block}

FORMAT EXAMPLES:
{_style_block(style_examples)}

HASHTAG RULE:
{hashtag_rule}

Requirements:
- Do not replace the topic/idea with a new one.
- If the original topic is a phrase/word, keep the same phrase/word.
- Enforce the same weekly category: {category}.
- Use normal Unicode emojis only.
- Never use Telegram custom emoji tags such as <tg-emoji> or </tg-emoji>.
- Language ratio target: about 80% English and 20% Uzbek.
- Uzbek only for translation and short clarification.
- Strongly follow learned tone, emoji rhythm, CTA, footer, and formatting patterns.
- Use Telegram-safe HTML only.
- Every post MUST include both <b>bold</b> and <i>italic</i> formatting, placed according to learned FORMAT EXAMPLES.
- Do not make the whole post bold or italic. Use formatting for relevant titles, target phrase, labels, translation, or emphasis only.
- Use only approved hashtags from HASHTAG RULE. If none are approved, include no hashtags.
- Return only the improved draft text.
""".strip()

    response = await openai.ChatCompletion.acreate(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You improve Voxi Telegram drafts while preserving the exact idea. "
                    "Use normal Unicode emojis only; never use Telegram custom emoji tags."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=750,
        temperature=0.65,
    )
    text, used_hashtags = _normalize_result(
        response["choices"][0]["message"]["content"],
        allowed_hashtags,
    )
    return {
        "text": text,
        "topic": topic,
        "generation_prompt": prompt,
        "style_examples_used": [int(row["id"]) for row in style_examples],
        "hashtags_used": used_hashtags,
    }
