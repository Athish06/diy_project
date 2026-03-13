"""
extract_rules.py — Safety rule extraction pipeline.

Ingests PDF documents, extracts atomic safety rules via Groq LLM,
validates, deduplicates, and saves to JSON or PostgreSQL.

Usage (CLI):
    python extract_rules.py path/to/doc.pdf [--output out.json] [--model qwen/qwen3-32b]
    python extract_rules.py path/to/pdfs/   [--output out.json]

    # Migrate saved JSON into DB:
    python extract_rules.py --migrate output/rules.json
"""

import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["USE_TF"] = "0"

import argparse
import json
import logging
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_FILE = Path(__file__).resolve().parent / "extraction.log"
logger = logging.getLogger("safety_extraction")
logger.setLevel(logging.DEBUG)

_fmt = logging.Formatter("[%(asctime)s] %(levelname)-8s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
_console = logging.StreamHandler(sys.stdout)
_console.setLevel(logging.INFO)
_console.setFormatter(_fmt)
logger.addHandler(_console)

_file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(_fmt)
logger.addHandler(_file_handler)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_CATEGORIES: set[str] = {
    "electrical", "chemical", "woodworking", "power_tools", "heat_fire",
    "mechanical", "PPE_required", "child_safety", "toxic_exposure",
    "ventilation", "structural", "general_safety",
}

VAGUE_PHRASES: list[str] = [
    "be careful", "ensure safety", "use caution", "exercise care",
    "take precaution", "take care", "be aware", "use common sense",
]

SEVERITY_PATTERNS: list[tuple[re.Pattern, int, str]] = [
    (
        re.compile(
            r"(toxic[\s\-]?gas|chlorine[\s\-]?gas|bleach[\s\-]?and[\s\-]?ammonia"
            r"|hydrogen[\s\-]?sulfide|carbon[\s\-]?monoxide|cyanide[\s\-]?gas"
            r"|phosgene|nerve[\s\-]?agent)",
            re.IGNORECASE,
        ),
        5, "toxic_fatal",
    ),
    (
        re.compile(
            r"(high[\s\-]?voltage|live[\s\-]?wire|live[\s\-]?current"
            r"|exposed[\s\-]?live[\s\-]?conductor|energized[\s\-]?circuit"
            r"|arc[\s\-]?flash|electrical[\s\-]?shock)",
            re.IGNORECASE,
        ),
        4, "electrical_hazard",
    ),
    (
        re.compile(
            r"(goggles|gloves|helmet|hard[\s\-]?hat|respirator|face[\s\-]?shield"
            r"|ear[\s\-]?protect|hearing[\s\-]?protect|ppe|protective[\s\-]?equipment"
            r"|safety[\s\-]?glasses|steel[\s\-]?toe)",
            re.IGNORECASE,
        ),
        3, "ppe_mention",
    ),
]

NUMBERED_HEADING_RE = re.compile(r"^\s*(\d+\.?\d*\.?\d*)\s+[A-Z]")
ALLCAPS_RE = re.compile(r"^[A-Z][A-Z\s\d\-:./()]{2,}$")

SKIP_POS_TAGS: set[str] = {"ADV", "PART"}
SKIP_LEMMAS: set[str] = {
    "always", "never", "immediately", "regularly",
    "periodically", "routinely", "continuously", "not",
    "do", "only", "also", "first", "then",
}

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ExtractionError(Exception):
    """Raised when rule extraction from LLM fails after retries."""


class PDFIngestionError(Exception):
    """Raised when PDF cannot be read or processed."""


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """You are a Safety Compliance Extraction Engine.
Your task is to extract atomic, actionable safety rules from the provided document text.

You are NOT allowed to:
- Generate advice not explicitly present in the text.
- Merge multiple rules into one.
- Produce vague or narrative safety commentary.
- Add explanations unless explicitly stated in the original text.
- Invent categories outside the predefined taxonomy.

Your output must be a JSON array ONLY. No commentary before or after.

ALLOWED CATEGORIES (use ONLY these):
electrical, chemical, woodworking, power_tools, heat_fire, mechanical,
PPE_required, child_safety, toxic_exposure, ventilation, structural, general_safety

If none apply, use: general_safety
You may assign multiple categories only if clearly justified by the rule.

SEVERITY SCALE (suggest based on content):
1 = Minor injury risk
2 = Moderate injury risk
3 = Serious injury risk
4 = Life-threatening hazard
5 = Extreme/fatal risk or legally restricted activity

Base severity on the consequence implied by the text, not on tone.

OUTPUT FORMAT (strict JSON array):
[
  {{
    "original_text": "<exact sentence or fragment from source>",
    "actionable_rule": "<imperative verb-first rule, one constraint only>",
    "category": ["<from allowed list>"],
    "materials": ["<explicitly mentioned materials/chemicals/tools>"],
    "suggested_severity": <1-5>
  }}
]

EXTRACTION RULES:
1. Split compound instructions into multiple atomic rules.
   Example: "Wear gloves and safety goggles when handling corrosive chemicals."
   → Two rules: one for gloves, one for safety goggles.

2. Remove narrative context.
   Example: "To prevent serious injury, always disconnect the power before servicing."
   → "Disconnect the power before servicing."

3. Each actionable_rule MUST begin with a verb (imperative form).
4. Ignore purely informational or descriptive text.
5. Ignore legal disclaimers unless they describe a specific safety action.
6. If a rule cannot be converted into a direct actionable constraint, discard it.
7. Do not summarize multiple sections into abstract advice.
8. Do not output anything outside the JSON array.

DOCUMENT METADATA:
- Document: {document_name}
- Section: {section_heading}
- Page: {page_number}

DOCUMENT TEXT:
{text}

Return ONLY a valid JSON array. No markdown fences, no explanation."""

# ---------------------------------------------------------------------------
# PDF ingestion
# ---------------------------------------------------------------------------

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

        raw_text = page.get_text().strip()

        if not raw_text:
            logger.info("Page %d: No text found, attempting OCR…", display_page)
            try:
                tp = page.get_textpage_ocr(flags=0, full=True)
                raw_text = page.get_text(textpage=tp).strip()
                ocr_used = True
            except Exception as exc:
                logger.warning("Page %d: OCR failed (%s), attempting pixmap fallback…", display_page, exc)
                try:
                    import fitz as fitz_mod
                    tp = page.get_textpage_ocr(flags=fitz_mod.TEXT_PRESERVE_WHITESPACE, full=True)
                    raw_text = page.get_text(textpage=tp).strip()
                    ocr_used = True
                except Exception as exc2:
                    logger.warning("Page %d: All OCR attempts failed (%s), skipping page.", display_page, exc2)

            if ocr_used and not raw_text:
                logger.warning("Page %d: OCR produced no text, skipping.", display_page)
                continue

        if not raw_text:
            logger.warning("Page %d: Empty page, skipping.", display_page)
            continue

        detected_heading = _detect_heading(page)
        if detected_heading:
            current_heading = detected_heading

        logger.info("Page %d: %d chars extracted | OCR=%s | heading='%s'",
                    display_page, len(raw_text), "yes" if ocr_used else "no", current_heading)

        pages.append({"page_number": display_page, "text": raw_text, "section_heading": current_heading})

    total = len(doc)
    doc.close()
    logger.info("PDF ingestion complete: %d pages with content out of %d total.", len(pages), total)
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
    heading = re.sub(r"\s+", " ", candidates[0][1]).strip()
    return heading if len(heading) <= 200 else heading[:200]


# ---------------------------------------------------------------------------
# LLM extraction
# ---------------------------------------------------------------------------

class GroqExtractor:
    def __init__(self, api_key: str, model_name: str = "qwen/qwen3-32b", max_retries: int = 3) -> None:
        from groq import Groq
        self._client = Groq(api_key=api_key)
        self._model_name = model_name
        self._max_retries = max_retries
        logger.info("Groq extractor initialised — model=%s", model_name)

    @property
    def model_name(self) -> str:
        return self._model_name

    def extract_rules(self, text: str, document_name: str, page_number: int, section_heading: str) -> list[dict[str, Any]]:
        if not text.strip():
            return []

        prompt = EXTRACTION_PROMPT.format(
            document_name=document_name,
            section_heading=section_heading,
            page_number=page_number,
            text=text,
        )

        last_error: Exception | None = None
        raw: str = ""

        for attempt in range(1, self._max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self._model_name,
                    messages=[
                        {"role": "system", "content": "You are a safety compliance extraction engine. Return ONLY a valid JSON array. No commentary."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=4096,
                )
                raw = response.choices[0].message.content or ""
                rules = _parse_json_response(raw)
                rules = _enforce_categories(rules)

                for rule in rules:
                    rule["source_document"] = document_name
                    rule["page_number"] = page_number
                    rule["section_heading"] = section_heading

                logger.info("Page %d: extracted %d rules (attempt %d)", page_number, len(rules), attempt)
                return rules

            except json.JSONDecodeError as exc:
                last_error = exc
                logger.warning("Page %d attempt %d: JSON parse failed — %s | raw[:500]=%s",
                               page_number, attempt, exc, raw[:500] if raw else "<empty>")
            except Exception as exc:
                last_error = exc
                logger.warning("Page %d attempt %d: Extraction error — %s", page_number, attempt, exc)

        raise ExtractionError(
            f"Failed to extract rules from page {page_number} of '{document_name}' "
            f"after {self._max_retries} attempts. Last error: {last_error}"
        )


def _parse_json_response(raw: str) -> list[dict[str, Any]]:
    if not raw or not raw.strip():
        return []

    text = raw.strip()
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()

    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence_match:
        text = fence_match.group(1).strip()

    if not text.startswith("["):
        start = text.find("[")
        if start == -1:
            raise json.JSONDecodeError("No JSON array found in response", text, 0)
        depth = 0
        end = start
        for i in range(start, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        text = text[start:end]

    parsed = json.loads(text)
    if not isinstance(parsed, list):
        raise json.JSONDecodeError("Response is not a JSON array", text, 0)
    return [item for item in parsed if isinstance(item, dict)]


def _enforce_categories(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        categories = rule.get("category", rule.get("categories", []))
        if isinstance(categories, str):
            categories = [categories]
        cleaned: list[str] = []
        for cat in categories:
            if cat in ALLOWED_CATEGORIES:
                cleaned.append(cat)
            else:
                logger.warning("Hallucinated category '%s' replaced with 'general_safety' in rule: %s",
                               cat, rule.get("actionable_rule", "")[:80])
                cleaned.append("general_safety")
        rule["categories"] = list(dict.fromkeys(cleaned))
        rule.pop("category", None)
    return rules


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class RuleValidator:
    def __init__(self) -> None:
        import spacy
        try:
            self._nlp = spacy.load("en_core_web_sm")
        except OSError:
            logger.error("spaCy model 'en_core_web_sm' not found. Run: python -m spacy download en_core_web_sm")
            raise

    def validate_and_normalize(self, rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        validated: list[dict[str, Any]] = []
        for rule in rules:
            action = rule.get("actionable_rule", "").strip()
            if not action:
                continue
            action_lower = action.lower()
            if any(phrase in action_lower for phrase in VAGUE_PHRASES):
                logger.warning("Discarding vague rule: '%s'", action[:100])
                continue
            for sub_rule in self._split_compound_rule(rule):
                normalised = self._normalize_verb(sub_rule)
                if normalised is not None:
                    validated.append(normalised)

        logger.info("Validation: %d rules in → %d rules out", len(rules), len(validated))
        return validated

    def _split_compound_rule(self, rule: dict[str, Any]) -> list[dict[str, Any]]:
        action = rule.get("actionable_rule", "")
        doc = self._nlp(action)

        verb_conj_pairs: list[tuple[Any, Any]] = []
        for token in doc:
            if token.dep_ == "conj" and token.head.pos_ == "VERB" and token.pos_ == "VERB":
                verb_conj_pairs.append((token.head, token))

        if not verb_conj_pairs:
            return [rule]

        split_rules: list[dict[str, Any]] = []
        for head_verb, conj_verb in verb_conj_pairs:
            cc_token = None
            for token in doc:
                if token.dep_ == "cc" and token.head == conj_verb and head_verb.i < token.i < conj_verb.i:
                    cc_token = token
                    break

            if cc_token is None:
                return [rule]

            clause1 = "".join(t.text_with_ws for t in doc if t.i < cc_token.i).strip().rstrip(",").strip()
            clause2 = "".join(t.text_with_ws for t in doc if t.i > cc_token.i).strip()
            if clause2 and clause2[0].islower():
                clause2 = clause2[0].upper() + clause2[1:]

            if clause1 and clause2:
                split_rules.extend([
                    {**rule, "actionable_rule": clause1},
                    {**rule, "actionable_rule": clause2},
                ])
                logger.info("Split compound rule: '%s' → ['%s', '%s']", action[:80], clause1[:60], clause2[:60])
            else:
                split_rules.append(rule)

        return split_rules if split_rules else [rule]

    def _normalize_verb(self, rule: dict[str, Any]) -> dict[str, Any] | None:
        action = rule.get("actionable_rule", "").strip()
        if not action:
            return None

        doc = self._nlp(action)
        verb_idx = None

        for token in doc:
            if token.pos_ in SKIP_POS_TAGS or token.lemma_.lower() in SKIP_LEMMAS:
                continue
            if token.pos_ == "VERB":
                verb_idx = token.i
                break
            else:
                logger.warning("Rule does not start with a verb (first token: '%s' POS=%s): '%s'",
                               token.text, token.pos_, action[:100])
                return None

        if verb_idx is None:
            return None

        verb_token = doc[verb_idx]
        lemma = verb_token.lemma_.capitalize()
        rest = action[verb_token.idx + len(verb_token.text):]
        rule["actionable_rule"] = lemma + rest
        return rule


# ---------------------------------------------------------------------------
# Severity overrides
# ---------------------------------------------------------------------------

def override_severity(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for rule in rules:
        suggested = rule.get("suggested_severity", 1)
        validated = suggested

        action = rule.get("actionable_rule", "")
        normalised = re.sub(r"[^\w\s\-]", "", action.lower())
        normalised = re.sub(r"\s+", " ", normalised).strip()
        original = rule.get("original_text", "")
        normalised_original = re.sub(r"[^\w\s\-]", "", original.lower())
        normalised_original = re.sub(r"\s+", " ", normalised_original).strip()
        combined = f"{normalised} {normalised_original}"

        for pattern, min_severity, label in SEVERITY_PATTERNS:
            if pattern.search(combined):
                if label == "toxic_fatal":
                    validated = 5
                elif label == "ppe_mention":
                    if validated < min_severity:
                        validated = min_severity
                else:
                    if validated < min_severity:
                        validated = max(validated, min_severity)

        rule["validated_severity"] = validated
    return rules


# ---------------------------------------------------------------------------
# Database helpers (for --migrate mode)
# ---------------------------------------------------------------------------

def _get_db_connection(register_vec: bool = True):
    import psycopg2
    raw_url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL", "")
    if not raw_url:
        raise RuntimeError("DATABASE_URL or SUPABASE_URL environment variable is not set.")
    conn = psycopg2.connect(raw_url)
    if register_vec:
        try:
            from pgvector.psycopg2 import register_vector
            register_vector(conn)
        except Exception:
            logger.debug("pgvector adapter registration skipped.")
    return conn


def _init_schema() -> None:
    schema_path = Path(__file__).resolve().parent.parent / "database" / "schema.sql"
    schema_sql = schema_path.read_text(encoding="utf-8")
    conn = _get_db_connection(register_vec=False)
    try:
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        conn.commit()
        logger.info("Schema initialised (or already exists).")
    finally:
        conn.close()


def migrate_json_to_db(json_path: Path) -> None:
    import psycopg2.extras

    logger.info("Starting migration from %s", json_path.name)
    _init_schema()

    with open(json_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    if isinstance(data, list):
        meta, rules = {}, data
    else:
        rules = data.pop("rules", [])
        meta = data

    logger.info("Loaded %d rules | model=%s", len(rules), meta.get("model_used", "?"))

    conn = _get_db_connection()
    try:
        if meta:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO extraction_runs
                        (run_timestamp, model_used, total_pages, rule_count,
                         document_count, source_documents, json_source_file)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        meta.get("extraction_timestamp"),
                        meta.get("model_used"),
                        meta.get("total_pages", 0),
                        meta.get("rule_count", 0),
                        meta.get("document_count", 1),
                        meta.get("source_documents", []),
                        json_path.name,
                    ),
                )
                run_id = cur.fetchone()[0]
                conn.commit()
                logger.info("Extraction run recorded — id=%d", run_id)

        rows = []
        for r in rules:
            emb = r.get("embedding")
            if emb is not None:
                if isinstance(emb, np.ndarray):
                    emb = emb.tolist()
                emb_str = "[" + ",".join(str(float(v)) for v in emb) + "]"
            else:
                emb_str = None
            rows.append((
                r.get("rule_id"), r.get("original_text", ""), r.get("actionable_rule", ""),
                r.get("materials", []), r.get("suggested_severity"), r.get("validated_severity"),
                r.get("categories", []), r.get("source_document", ""), r.get("page_number"),
                r.get("section_heading", "Unknown Section"), emb_str,
            ))

        insert_sql = """
            INSERT INTO safety_rules
                (rule_id, original_text, actionable_rule, materials,
                 suggested_severity, validated_severity, categories,
                 source_document, page_number, section_heading, embedding)
            VALUES %s
            ON CONFLICT (rule_id) DO NOTHING
        """
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, insert_sql, rows, page_size=100)
        conn.commit()
        logger.info("Migration complete — %d rules in database.", len(rows))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Extraction service
# ---------------------------------------------------------------------------

class SafetyRuleExtractionService:
    def __init__(
        self,
        groq_api_key: str | None = None,
        model_name: str = "qwen/qwen3-32b",
        embedding_model: str = "all-MiniLM-L6-v2",
        similarity_threshold: float = 0.9,
        max_retries: int = 3,
    ) -> None:
        api_key = groq_api_key or os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY must be provided or set as environment variable.")

        self._extractor = GroqExtractor(api_key=api_key, model_name=model_name, max_retries=max_retries)
        self._validator = RuleValidator()
        self._embedder = EmbeddingProcessor(model_name=embedding_model, similarity_threshold=similarity_threshold)
        self._model_name = model_name

        logger.info("Service initialised — llm=%s, embedder=%s, sim_threshold=%.2f",
                    model_name, embedding_model, similarity_threshold)

    def _extract_and_validate(self, file_path: str | Path) -> list[dict[str, Any]]:
        file_path = Path(file_path)
        document_name = file_path.stem

        logger.info("=" * 60)
        logger.info("Processing document: %s", file_path.name)
        logger.info("=" * 60)

        pages = ingest_pdf(file_path)
        if not pages:
            logger.warning("No extractable pages found in %s", file_path.name)
            return []

        all_rules: list[dict[str, Any]] = []
        extraction_errors: list[str] = []

        for page_data in pages:
            try:
                page_rules = self._extractor.extract_rules(
                    text=page_data["text"],
                    document_name=document_name,
                    page_number=page_data["page_number"],
                    section_heading=page_data["section_heading"],
                )
                all_rules.extend(page_rules)
            except ExtractionError as exc:
                logger.error("Extraction failed: %s", exc)
                extraction_errors.append(str(exc))

        if not all_rules:
            logger.warning("No rules extracted from %s", file_path.name)
            return []

        all_rules = self._validator.validate_and_normalize(all_rules)
        all_rules = override_severity(all_rules)

        logger.info("Pre-dedup rules for '%s': %d", file_path.name, len(all_rules))
        return all_rules

    def process_document(self, file_path: str | Path) -> list[dict[str, Any]]:
        all_rules = self._extract_and_validate(file_path)
        if not all_rules:
            return []

        all_rules = self._embedder.generate_embeddings(all_rules)
        all_rules = self._embedder.deduplicate_rules(all_rules)
        for rule in all_rules:
            rule["rule_id"] = str(uuid.uuid4())

        logger.info("Pipeline complete for '%s': %d final rules.", Path(file_path).name, len(all_rules))
        return all_rules

    def process_batch(self, file_paths: list[str | Path]) -> list[dict[str, Any]]:
        combined_rules: list[dict[str, Any]] = []
        doc_stats: list[dict[str, Any]] = []

        for file_path in file_paths:
            file_path = Path(file_path)
            try:
                rules = self._extract_and_validate(file_path)
                doc_stats.append({"document": file_path.name, "rules_before_dedup": len(rules)})
                combined_rules.extend(rules)
            except Exception as exc:
                logger.error("Failed to process %s: %s", file_path.name, exc, exc_info=True)
                doc_stats.append({"document": file_path.name, "rules_before_dedup": 0, "error": str(exc)})

        logger.info("=" * 60)
        logger.info("BATCH SUMMARY — %d documents, %d total rules before dedup", len(file_paths), len(combined_rules))
        logger.info("=" * 60)

        if not combined_rules:
            logger.warning("No rules extracted from any document.")
            return []

        combined_rules = self._embedder.generate_embeddings(combined_rules)
        combined_rules = self._embedder.deduplicate_rules(combined_rules)

        for rule in combined_rules:
            rule["rule_id"] = str(uuid.uuid4())

        for stat in doc_stats:
            doc_name = stat["document"].rsplit(".", 1)[0]
            surviving = sum(1 for r in combined_rules if r.get("source_document") == doc_name)
            stat["rules_after_dedup"] = surviving

        logger.info("Batch complete: %d final deduplicated rules across %d documents.",
                    len(combined_rules), len(file_paths))
        for stat in doc_stats:
            logger.info("  %-40s %d extracted → %d after global dedup%s",
                        stat["document"], stat.get("rules_before_dedup", 0),
                        stat.get("rules_after_dedup", 0),
                        f"  [ERROR: {stat['error']}]" if "error" in stat else "")

        return combined_rules

    def save_results(
        self,
        rules: list[dict[str, Any]],
        output_path: str | Path,
        document_name: str = "",
        total_pages: int = 0,
        source_documents: list[str] | None = None,
    ) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        envelope: dict[str, Any] = {
            "extraction_timestamp": datetime.now(timezone.utc).isoformat(),
            "model_used": self._model_name,
            "total_pages": total_pages,
            "rule_count": len(rules),
        }

        if source_documents and len(source_documents) > 1:
            envelope["document_name"] = "batch"
            envelope["source_documents"] = source_documents
            envelope["document_count"] = len(source_documents)
        else:
            envelope["document_name"] = document_name

        envelope["rules"] = rules

        def _default(obj: Any) -> Any:
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            if isinstance(obj, np.floating):
                return float(obj)
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, uuid.UUID):
                return str(obj)
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(envelope, f, indent=2, default=_default, ensure_ascii=False)

        logger.info("Results saved to: %s", output_path)
        return output_path


# ---------------------------------------------------------------------------
# EmbeddingProcessor (kept here to avoid circular import with embeddings.py)
# ---------------------------------------------------------------------------

class EmbeddingProcessor:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2", similarity_threshold: float = 0.9) -> None:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading embedding model: %s", model_name)
        self._embedder = SentenceTransformer(model_name)
        self._similarity_threshold = similarity_threshold

    def generate_embeddings(self, rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not rules:
            return rules
        texts = [r.get("actionable_rule", "") for r in rules]
        embeddings = self._embedder.encode(texts, show_progress_bar=False)
        for rule, emb in zip(rules, embeddings):
            rule["embedding"] = emb.tolist() if hasattr(emb, "tolist") else list(emb)
        logger.info("Generated embeddings for %d rules.", len(rules))
        return rules

    def deduplicate_rules(self, rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(rules) <= 1:
            return rules

        emb_list = [np.array(r["embedding"], dtype=np.float32) for r in rules]
        emb_matrix = np.stack(emb_list)
        norms = np.linalg.norm(emb_matrix, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1e-10, norms)
        normed = emb_matrix / norms
        sim_matrix = normed @ normed.T

        keep_mask = [True] * len(rules)
        duplicate_count = 0

        for i in range(len(rules)):
            if not keep_mask[i]:
                continue
            for j in range(i + 1, len(rules)):
                if not keep_mask[j]:
                    continue
                if float(sim_matrix[i, j]) > self._similarity_threshold:
                    keep_mask[j] = False
                    duplicate_count += 1

        deduped = [r for r, keep in zip(rules, keep_mask) if keep]
        logger.info("Deduplication: %d rules → %d rules (%d duplicates removed).",
                    len(rules), len(deduped), duplicate_count)
        return deduped


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Safety Rule Extraction — extract actionable safety rules from PDF documents via Groq.",
    )
    parser.add_argument("input", nargs="?", help="Path to a PDF file or directory. Omit when using --migrate.")
    parser.add_argument("--output", "-o", default=None, help="Output JSON file path.")
    parser.add_argument("--model", default="qwen/qwen3-32b", help="Groq model name.")
    parser.add_argument("--threshold", type=float, default=0.9, help="Cosine similarity threshold for dedup.")
    parser.add_argument("--migrate", metavar="JSON_FILE", help="Migrate an existing extraction JSON into the DB.")
    args = parser.parse_args()

    if args.migrate:
        json_path = Path(args.migrate)
        if not json_path.exists():
            logger.error("File not found: %s", json_path)
            sys.exit(1)
        migrate_json_to_db(json_path)
        return

    if not args.input:
        parser.print_help()
        sys.exit(1)

    input_path = Path(args.input)

    if input_path.is_dir():
        pdf_files = sorted(input_path.glob("*.pdf"))
        if not pdf_files:
            logger.error("No PDF files found in %s", input_path)
            sys.exit(1)
        logger.info("Found %d PDF files in %s", len(pdf_files), input_path)
    elif input_path.is_file():
        pdf_files = [input_path]
    else:
        logger.error("Input path does not exist: %s", input_path)
        sys.exit(1)

    service = SafetyRuleExtractionService(model_name=args.model, similarity_threshold=args.threshold)

    out_dir = Path(__file__).resolve().parent / "output"

    if len(pdf_files) == 1:
        pdf_path = pdf_files[0]
        try:
            rules = service.process_document(pdf_path)
            if not rules:
                logger.warning("No rules extracted from %s", pdf_path.name)
                sys.exit(0)

            out_path = Path(args.output) if args.output else (
                out_dir / f"{pdf_path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
            total_pages = max((r.get("page_number", 0) for r in rules), default=0)
            service.save_results(rules=rules, output_path=out_path, document_name=pdf_path.stem, total_pages=total_pages)

            print(f"\n{'=' * 50}")
            print(f"Document:    {pdf_path.name}")
            print(f"Rules:       {len(rules)}")
            print(f"Output:      {out_path}")
            print(f"{'=' * 50}\n")

        except Exception as exc:
            logger.error("Failed to process %s: %s", pdf_path.name, exc, exc_info=True)
            sys.exit(1)

    else:
        logger.info("Batch mode: %d PDFs — rules will be deduplicated across ALL documents.", len(pdf_files))
        rules = service.process_batch(pdf_files)
        if not rules:
            logger.warning("No rules extracted from any document.")
            sys.exit(0)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = Path(args.output) if args.output else (
            out_dir / f"batch_{len(pdf_files)}_docs_{timestamp}.json"
        )
        total_pages = max((r.get("page_number", 0) for r in rules), default=0)
        source_documents = [p.stem for p in pdf_files]

        service.save_results(rules=rules, output_path=out_path, document_name="batch",
                             total_pages=total_pages, source_documents=source_documents)

        doc_counts: dict[str, int] = {}
        for rule in rules:
            src = rule.get("source_document", "unknown")
            doc_counts[src] = doc_counts.get(src, 0) + 1

        print(f"\n{'=' * 60}")
        print(f"BATCH RESULTS — {len(pdf_files)} documents processed")
        print(f"{'=' * 60}")
        print(f"Total deduplicated rules:  {len(rules)}")
        print(f"Output:                    {out_path}")
        print(f"\nPer-document breakdown:")
        for doc_name, count in sorted(doc_counts.items()):
            print(f"  {doc_name:<40} {count} rules")
        print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
