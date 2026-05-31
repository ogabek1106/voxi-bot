import logging
import os
import re
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
) -> Dict[str, str]:
    category = category_for_weekday(weekday_index)
    recent = storage.get_recent_drafts(30)
    used_topics = [
        str(row.get("used_topic") or row.get("content_category") or "")
        for row in recent
        if row.get("status") in {"approved", "posted_used", "pending_review"}
    ][:20]
    style_category = style_category_for_plan(category)
    style_examples = storage.choose_style_examples(style_category, 5)
    hashtag_rule, allowed_hashtags = _allowed_hashtag_block(style_category)

    if not openai.api_key:
        logger.warning("OPENAI_API_KEY missing; using content engine fallback draft")
        text, used_hashtags = _normalize_result(_fallback_draft(category, source, used_topics), allowed_hashtags)
        return {
            "text": text,
            "topic": category,
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

    prompt = f"""
Create ONE Telegram channel post draft for Uzbek IELTS/English learners.

STRICT weekly content category for this draft:
{category}

Draft slot:
{slot}

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
- Do NOT copy the exact example wording. Generate fresh content.
- If examples include branding/footer links such as Telegram | Vocabulary | Voxi | Web-Site, include a similar footer.
- Use only approved hashtags from HASHTAG RULE. If none are approved, include no hashtags.
- Do not say it was posted.
- Do not generate images.
- Do not mix multiple books/resources or unrelated ideas.
- If an idea card is provided, base the whole post on that one idea card only.
- Avoid repeating any used idea/topic above.
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
                    "channel teaching IELTS and English to Uzbek learners."
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
    topic = _infer_topic(text, f"{category} / {slot}")
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
                "content": "You improve Voxi Telegram drafts while preserving the exact idea.",
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
