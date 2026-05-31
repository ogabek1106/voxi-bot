import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import openai

from . import storage

logger = logging.getLogger(__name__)

MODEL = os.getenv("CONTENT_ENGINE_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
openai.api_key = os.getenv("OPENAI_API_KEY")
CHARS_PER_CHUNK = int(os.getenv("CONTENT_RESOURCE_CHARS_PER_CHUNK", "6000"))
MAX_IDEAS_PER_CHUNK = int(os.getenv("CONTENT_RESOURCE_IDEAS_PER_CHUNK", "6"))
_tasks: Dict[int, asyncio.Task] = {}


def start_processing(resource_id: int) -> None:
    if resource_id in _tasks and not _tasks[resource_id].done():
        return
    _tasks[resource_id] = asyncio.create_task(process_resource(resource_id))


def start_pending_processing() -> None:
    for resource in storage.list_resources_by_status(["uploaded", "processing"], 25):
        start_processing(int(resource["id"]))


async def process_resource(resource_id: int) -> None:
    resource = storage.get_resource(resource_id)
    if not resource:
        return
    storage.update_resource_status(resource_id, "processing")
    try:
        existing = storage.count_resource_ideas(resource_id)
        if existing:
            storage.update_resource_status(resource_id, "ready")
            return

        chunks = await asyncio.to_thread(_extract_chunks, resource)
        if not chunks:
            raise RuntimeError("No extractable text found in resource.")

        created = 0
        for chunk in chunks:
            ideas = await _ideas_from_chunk(resource, chunk)
            for idea in ideas:
                idea_id = storage.add_resource_idea(
                    resource_id=resource_id,
                    idea_type=idea.get("idea_type", "resource_tip"),
                    title=idea.get("title", "").strip(),
                    content=idea.get("content", "").strip(),
                    source_excerpt=idea.get("source_excerpt") or chunk["text"][:1200],
                    page_start=chunk.get("page_start"),
                    page_end=chunk.get("page_end"),
                )
                if idea_id:
                    created += 1
            await asyncio.sleep(0)

        if created:
            storage.update_resource_status(resource_id, "ready")
        else:
            raise RuntimeError("No idea cards were created.")
    except Exception as e:
        logger.exception("Resource processing failed for %s", resource_id)
        storage.update_resource_status(resource_id, "failed", str(e)[:1000])


def _extract_chunks(resource: Dict) -> List[Dict]:
    path = Path(resource.get("local_path") or "")
    if not path.exists():
        return []

    name = (resource.get("file_name") or path.name).lower()
    mime = (resource.get("mime_type") or "").lower()
    if "pdf" in mime or name.endswith(".pdf"):
        return _extract_pdf_chunks(path)
    return _extract_text_chunks(path)


def _extract_text_chunks(path: Path) -> List[Dict]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return _chunk_text(text)


def _extract_pdf_chunks(path: Path) -> List[Dict]:
    try:
        from pypdf import PdfReader
    except Exception as e:
        raise RuntimeError("PDF processing requires pypdf in requirements.txt") from e

    reader = PdfReader(str(path))
    chunks = []
    buffer = []
    start_page = 1
    for index, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        if not page_text.strip():
            continue
        if not buffer:
            start_page = index
        buffer.append(page_text)
        joined = "\n\n".join(buffer)
        if len(joined) >= CHARS_PER_CHUNK:
            chunks.append({"text": joined, "page_start": start_page, "page_end": index})
            buffer = []
    if buffer:
        chunks.append(
            {
                "text": "\n\n".join(buffer),
                "page_start": start_page,
                "page_end": len(reader.pages),
            }
        )
    return chunks


def _chunk_text(text: str) -> List[Dict]:
    clean = re.sub(r"\n{3,}", "\n\n", text or "").strip()
    chunks = []
    for start in range(0, len(clean), CHARS_PER_CHUNK):
        part = clean[start:start + CHARS_PER_CHUNK].strip()
        if part:
            chunks.append({"text": part, "page_start": None, "page_end": None})
    return chunks


async def _ideas_from_chunk(resource: Dict, chunk: Dict) -> List[Dict]:
    if not openai.api_key:
        return _heuristic_ideas(chunk["text"])

    prompt = f"""
Extract reusable learning idea cards from this resource chunk.

Resource title: {resource.get('title') or ''}
Resource category: {resource.get('category') or ''}
Page range: {chunk.get('page_start') or ''}-{chunk.get('page_end') or ''}

Allowed idea_type values:
word, phrase, phrasal_verb, collocation, grammar_tip, academic_phrase,
ielts_verb, common_mistake, quote, resource_tip

Rules:
- Extract concrete learning ideas, not chapter summaries.
- One idea card = one reusable post idea/source.
- Do not mix unrelated ideas.
- Keep source_excerpt short and traceable.
- Return JSON array only.
- Max {MAX_IDEAS_PER_CHUNK} cards.

Chunk:
{chunk['text']}

JSON shape:
[
  {{
    "idea_type": "phrase",
    "title": "catch up with",
    "content": "Short reusable explanation for content generation",
    "source_excerpt": "Exact short source excerpt"
  }}
]
""".strip()
    response = await openai.ChatCompletion.acreate(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You extract concise IELTS/English learning idea cards."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=1200,
        temperature=0.2,
    )
    raw = response["choices"][0]["message"]["content"].strip()
    return _parse_ideas(raw)


def _parse_ideas(raw: str) -> List[Dict]:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw).strip()
        raw = re.sub(r"```$", "", raw).strip()
    try:
        data = json.loads(raw)
    except Exception:
        logger.warning("Could not parse idea JSON from resource processor")
        return []
    if not isinstance(data, list):
        return []
    out = []
    allowed = {
        "word", "phrase", "phrasal_verb", "collocation", "grammar_tip",
        "academic_phrase", "ielts_verb", "common_mistake", "quote", "resource_tip",
    }
    for item in data[:MAX_IDEAS_PER_CHUNK]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        idea_type = str(item.get("idea_type") or "resource_tip").strip()
        if idea_type not in allowed:
            idea_type = "resource_tip"
        out.append(
            {
                "idea_type": idea_type,
                "title": title,
                "content": str(item.get("content") or "").strip(),
                "source_excerpt": str(item.get("source_excerpt") or "").strip(),
            }
        )
    return out


def _heuristic_ideas(text: str) -> List[Dict]:
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) > 20]
    out = []
    for line in lines[:MAX_IDEAS_PER_CHUNK]:
        title = line[:80].rstrip(" .,:;")
        out.append(
            {
                "idea_type": "resource_tip",
                "title": title,
                "content": line[:500],
                "source_excerpt": line[:500],
            }
        )
    return out
