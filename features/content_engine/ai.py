import logging
import os
import re
import json
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


CONTENT_TYPE_PROCESSES = {
    "Word of the Day": """Locked content type: Word of the Day.
Think: I need ONE advanced IELTS-usable word.
Process before writing:
1. Pick exactly 1 word.
2. Validate it is really a word.
3. Validate it is IELTS-useful/high-band.
4. Validate it is not repeated or substantially overlapping with forbidden used topics.
5. Only after the word passes validation, write the Telegram post.
Never generate collocations, grammar tips, quotes, general advice, or lists.""",
    "5 Underrated IELTS Collocations": """Locked content type: 5 Underrated IELTS Collocations.
Think: I need exactly 5 IELTS-usable collocations.
Process before writing:
1. Pick collocation #1, validate it, and replace #1 only if it is bad or repeated.
2. Repeat the same process for #2, #3, #4, and #5.
3. Do not move to the next item until the current collocation is valid.
4. Only after all 5 collocations are valid, write the Telegram post.
Each item must be 2+ words. No single words.
Never generate single words, grammar tips, idioms, phrasal verbs, quotes, or general useful vocabulary.""",
    "Grammar Tip": """Locked content type: Grammar Tip.
Think: I need ONE real grammar rule.
Process before writing:
1. Choose exactly 1 grammar concept.
2. Validate it is grammar, not vocabulary.
3. Validate it is not repeated or substantially overlapping with forbidden used topics.
4. Only after the concept passes validation, write the Telegram post.
Allowed concept families: tenses, articles, prepositions, conditionals, passive voice, reported speech, relative clauses, subject-verb agreement, gerunds/infinitives, countable/uncountable nouns, comparatives/superlatives, modal verbs, linking words.
Never generate word meanings, synonyms, collocations, phrases, phrasal verbs, pronunciation, or parts-of-speech vocabulary lessons.""",
    "5 High-Band Words/Phrases": """Locked content type: 5 High-Band Words/Phrases.
Think: I need exactly 5 high-band IELTS vocabulary items.
Process before writing:
1. Pick item #1, validate it, and replace #1 only if it is bad or repeated.
2. Repeat the same process for #2, #3, #4, and #5.
3. Do not move to the next item until the current word/phrase is valid.
4. Only after all 5 items are valid, write the Telegram post.
Each item may be one advanced word OR one short academic phrase.
Never generate productivity words, afternoon-themed words, motivational phrases, grammar tips, a collocations post, or idioms.""",
    "Idiom/Phrase": """Locked content type: Idiom/Phrase.
Think: I need ONE idiom or useful phrase.
Process before writing:
1. Choose exactly 1 idiom or useful phrase.
2. Validate it is really an idiom or phrase.
3. Validate it is not repeated or substantially overlapping with forbidden used topics.
4. Only after the item passes validation, write the Telegram post.
Never generate a single advanced word, grammar tip, collocation list, quote, or resource.""",
    "5 Useful Academic Phrases": """Locked content type: 5 Useful Academic Phrases.
Think: I need exactly 5 academic phrases.
Process before writing:
1. Pick phrase #1, validate it, and replace #1 only if it is bad or repeated.
2. Repeat the same process for #2, #3, #4, and #5.
3. Do not move to the next item until the current phrase is valid.
4. Only after all 5 phrases are valid, write the Telegram post.
Each item must be a phrase, not a single word.
Never generate single words, idioms, grammar rules, collocations posts, or quotes.""",
    "PDF/Video Resource": """Locked content type: PDF/Video Resource.
Think: I need ONE useful English/IELTS resource.
Process before writing:
1. Choose exactly 1 resource or resource-based learning idea.
2. Validate it is truly a resource.
3. Validate it is not repeated or substantially overlapping with forbidden used topics.
4. Only after the resource idea passes validation, write the Telegram post.
Never generate Word of the Day, Grammar Tip, phrase post, quote, or vocabulary list.""",
    "5 Powerful IELTS Verbs": """Locked content type: 5 Powerful IELTS Verbs.
Think: I need exactly 5 powerful IELTS verbs.
Process before writing:
1. Pick verb #1, validate it, and replace #1 only if it is bad or repeated.
2. Repeat the same process for #2, #3, #4, and #5.
3. Do not move to the next item until the current verb is valid.
4. Only after all 5 verbs are valid, write the Telegram post.
Each item must be a verb or verb phrase used as a verb.
Never generate nouns, adjectives, collocations, grammar tips, idioms, or general vocabulary.""",
    "Quiz/Poll": """Locked content type: Quiz/Poll.
Think: I need ONE quiz, poll, or short review activity.
Process before writing:
1. Choose exactly 1 quiz/poll/review idea.
2. Validate it fits the locked category.
3. Validate it is not repeated or substantially overlapping with forbidden used topics.
4. Only after the activity passes validation, write the Telegram post.
Never generate a word list, grammar lesson, resource recommendation, or quote.""",
    "Weekly Review": """Locked content type: Weekly Review.
Think: I need ONE short review activity based on recent content.
Process before writing:
1. Choose exactly 1 review format.
2. Validate it is a review, not a new unrelated lesson.
3. Validate it is not repeated or substantially overlapping with forbidden used topics.
4. Only after the review idea passes validation, write the Telegram post.
Never generate a fresh word list, full grammar lesson, quote, or resource recommendation.""",
    "5 Common IELTS Mistakes": """Locked content type: 5 Common IELTS Mistakes.
Think: I need exactly 5 common IELTS learner mistakes.
Process before writing:
1. Pick mistake #1, validate it, and replace #1 only if it is bad or repeated.
2. Repeat the same process for #2, #3, #4, and #5.
3. Do not move to the next item until the current mistake is valid.
4. Only after all 5 mistakes are valid, write the Telegram post.
Each item must include a wrong form + corrected form OR a mistake + correction.
Never generate a plain vocabulary list, collocations list, grammar topic only, synonyms, or quotes.""",
    "Music/Quote": """Locked content type: Music/Quote.
Think: I need ONE quote, music-based English post, or meaningful line.
Process before writing:
1. Choose exactly 1 quote/music idea.
2. Validate it fits the locked category.
3. Validate it is not repeated or substantially overlapping with forbidden used topics.
4. Only after the idea passes validation, write the Telegram post.
Never generate a grammar tip, vocabulary list, collocation list, or resource recommendation.""",
    "5 Advanced Synonyms": """Locked content type: 5 Advanced Synonyms.
Think: I need exactly 5 advanced synonym upgrades.
Process before writing:
1. Pick synonym set #1, validate it, and replace #1 only if it is bad or repeated.
2. Repeat the same process for #2, #3, #4, and #5.
3. Do not move to the next item until the current synonym set is valid.
4. Only after all 5 synonym sets are valid, write the Telegram post.
Each item must show: basic word -> advanced synonym.
Never generate collocations, idioms, grammar tips, or random phrases.""",
    "Useful English Tip": """Locked content type: Useful English Tip.
Think: I need ONE practical English-learning tip.
Process before writing:
1. Choose exactly 1 practical English tip.
2. Validate it is practical and not another category.
3. Validate it is not repeated or substantially overlapping with forbidden used topics.
4. Only after the tip passes validation, write the Telegram post.
Never generate Word of the Day, Grammar Tip, resource-only post, quote, or collocation list.""",
    "Weekly Revision": """Locked content type: Weekly Revision.
Think: I need to revise this week's content.
Process before writing:
1. Use current week's posted/reviewed content when available.
2. Choose exactly 1 revision format.
3. Validate it is revision, not new unrelated content.
4. Validate it is not repeated or substantially overlapping with forbidden used topics.
5. Only after the revision idea passes validation, write the Telegram post.
Never generate a new unrelated word list, new grammar lesson, new quote, or unrelated resource.""",
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
    "misol",
    "misollar",
    "synonyms",
    "synonym",
    "meaning",
    "ma'nosi",
    "ma’nosi",
    "manosi",
    "usage",
    "qo'llanilishi",
    "qo‘llanilishi",
    "qollanilishi",
    "izoh",
    "explanation",
    "quiz",
    "task",
    "mini task",
    "savol",
    "question",
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
    "o'rganishni davom ettiring",
    "o‘rganishni davom ettiring",
}

_SECTION_LABEL_PREFIXES = {
    "example",
    "examples",
    "misol",
    "misollar",
    "meaning",
    "ma'nosi",
    "ma’nosi",
    "manosi",
    "usage",
    "qo'llanilishi",
    "qo‘llanilishi",
    "qollanilishi",
    "izoh",
    "explanation",
    "synonym",
    "synonyms",
    "savol",
    "question",
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


def _ascii_topic_label(text: str) -> str:
    return (
        (text or "")
        .lower()
        .replace("’", "'")
        .replace("‘", "'")
        .replace("`", "'")
        .strip()
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


def _is_section_label_line(text: str) -> bool:
    clean = _ascii_topic_label(_clean_topic_label(text)).strip(" .:-")
    if not clean:
        return True
    if clean in _GENERIC_TOPIC_LINES:
        return True
    before_colon = clean.split(":", 1)[0].strip()
    if before_colon in _SECTION_LABEL_PREFIXES:
        return True
    return any(clean.startswith(f"{prefix}:") for prefix in _SECTION_LABEL_PREFIXES)


def _normalize_topic_key(topic: str) -> str:
    clean = _clean_topic_label(topic).lower()
    if _is_section_label_line(clean):
        return ""
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
        try:
            raw_candidates.extend(json.loads(row.get("used_vocabulary") or "[]"))
        except Exception:
            pass
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


def _topic_count_for_category(category: str) -> int:
    return 5 if (category or "").strip().lower().startswith("5 ") else 1


def _raw_topics_block(topics: List[str]) -> str:
    if not topics:
        return "None selected."
    return "\n".join(f"{index}. {topic}" for index, topic in enumerate(topics, 1))


def _parse_raw_topics(raw_text: str) -> List[str]:
    text = (raw_text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            values = payload.get("topics") or payload.get("items") or []
        else:
            values = payload
        if isinstance(values, list):
            return [str(item).strip() for item in values if str(item).strip()]
    except Exception:
        pass

    topics = []
    for line in text.splitlines():
        clean = _clean_topic_label(line)
        if clean and not _is_section_label_line(clean):
            topics.append(clean)
    return topics


def _raw_topic_violation(category: str, topic: str) -> Optional[str]:
    clean = _clean_topic_label(topic)
    key = _normalize_topic_key(clean)
    if not key:
        return "selected topic is empty or metadata, not a learning item"

    category_lower = (category or "").lower()
    words = key.split()
    if "collocation" in category_lower and len(words) < 2:
        return "collocation item must contain 2+ words"
    if "academic phrases" in category_lower and len(words) < 2:
        return "academic phrase item must contain 2+ words"
    if "advanced synonyms" in category_lower and not re.search(r"\s(?:->|to|=>)\s", clean.lower()):
        return "advanced synonym item must show a basic word and an upgraded synonym"
    if "common ielts mistakes" in category_lower and not re.search(r"(->|=>|correct|incorrect|wrong|mistake)", clean.lower()):
        return "common mistake item must include a mistake and correction"
    return None


def _raw_topic_duplicate_reason(topic: str, used_records: List[Dict[str, str]]) -> Optional[str]:
    new_key = _normalize_topic_key(topic)
    if not new_key:
        return "selected topic is empty or metadata, not a learning item"
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


def _selected_topic_duplicate_reason(topic: str, topics: List[str], index: int) -> Optional[str]:
    new_key = _normalize_topic_key(topic)
    if not new_key:
        return None
    for other_index, other_topic in enumerate(topics):
        if other_index == index:
            continue
        other_key = _normalize_topic_key(other_topic)
        if other_key and _topics_overlap(new_key, other_key):
            return f"selected item #{index + 1} duplicates selected item #{other_index + 1}"
    return None


def _topic_selection_rules(category: str) -> str:
    process = CONTENT_TYPE_PROCESSES.get(category or "")
    return process or "Select the raw learning topic/items that match the locked category only."


async def _select_raw_topics(
    category: str,
    slot: str,
    source_block: str,
    used_topics: List[str],
    used_records: List[Dict[str, str]],
) -> tuple[List[str], str, Optional[str]]:
    expected_count = _topic_count_for_category(category)
    forbidden = used_topics or ["None yet"]
    prompt = f"""
Select the raw learning topic/items for a Voxi Content Engine draft.

Locked category:
{category}

Slot:
{slot}

CONTENT TYPE PROCESS:
{_topic_selection_rules(category)}

Source/reference context:
{source_block}

Forbidden previously used raw topics:
{forbidden}

Rules:
- Return ONLY JSON.
- JSON shape: {{"topics": ["..."]}}
- Select exactly {expected_count} topic(s).
- These are raw learning items only, not post text.
- Do not include section labels, titles, explanations, translations, examples, CTA text, hashtags, links, footer text, or branding.
- Check each selected item against forbidden topics before returning it.
- If an item is duplicate or wrong type, replace only that raw item before returning the final JSON.
""".strip()

    response = await openai.ChatCompletion.acreate(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "Select raw learning topics only. Do not write the Telegram post yet.",
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=350,
        temperature=0.75,
    )
    topics = _parse_raw_topics(response["choices"][0]["message"]["content"])[:expected_count]

    repair_prompt = prompt
    for _ in range(5):
        while len(topics) < expected_count:
            topics.append("")
        changed = False
        for index, topic in enumerate(list(topics[:expected_count])):
            reason = (
                _raw_topic_violation(category, topic)
                or _raw_topic_duplicate_reason(topic, used_records)
                or _selected_topic_duplicate_reason(topic, topics[:expected_count], index)
            )
            if not reason:
                continue
            changed = True
            replacement_prompt = f"""
Replace only item #{index + 1} for this locked category.

Locked category:
{category}

Current selected raw topics:
{_raw_topics_block(topics[:expected_count])}

Item #{index + 1} was rejected:
{reason}

Forbidden previously used raw topics:
{forbidden}

Return ONLY JSON:
{{"topic": "replacement item"}}

Rules:
- Replace only item #{index + 1}.
- Keep all other items unchanged.
- The replacement must be the same content type as the locked category.
- Do not return post text, labels, translations, examples, CTA, hashtags, links, or footer.
""".strip()
            repair_prompt = replacement_prompt
            response = await openai.ChatCompletion.acreate(
                model=MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "Replace one rejected raw learning topic only.",
                    },
                    {"role": "user", "content": replacement_prompt},
                ],
                max_tokens=180,
                temperature=0.8,
            )
            raw = response["choices"][0]["message"]["content"]
            try:
                payload = json.loads(raw)
                replacement = str(payload.get("topic") or "").strip()
            except Exception:
                replacement_topics = _parse_raw_topics(raw)
                replacement = replacement_topics[0] if replacement_topics else ""
            topics[index] = replacement
        if not changed:
            final_topics = [_clean_topic_label(topic) for topic in topics[:expected_count]]
            return final_topics, prompt, None

    for index, topic in enumerate(topics[:expected_count]):
        reason = (
            _raw_topic_violation(category, topic)
            or _raw_topic_duplicate_reason(topic, used_records)
            or _selected_topic_duplicate_reason(topic, topics[:expected_count], index)
        )
        if reason:
            return topics[:expected_count], repair_prompt, reason
    return topics[:expected_count], prompt, None


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
    process = CONTENT_TYPE_PROCESSES.get(category or "")
    base = [
        f"This post is ONLY for the {slot} slot category: {category}.",
        "The selected weekly category is locked before generation starts.",
        "First identify the exact content type, then select the correct item/items, validate them, and only then write the Telegram post.",
        f"Required output shape: {contract.get('required_output_shape')}",
        "Allowed sections: " + ", ".join(contract.get("allowed_sections") or []),
        "Forbidden sections: " + (", ".join(contract.get("forbidden_sections") or []) or "none"),
        process or "Locked content type: match the strict category exactly. Validate the chosen idea before writing the post.",
        "For list categories, validate each item before writing the post. If one item is invalid or repeated, replace only that item before continuing.",
        "For single-item categories, validate the chosen item before writing the post. If it is invalid or repeated, choose another item.",
        "Never switch category during retry or regeneration.",
        "Use FORMAT EXAMPLES only for visual style, CTA, footer, emoji rhythm, and tone.",
        "Do not copy extra content sections from examples when they belong to another slot.",
        "Learned style must not override the locked weekly content type.",
        "References/resources may help item selection, but they must not override the locked category.",
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
        raw_topics = [category]
        topic = "; ".join(raw_topics)
        duplicate = _raw_topic_duplicate_reason(topic, used_topic_records)
        if duplicate:
            return _contract_failed_payload(category, slot, duplicate, "fallback")
        return {
            "text": text,
            "topic": topic,
            "topics": raw_topics,
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
    raw_topics, selection_prompt, selection_error = await _select_raw_topics(
        category,
        slot,
        source_block,
        used_topics,
        used_topic_records,
    )
    if selection_error:
        return _contract_failed_payload(category, slot, selection_error, selection_prompt)
    topic = "; ".join(raw_topics)

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

RAW SELECTED LEARNING TOPIC(S):
{_raw_topics_block(raw_topics)}

Raw topic rule:
- Build the post only around the raw selected learning topic(s) above.
- Do not add extra learning topics that were not selected.
- Do not replace these raw topic(s) while writing the post.
- Duplicate checking has already been done on the raw topic(s), not on rendered post text.

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
- Keep the selected category locked. Do not switch content type during retry.
- Follow CATEGORY BOUNDARY RULES as the thinking process before writing.
- Build the post only around these raw selected learning topic(s):
{_raw_topics_block(raw_topics)}
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
    return {
        "text": text,
        "topic": topic,
        "topics": raw_topics,
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
