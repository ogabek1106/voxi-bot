import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import openai

from . import ocr, storage

logger = logging.getLogger(__name__)

MODEL = os.getenv("CONTENT_ENGINE_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
openai.api_key = os.getenv("OPENAI_API_KEY")
CHARS_PER_CHUNK = int(os.getenv("CONTENT_RESOURCE_CHARS_PER_CHUNK", "6000"))
MAX_IDEAS_PER_CHUNK = int(os.getenv("CONTENT_RESOURCE_IDEAS_PER_CHUNK", "6"))
ENABLE_OCR = os.getenv("CONTENT_ENGINE_ENABLE_OCR", "true").strip().lower() not in {"0", "false", "no", "off"}
OCR_MAX_PAGES = int(os.getenv("CONTENT_ENGINE_OCR_MAX_PAGES", "300"))
OCR_DPI = int(os.getenv("CONTENT_ENGINE_OCR_DPI", "200"))
MIN_TEXT_CHARS_PER_PAGE = int(os.getenv("CONTENT_ENGINE_MIN_TEXT_CHARS_PER_PAGE", "80"))
_tasks: Dict[int, asyncio.Task] = {}


def start_processing(resource_id: int) -> None:
    if resource_id in _tasks and not _tasks[resource_id].done():
        return
    _tasks[resource_id] = asyncio.create_task(process_resource(resource_id))


def start_pending_processing() -> None:
    resumable_statuses = [
        "uploaded",
        "processing",
        "extracting_text",
        "low_text_detected",
        "ocr_processing",
        "creating_idea_cards",
    ]
    for resource in storage.list_resources_by_status(resumable_statuses, 25):
        if resource.get("source_type") == "existing_book" and not resource.get("local_path"):
            continue
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

        storage.update_resource_status(resource_id, "extracting_text")
        chunks = await asyncio.to_thread(_extract_chunks, resource_id, resource)
        if not chunks:
            raise RuntimeError("No extractable text found in resource.")

        storage.update_resource_status(resource_id, "creating_idea_cards")
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


def _extract_chunks(resource_id: int, resource: Dict) -> List[Dict]:
    path = Path(resource.get("local_path") or "")
    if not path.exists():
        return []

    name = (resource.get("file_name") or path.name).lower()
    mime = (resource.get("mime_type") or "").lower()
    if "pdf" in mime or name.endswith(".pdf"):
        return _extract_pdf_chunks(resource_id, path)
    return _extract_text_chunks(path)


def _extract_text_chunks(path: Path) -> List[Dict]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return _chunk_text(text)


def _extract_pdf_chunks(resource_id: int, path: Path) -> List[Dict]:
    pages = _extract_pdf_pages(path)
    quality = _text_quality(pages)
    logger.info(
        "PDF text quality for resource %s: chars=%s pages=%s avg_chars_per_page=%.1f useful_pages=%s",
        resource_id,
        quality["total_chars"],
        quality["total_pages"],
        quality["avg_chars_per_page"],
        quality["useful_pages"],
    )
    if _needs_ocr(quality):
        storage.update_resource_status(
            resource_id,
            "low_text_detected",
            (
                "Normal PDF extraction found too little text "
                f"({quality['total_chars']} chars across {quality['total_pages']} pages)."
            ),
        )
        if not ENABLE_OCR:
            raise RuntimeError(
                "PDF appears scanned/image-based, but OCR is disabled. "
                "Set CONTENT_ENGINE_ENABLE_OCR=true to enable OCR fallback."
            )
        storage.update_resource_status(resource_id, "ocr_processing")
        pages = ocr.ocr_pdf_pages(path, max_pages=OCR_MAX_PAGES, dpi=OCR_DPI)
        if not pages:
            raise RuntimeError("OCR completed but did not extract usable text from this PDF.")
    return _chunk_pages(pages)


def _extract_pdf_pages(path: Path) -> List[Dict]:
    try:
        from pypdf import PdfReader
    except Exception as e:
        raise RuntimeError("PDF processing requires pypdf in requirements.txt") from e

    reader = PdfReader(str(path))
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        pages.append(
            {
                "text": page_text.strip(),
                "page_start": index,
                "page_end": index,
            }
        )
    return pages


def _text_quality(pages: List[Dict]) -> Dict[str, float]:
    total_pages = len(pages)
    total_chars = sum(len(str(page.get("text") or "").strip()) for page in pages)
    useful_pages = sum(1 for page in pages if len(str(page.get("text") or "").strip()) >= MIN_TEXT_CHARS_PER_PAGE)
    avg = (total_chars / total_pages) if total_pages else 0
    return {
        "total_pages": total_pages,
        "total_chars": total_chars,
        "avg_chars_per_page": avg,
        "useful_pages": useful_pages,
    }


def _needs_ocr(quality: Dict[str, float]) -> bool:
    total_pages = int(quality["total_pages"])
    if total_pages <= 0:
        return False
    total_chars = int(quality["total_chars"])
    avg = float(quality["avg_chars_per_page"])
    useful_pages = int(quality["useful_pages"])
    min_total = MIN_TEXT_CHARS_PER_PAGE * min(total_pages, 3)
    return avg < MIN_TEXT_CHARS_PER_PAGE or total_chars < min_total or useful_pages == 0


def _chunk_pages(pages: List[Dict]) -> List[Dict]:
    chunks = []
    buffer = []
    start_page = None
    last_page = None
    for page in pages:
        page_text = str(page.get("text") or "").strip()
        if not page_text.strip():
            continue
        page_number = page.get("page_start")
        if not buffer:
            start_page = page_number
        last_page = page.get("page_end") or page_number
        buffer.append(page_text)
        joined = "\n\n".join(buffer)
        if len(joined) >= CHARS_PER_CHUNK:
            chunks.append({"text": joined, "page_start": start_page, "page_end": last_page})
            buffer = []
            start_page = None
            last_page = None
    if buffer:
        chunks.append(
            {
                "text": "\n\n".join(buffer),
                "page_start": start_page,
                "page_end": last_page,
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
