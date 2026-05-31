import logging
import os
from typing import Dict, List, Optional

import openai

from . import storage

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


def _fallback_draft(category: str, source: Optional[Dict], used_topics: List[str]) -> str:
    source_line = f"\nSource: {source['title']}" if source else ""
    return (
        f"Voxi draft idea\n\n"
        f"Category: {category}{source_line}\n\n"
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


async def generate_draft_text(
    weekday_index: int,
    slot: str,
    source: Optional[Dict] = None,
) -> Dict[str, str]:
    category = category_for_weekday(weekday_index)
    recent = storage.get_recent_drafts(30)
    used_topics = [
        str(row.get("used_topic") or row.get("content_category") or "")
        for row in recent
        if row.get("status") in {"approved", "posted_used", "pending_review"}
    ][:20]
    channel_examples = storage.recent_channel_examples(3)
    approved_examples = [
        row.get("draft_text", "")
        for row in recent
        if row.get("status") == "approved"
    ][:3]

    if not openai.api_key:
        logger.warning("OPENAI_API_KEY missing; using content engine fallback draft")
        return {
            "text": _fallback_draft(category, source, used_topics),
            "topic": category,
            "vocabulary": "",
        }

    source_block = "No uploaded resource selected. Generate from the weekly plan only."
    if source:
        extracted = _clip(source.get("extracted_text") or "")
        source_block = (
            f"Use exactly one source for this draft.\n"
            f"Source title: {source.get('title')}\n"
            f"Source category: {source.get('category') or 'uncategorized'}\n"
            f"Source text excerpt: {extracted or '[File is saved, but no extractable text is available.]'}"
        )

    style_block = "\n\n".join(_clip(x, 700) for x in (channel_examples + approved_examples) if x)
    if not style_block:
        style_block = "No style examples yet."

    prompt = f"""
Create ONE Telegram channel post draft for Uzbek IELTS/English learners.

Weekly content category:
{category}

Draft slot:
{slot}

Source rule:
{source_block}

Recent/used ideas to avoid:
{used_topics or 'None yet'}

Style examples from the channel or approved drafts:
{style_block}

Requirements:
- Short enough for Telegram.
- Practical, concrete, and not generic.
- Use Uzbek explanations with useful English examples.
- Sound like a real channel post ready for admin review.
- Do not say it was posted.
- Do not generate images.
- Do not mix multiple books/resources or unrelated ideas.
- Avoid repeating any used idea/topic above.
- Include 5 items when the weekly plan asks for 5 items.

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
    text = response["choices"][0]["message"]["content"].strip()
    topic = f"{category} / {slot}"
    if source:
        topic = f"{category} / {source.get('title')}"
    return {"text": text, "topic": topic, "vocabulary": ""}
