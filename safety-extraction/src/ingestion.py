

import logging
import re
from pathlib import Path
from typing import Any

import numpy as np

from src.constants import ALLCAPS_RE, NUMBERED_HEADING_RE
from src.exceptions import PDFIngestionError

logger = logging.getLogger("safety_extraction")


def ingest_pdf(file_path: str | Path) -> list[dict[str, Any]]:

    import fitz  # PyMuPDF

    file_path = Path(file_path)
    if not file_path.exists():
        raise PDFIngestionError(f"File not found: {file_path}")
    if file_path.suffix.lower() != ".pdf":
        raise PDFIngestionError(f"Not a PDF file: {file_path}")

    doc = fitz.open(str(file_path))
    pages: list[dict[str, Any]] = []
    current_heading = "Unknown Section"

    logger.info("Ingesting PDF: %s (%d pages)", file_path.name, len(doc))

    for page_num in range(len(doc)):
        page = doc[page_num]
        display_page = page_num + 1
        ocr_used = False

        # --- Text extraction ---
        raw_text = page.get_text().strip()

        # --- OCR fallback for scanned pages ---
        if not raw_text:
            logger.info("Page %d: No text found, attempting OCR…", display_page)
            try:
                tp = page.get_textpage_ocr(flags=0, full=True)
                raw_text = page.get_text(textpage=tp).strip()
                ocr_used = True
            except Exception as exc:
                logger.warning(
                    "Page %d: OCR failed (%s), attempting pixmap fallback…",
                    display_page, exc,
                )
                try:
                    import fitz as fitz_mod
                    tp = page.get_textpage_ocr(
                        flags=fitz_mod.TEXT_PRESERVE_WHITESPACE, full=True,
                    )
                    raw_text = page.get_text(textpage=tp).strip()
                    ocr_used = True
                except Exception as exc2:
                    logger.warning(
                        "Page %d: All OCR attempts failed (%s), skipping page.",
                        display_page, exc2,
                    )

            if ocr_used and not raw_text:
                logger.warning("Page %d: OCR produced no text, skipping.", display_page)
                continue

        if not raw_text:
            logger.warning("Page %d: Empty page, skipping.", display_page)
            continue

        # --- Heading detection ---
        detected_heading = _detect_heading(page)
        if detected_heading:
            current_heading = detected_heading

        logger.info(
            "Page %d: %d chars extracted | OCR=%s | heading='%s'",
            display_page, len(raw_text),
            "yes" if ocr_used else "no", current_heading,
        )

        pages.append({
            "page_number": display_page,
            "text": raw_text,
            "section_heading": current_heading,
        })

    total = len(doc)
    doc.close()
    logger.info(
        "PDF ingestion complete: %d pages with content out of %d total.",
        len(pages), total,
    )
    return pages


def _detect_heading(page: Any) -> str | None:

    try:
        blocks = page.get_text("dict", flags=0)["blocks"]
    except Exception:
        return None

    all_spans: list[tuple[float, str]] = []
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                size = span.get("size", 0)
                if text and size > 0:
                    all_spans.append((size, text))

    if not all_spans:
        return None

    sizes = [s for s, _ in all_spans]
    median_size = float(np.median(sizes))

    candidates: list[tuple[float, str]] = []
    for size, text in all_spans:
        line_text = text.strip()
        if not line_text or len(line_text) < 3:
            continue

        score = 0.0
        if size > median_size * 1.15:
            score += size - median_size
        if ALLCAPS_RE.match(line_text) and len(line_text) < 80:
            score += 10.0
        if NUMBERED_HEADING_RE.match(line_text):
            score += 15.0

        if score > 0:
            candidates.append((score, line_text))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    heading = candidates[0][1]
    heading = re.sub(r"\s+", " ", heading).strip()
    return heading if len(heading) <= 200 else heading[:200]
