import io
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class OcrDependencyError(RuntimeError):
    pass


def _import_ocr_dependencies():
    missing = []
    try:
        import fitz  # type: ignore
    except Exception:
        fitz = None
        missing.append("PyMuPDF")
    try:
        import pytesseract  # type: ignore
    except Exception:
        pytesseract = None
        missing.append("pytesseract")
    try:
        from PIL import Image  # type: ignore
    except Exception:
        Image = None
        missing.append("Pillow")

    if missing:
        raise OcrDependencyError(
            "OCR dependencies are missing: "
            + ", ".join(missing)
            + ". Install Python packages PyMuPDF, pytesseract, Pillow and the system package tesseract-ocr."
        )

    try:
        pytesseract.get_tesseract_version()
    except Exception as exc:
        raise OcrDependencyError(
            "OCR system dependency is missing or unavailable: tesseract-ocr. "
            "Install tesseract-ocr on Railway/container image."
        ) from exc

    return fitz, pytesseract, Image


def ocr_pdf_pages(path: Path, max_pages: Optional[int] = None, dpi: int = 200) -> List[Dict]:
    fitz, pytesseract, Image = _import_ocr_dependencies()
    language = os.getenv("CONTENT_ENGINE_OCR_LANG", "eng")
    pages: List[Dict] = []

    with fitz.open(str(path)) as document:
        total_pages = len(document)
        limit = min(total_pages, int(max_pages or total_pages))
        zoom = max(72, int(dpi)) / 72
        matrix = fitz.Matrix(zoom, zoom)

        for page_number in range(1, limit + 1):
            page = document.load_page(page_number - 1)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            image = Image.open(io.BytesIO(pixmap.tobytes("png")))
            text = pytesseract.image_to_string(image, lang=language) or ""
            clean = text.strip()
            if clean:
                pages.append(
                    {
                        "text": clean,
                        "page_start": page_number,
                        "page_end": page_number,
                    }
                )
            if page_number == 1 or page_number % 10 == 0 or page_number == limit:
                logger.info("OCR processed %s/%s pages for %s", page_number, limit, path.name)

    return pages
