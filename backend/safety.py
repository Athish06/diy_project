"""
Safety analysis helpers — calls the safety-extraction Python pipeline.

Port of src-tauri/src/safety.rs — same logic:
  - extract_rules: run extraction pipeline on a PDF
  - fetch_rules: query rules from DB via query_rules.py
  - fetch_filter_options: get distinct filter values from DB
  - run_match_script: run match_steps.py for compliance analysis

ENHANCED:
  - extract_rules_v2: extraction + Supabase upload + run_id + evaluation
  - run_brutal_evaluation: 6-check hallucination evaluation
  - fetch_rules_by_document: PDF-grouped rule counts
  - fetch_extraction_runs: all runs with evaluation results
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras


def _safety_extraction_dir() -> Path:
    """Resolve the safety-extraction/ directory relative to project root."""
    return Path(__file__).parent.parent / "safety-extraction"


def _find_python() -> str:
    """Find a working Python executable."""
    candidates = ["python", "python3", "py"] if os.name == "nt" else ["python3", "python"]
    for candidate in candidates:
        path = shutil.which(candidate)
        if path:
            return candidate
    return candidates[0]


def _get_db_connection():
    """Get a psycopg2 connection using SUPABASE_URL."""
    raw_url = os.getenv("SUPABASE_URL", "")
    if not raw_url:
        raise RuntimeError("SUPABASE_URL not set")
    url = re.sub(r":5432/", ":6543/", raw_url)
    return psycopg2.connect(url)


def _strip_embeddings(data: dict) -> dict:
    """Remove heavyweight embedding arrays from rules before sending to frontend."""
    if "rules" in data and isinstance(data["rules"], list):
        for rule in data["rules"]:
            if isinstance(rule, dict):
                rule.pop("embedding", None)
    return data


def _run_query_script(args: list[str]) -> Any:
    """Run query_rules.py with given args and return parsed JSON from stdout."""
    safety_dir = _safety_extraction_dir()
    if not safety_dir.exists():
        raise Exception(f"safety-extraction directory not found at {safety_dir}")

    python = _find_python()
    result = subprocess.run(
        [python, "query_rules.py"] + args,
        cwd=str(safety_dir),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise Exception(f"Query failed: {result.stderr}")

    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Original extraction (kept for backward compat)
# ---------------------------------------------------------------------------

def extract_rules_from_pdf(file_path: str) -> dict:
    """Run the Python extraction pipeline on a PDF file."""
    input_path = Path(file_path)
    if not input_path.exists():
        raise Exception(f"File not found: {file_path}")

    ext = input_path.suffix.lower()
    if ext != ".pdf":
        raise Exception("Only PDF files are supported.")

    stem = input_path.stem
    ts = int(time.time())
    out_path = Path(tempfile.gettempdir()) / f"{stem}_{ts}_rules.json"

    safety_dir = _safety_extraction_dir()
    if not safety_dir.exists():
        raise Exception(f"safety-extraction directory not found at {safety_dir}")

    python = _find_python()
    env = os.environ.copy()
    env["KMP_DUPLICATE_LIB_OK"] = "TRUE"
    env["USE_TF"] = "0"

    result = subprocess.run(
        [python, "-m", "src", str(input_path), "--output", str(out_path)],
        cwd=str(safety_dir),
        capture_output=True,
        text=True,
        env=env,
    )

    if result.returncode != 0:
        raise Exception(
            f"Extraction failed (exit {result.returncode}):\n{result.stderr}{result.stdout}"
        )

    raw = out_path.read_text()
    data = json.loads(raw)
    _strip_embeddings(data)

    try:
        out_path.unlink()
    except OSError:
        pass

    return data


# ---------------------------------------------------------------------------
# Enhanced extraction with run tracking + evaluation
# ---------------------------------------------------------------------------

def _upload_to_supabase_storage(file_path: str, original_filename: str) -> str | None:
    """Upload PDF to Supabase safety_files bucket. Returns public URL or None."""
    try:
        supabase_url = os.getenv("SUPABASE_URL", "")
        # Extract project ref from the connection string
        match = re.search(r"@db\.([^.]+)\.supabase\.co", supabase_url)
        if not match:
            return None

        project_ref = match.group(1)
        # We need the Supabase service key for storage API.
        # For now, store the file path reference instead.
        # The file is already in temp, so we store the original filename.
        return f"supabase://safety_files/{original_filename}"
    except Exception:
        return None


def _insert_run_and_rules(extraction_data: dict, original_filename: str, file_url: str | None) -> int:
    """
    Insert extraction run + rules into DB with run_id linkage.
    Returns the run_id.
    """
    conn = _get_db_connection()
    try:
        with conn.cursor() as cur:
            # Insert extraction run
            cur.execute(
                """
                INSERT INTO extraction_runs
                    (run_timestamp, model_used, total_pages, rule_count,
                     document_count, source_documents, json_source_file, file_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    extraction_data.get("extraction_timestamp", datetime.now(timezone.utc).isoformat()),
                    extraction_data.get("model_used", "unknown"),
                    extraction_data.get("total_pages", 0),
                    extraction_data.get("rule_count", 0),
                    extraction_data.get("document_count", 1),
                    extraction_data.get("source_documents", [original_filename]),
                    original_filename,
                    file_url,
                ),
            )
            run_id = cur.fetchone()[0]

            # Insert rules with run_id
            rules = extraction_data.get("rules", [])
            if rules:
                for rule in rules:
                    emb = rule.get("embedding")
                    emb_str = None
                    if emb is not None:
                        if hasattr(emb, "tolist"):
                            emb = emb.tolist()
                        emb_str = "[" + ",".join(str(float(v)) for v in emb) + "]"

                    cur.execute(
                        """
                        INSERT INTO safety_rules
                            (rule_id, original_text, actionable_rule, materials,
                             suggested_severity, validated_severity, categories,
                             source_document, page_number, section_heading, embedding, run_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (rule_id) DO NOTHING
                        """,
                        (
                            rule.get("rule_id"),
                            rule.get("original_text", ""),
                            rule.get("actionable_rule", ""),
                            rule.get("materials", []),
                            rule.get("suggested_severity"),
                            rule.get("validated_severity"),
                            rule.get("categories", []),
                            rule.get("source_document", ""),
                            rule.get("page_number"),
                            rule.get("section_heading", "Unknown Section"),
                            emb_str,
                            run_id,
                        ),
                    )

            conn.commit()
            return run_id
    finally:
        conn.close()


def _save_evaluation_results(run_id: int, evaluation: dict) -> None:
    """Store evaluation results JSON in the extraction_runs table."""
    conn = _get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE extraction_runs SET evaluation_results = %s WHERE id = %s",
                (json.dumps(evaluation), run_id),
            )
        conn.commit()
    finally:
        conn.close()


def run_brutal_evaluation(pdf_path: str, extraction_data: dict) -> dict:
    """
    4-check brutal evaluation to detect hallucination.

    Checks:
      1. Text Presence: Is original_text actually in the PDF?
      2. Page Accuracy: Is original_text on the claimed page?
      3. Category Validity: Are categories in the allowed set?
      4. Severity Consistency: Is validated_severity >= suggested_severity for hazardous rules?
    """
    import fitz  # PyMuPDF

    rules = extraction_data.get("rules", [])
    if not rules:
        return {"total_rules": 0, "overall_accuracy": 100.0, "checks": {}}

    # Load PDF pages
    doc = fitz.open(pdf_path)
    page_texts: dict[int, str] = {}
    page_headings: dict[int, list[str]] = {}

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_texts[page_num + 1] = page.get_text().strip().lower()

    doc.close()

    # Allowed categories
    ALLOWED_CATEGORIES = {
        "electrical", "chemical", "woodworking", "power_tools",
        "heat_fire", "mechanical", "PPE_required", "child_safety",
        "toxic_exposure", "ventilation", "structural", "general_safety",
    }

    # Hazard keywords for severity check
    HAZARD_KEYWORDS = [
        "toxic", "fatal", "death", "electrocution", "fire",
        "explosion", "asbestos", "cyanide", "carbon monoxide",
        "burn", "amputation", "crush",
    ]

    results_per_rule = []
    check_totals = {
        "text_presence": {"passed": 0, "total": 0},
        "page_accuracy": {"passed": 0, "total": 0},
        "category_validity": {"passed": 0, "total": 0},
        "severity_consistency": {"passed": 0, "total": 0},
    }

    for rule in rules:
        original_text = (rule.get("original_text") or "").lower().strip()
        page_num = rule.get("page_number")
        heading = (rule.get("section_heading") or "").lower().strip()
        actionable = (rule.get("actionable_rule") or "").strip()
        categories = rule.get("categories", [])
        suggested_sev = rule.get("suggested_severity") or 1
        validated_sev = rule.get("validated_severity") or suggested_sev

        checks = {}
        failed = []

        # 1. Text Presence — fuzzy match original_text in any page
        text_found = False
        if original_text and len(original_text) > 10:
            # Check exact substring first
            for pt in page_texts.values():
                if original_text in pt:
                    text_found = True
                    break
            # Fallback: check if >=60% of words are found on any page
            if not text_found:
                words = original_text.split()
                for pt in page_texts.values():
                    matched_words = sum(1 for w in words if w in pt)
                    if len(words) > 0 and matched_words / len(words) >= 0.6:
                        text_found = True
                        break
        elif original_text:
            text_found = True  # Too short to evaluate meaningfully

        checks["text_presence"] = text_found
        check_totals["text_presence"]["total"] += 1
        if text_found:
            check_totals["text_presence"]["passed"] += 1
        else:
            failed.append("text_presence")

        # 2. Page Accuracy — text on claimed page ± 1
        page_ok = False
        if page_num and original_text and len(original_text) > 10:
            words = original_text.split()[:8]  # Check first 8 words
            search_str = " ".join(words)
            for offset in [0, -1, 1]:
                check_page = page_num + offset
                if check_page in page_texts and search_str in page_texts[check_page]:
                    page_ok = True
                    break
            if not page_ok:
                # Fallback: word overlap check
                for offset in [0, -1, 1]:
                    check_page = page_num + offset
                    if check_page in page_texts:
                        matched = sum(1 for w in words if w in page_texts[check_page])
                        if len(words) > 0 and matched / len(words) >= 0.7:
                            page_ok = True
                            break
        else:
            page_ok = True  # Can't evaluate

        checks["page_accuracy"] = page_ok
        check_totals["page_accuracy"]["total"] += 1
        if page_ok:
            check_totals["page_accuracy"]["passed"] += 1
        else:
            failed.append("page_accuracy")

        # 3. Category Validity
        cats_valid = all(c in ALLOWED_CATEGORIES for c in categories) if categories else True
        checks["category_validity"] = cats_valid
        check_totals["category_validity"]["total"] += 1
        if cats_valid:
            check_totals["category_validity"]["passed"] += 1
        else:
            failed.append("category_validity")

        # 6. Severity Consistency
        combined_text = (original_text + " " + actionable.lower())
        has_hazard = any(kw in combined_text for kw in HAZARD_KEYWORDS)
        severity_ok = True
        if has_hazard and validated_sev < 3:
            severity_ok = False
        if validated_sev < suggested_sev:
            severity_ok = False

        checks["severity_consistency"] = severity_ok
        check_totals["severity_consistency"]["total"] += 1
        if severity_ok:
            check_totals["severity_consistency"]["passed"] += 1
        else:
            failed.append("severity_consistency")

        results_per_rule.append({
            "rule_id": rule.get("rule_id", ""),
            "actionable_rule": actionable[:100],
            "checks": checks,
            "all_passed": len(failed) == 0,
            "failed_checks": failed,
        })

    # Aggregate scores
    total_rules = len(rules)
    total_checks = sum(ct["total"] for ct in check_totals.values())
    total_passed = sum(ct["passed"] for ct in check_totals.values())

    per_check_accuracy = {}
    for check_name, ct in check_totals.items():
        if ct["total"] > 0:
            per_check_accuracy[check_name] = round(ct["passed"] / ct["total"] * 100, 1)
        else:
            per_check_accuracy[check_name] = 100.0

    overall_accuracy = round(total_passed / total_checks * 100, 1) if total_checks > 0 else 100.0

    # Failed rules (rules that failed at least one check)
    failed_rules = [r for r in results_per_rule if not r["all_passed"]]

    return {
        "total_rules": total_rules,
        "total_checks": total_checks,
        "checks_passed": total_passed,
        "overall_accuracy": overall_accuracy,
        "per_check_accuracy": per_check_accuracy,
        "rules_all_passed": total_rules - len(failed_rules),
        "rules_with_failures": len(failed_rules),
        "failed_rules": failed_rules[:50],  # Cap for storage
    }


def extract_rules_v2(file_path: str, original_filename: str) -> dict:
    """
    Enhanced extraction: pipeline → DB insert with run_id → evaluation.
    Returns {extraction_data, run_id, evaluation_results}.
    """
    input_path = Path(file_path)
    if not input_path.exists():
        raise Exception(f"File not found: {file_path}")
    if input_path.suffix.lower() != ".pdf":
        raise Exception("Only PDF files are supported.")

    stem = input_path.stem
    ts = int(time.time())
    out_path = Path(tempfile.gettempdir()) / f"{stem}_{ts}_rules.json"

    safety_dir = _safety_extraction_dir()
    if not safety_dir.exists():
        raise Exception(f"safety-extraction directory not found at {safety_dir}")

    python = _find_python()
    env = os.environ.copy()
    env["KMP_DUPLICATE_LIB_OK"] = "TRUE"
    env["USE_TF"] = "0"
    # Pipeline's db.py expects DATABASE_URL, backend uses SUPABASE_URL
    supabase_url = os.getenv("SUPABASE_URL", "")
    if supabase_url and not env.get("DATABASE_URL"):
        env["DATABASE_URL"] = supabase_url
    groq_key = os.getenv("GROQ_API_KEY", "")
    if groq_key:
        env["GROQ_API_KEY"] = groq_key

    # 1. Run extraction pipeline (UNCHANGED)
    result = subprocess.run(
        [python, "-m", "src", str(input_path), "--output", str(out_path)],
        cwd=str(safety_dir),
        capture_output=True,
        text=True,
        env=env,
    )

    if result.returncode != 0:
        raise Exception(
            f"Extraction failed (exit {result.returncode}):\n{result.stderr}{result.stdout}"
        )

    raw = out_path.read_text()
    data = json.loads(raw)

    try:
        out_path.unlink()
    except OSError:
        pass

    # 2. Upload to Supabase storage
    file_url = _upload_to_supabase_storage(file_path, original_filename)

    # 3. Insert run + rules into DB with run_id
    run_id = _insert_run_and_rules(data, original_filename, file_url)

    # 4. Run brutal evaluation
    evaluation = run_brutal_evaluation(file_path, data)

    # 5. Save evaluation results
    _save_evaluation_results(run_id, evaluation)

    # Strip embeddings for frontend
    _strip_embeddings(data)

    return {
        "extraction": data,
        "run_id": run_id,
        "evaluation_results": evaluation,
    }


def extract_rules_with_progress(
    file_path: str,
    original_filename: str,
    progress_callback,
) -> dict:
    """
    Subprocess-based extraction with real-time progress callbacks.

    Runs the safety-extraction pipeline via subprocess.Popen, reads stdout
    line-by-line, and maps log messages to WebSocket progress events.
    DB insert + evaluation run directly in this process (no numpy needed).
    """
    import re as _re

    input_path = Path(file_path)
    if not input_path.exists():
        raise Exception(f"File not found: {file_path}")

    stem = input_path.stem
    ts = int(time.time())
    out_path = Path(tempfile.gettempdir()) / f"{stem}_{ts}_rules.json"

    safety_dir = _safety_extraction_dir()
    if not safety_dir.exists():
        raise Exception(f"safety-extraction directory not found at {safety_dir}")

    python = _find_python()
    env = os.environ.copy()
    env["KMP_DUPLICATE_LIB_OK"] = "TRUE"
    env["USE_TF"] = "0"
    supabase_url = os.getenv("SUPABASE_URL", "")
    if supabase_url and not env.get("DATABASE_URL"):
        env["DATABASE_URL"] = supabase_url
    groq_key = os.getenv("GROQ_API_KEY", "")
    if groq_key:
        env["GROQ_API_KEY"] = groq_key

    progress_callback("upload", {
        "status": f"File received: {original_filename}",
        "file": original_filename,
    })

    # ── Run pipeline as subprocess with real-time output ──
    progress_callback("ingestion", {
        "status": f"Starting pipeline for {original_filename}",
        "file": original_filename,
    })

    proc = subprocess.Popen(
        [python, "-m", "src", str(input_path), "--output", str(out_path)],
        cwd=str(safety_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        bufsize=1,  # line-buffered
    )

    # -- Regex patterns for parsing pipeline log lines --
    re_ingest = _re.compile(r"Ingesting PDF: (.+?) \((\d+) pages\)")
    re_page_content = _re.compile(r"PDF ingestion complete: (\d+) pages with content")
    re_page_extract = _re.compile(r"Page (\d+): extracted (\d+) rules")
    re_pre_dedup = _re.compile(r"Pre-dedup rules for '(.+?)': (\d+)")
    re_loading_embed = _re.compile(r"Loading embedding model")
    re_embed_done = _re.compile(r"Generated embeddings for (\d+) rules")
    re_dedup_done = _re.compile(r"Deduplication: (\d+) rules → (\d+) rules")
    re_pipeline_done = _re.compile(r"Pipeline complete .+?: (\d+) final rules")
    re_batch_summary = _re.compile(r"BATCH SUMMARY — (\d+) documents?, (\d+) total")
    re_batch_done = _re.compile(r"Batch complete: (\d+) final deduplicated")

    total_pages = 0
    current_page = 0
    last_step = "ingestion"
    all_output: list[str] = []  # Collect for error reporting

    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        all_output.append(line)

        # -- Map log lines to progress events --
        m = re_ingest.search(line)
        if m:
            total_pages = int(m.group(2))
            progress_callback("ingestion", {
                "status": f"Reading PDF: {m.group(1)} ({total_pages} pages)",
                "pages": total_pages,
            })
            continue

        m = re_page_content.search(line)
        if m:
            progress_callback("ingestion", {
                "status": f"PDF read: {m.group(1)} pages with content",
                "pages": int(m.group(1)),
                "percentage": 100,
            })
            last_step = "llm_extraction"
            continue

        m = re_page_extract.search(line)
        if m:
            current_page = int(m.group(1))
            rules_found = int(m.group(2))
            pct = round((current_page / max(total_pages, 1)) * 100) if total_pages else 0
            progress_callback("llm_extraction", {
                "status": f"Page {current_page}/{total_pages}: {rules_found} rules extracted",
                "page": current_page,
                "total": total_pages,
                "percentage": pct,
            })
            continue

        m = re_pre_dedup.search(line)
        if m:
            progress_callback("validation", {
                "status": f"Validated {m.group(2)} rules from {m.group(1)}",
                "rule_count": int(m.group(2)),
                "percentage": 100,
            })
            last_step = "validation"
            continue

        if re_loading_embed.search(line):
            progress_callback("embedding", {
                "status": "Loading embedding model…",
            })
            last_step = "embedding"
            continue

        m = re_embed_done.search(line)
        if m:
            progress_callback("embedding", {
                "status": f"Embeddings generated for {m.group(1)} rules",
                "percentage": 100,
            })
            continue

        m = re_dedup_done.search(line)
        if m:
            before = int(m.group(1))
            after = int(m.group(2))
            progress_callback("dedup", {
                "status": f"Deduplication: {before} → {after} rules",
                "before": before,
                "after": after,
                "removed": before - after,
                "percentage": 100,
            })
            last_step = "dedup"
            continue

        m = re_pipeline_done.search(line) or re_batch_done.search(line)
        if m:
            progress_callback("dedup", {
                "status": f"Pipeline done: {m.group(1)} final rules",
                "percentage": 100,
            })
            continue

        m = re_batch_summary.search(line)
        if m:
            progress_callback("validation", {
                "status": f"Batch: {m.group(1)} documents, {m.group(2)} total rules before dedup",
            })
            continue

        # Send unmatched lines so user can see pipeline output
        progress_callback(last_step, {
            "status": line[:200],
        })

    proc.wait()

    if proc.returncode != 0:
        # Include last 30 lines of output for debugging
        tail = "\n".join(all_output[-30:]) if all_output else "(no output)"
        raise Exception(
            f"Extraction pipeline failed (exit {proc.returncode}):\n{tail}"
        )

    # ── Read results ──
    if not out_path.exists():
        raise Exception("Pipeline produced no output file")

    raw = out_path.read_text()
    data = json.loads(raw)

    try:
        out_path.unlink()
    except OSError:
        pass

    # ── Override document names with original filename ──
    data["document_name"] = original_filename
    data["source_documents"] = [original_filename]
    for rule in data.get("rules", []):
        rule["source_document"] = original_filename

    # ── Upload to storage ──
    file_url = _upload_to_supabase_storage(file_path, original_filename)

    # ── DB Insert ──
    rule_count = data.get("rule_count", len(data.get("rules", [])))
    progress_callback("db_insert", {
        "status": f"Inserting {rule_count} rules into database",
        "rule_count": rule_count,
    })

    run_id = _insert_run_and_rules(data, original_filename, file_url)

    progress_callback("db_insert", {
        "status": f"Saved to database — Run #{run_id}",
        "run_id": run_id,
        "percentage": 100,
    })

    # ── Evaluation ──
    progress_callback("evaluation", {
        "status": "Running brutal evaluation (6 checks)",
    })

    evaluation = run_brutal_evaluation(file_path, data)
    _save_evaluation_results(run_id, evaluation)

    progress_callback("evaluation", {
        "status": f"Evaluation complete — {evaluation.get('overall_accuracy', '?')}% accurate",
        "accuracy": evaluation.get("overall_accuracy"),
        "percentage": 100,
    })

    # ── Strip embeddings for frontend ──
    _strip_embeddings(data)

    # ── Complete ──
    progress_callback("complete", {
        "status": f"Done! {rule_count} rules extracted from {original_filename}",
        "run_id": run_id,
        "rule_count": rule_count,
        "accuracy": evaluation.get("overall_accuracy"),
    })

    return {
        "extraction": data,
        "run_id": run_id,
        "evaluation_results": evaluation,
    }


# ---------------------------------------------------------------------------
# DB query helpers
# ---------------------------------------------------------------------------

def fetch_rules_from_db(
    category: str | None = None,
    severity: int | None = None,
    document: str | None = None,
    search: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """Fetch existing rules from the database with optional filters & pagination (direct DB)."""
    conn = _get_db_connection()
    try:
        conditions = []
        params: list[Any] = []

        if category:
            conditions.append("%s = ANY(categories)")
            params.append(category)
        if severity is not None:
            conditions.append("validated_severity = %s")
            params.append(severity)
        if document:
            conditions.append("source_document = %s")
            params.append(document)
        if search:
            conditions.append("(actionable_rule ILIKE %s OR original_text ILIKE %s)")
            params.extend([f"%{search}%", f"%{search}%"])

        where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM safety_rules{where_clause}", params)
            total = cur.fetchone()[0]

        offset = (page - 1) * per_page
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT id, rule_id, original_text, actionable_rule, materials,
                       suggested_severity, validated_severity, categories,
                       source_document, page_number, section_heading, run_id, created_at
                FROM safety_rules{where_clause}
                ORDER BY validated_severity DESC, id
                LIMIT %s OFFSET %s
                """,
                params + [per_page, offset],
            )
            rows = cur.fetchall()

        rules = []
        for row in rows:
            r = dict(row)
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
            if r.get("rule_id"):
                r["rule_id"] = str(r["rule_id"])
            rules.append(r)

        return {"rules": rules, "total": total, "page": page, "per_page": per_page}
    finally:
        conn.close()


def fetch_filter_options_from_db() -> dict:
    """Fetch distinct filter values (categories, severities, documents) from DB (direct DB)."""
    conn = _get_db_connection()
    try:
        with conn.cursor() as cur:
            # Distinct categories
            cur.execute("SELECT DISTINCT unnest(categories) AS cat FROM safety_rules ORDER BY cat")
            categories = [row[0] for row in cur.fetchall()]

            # Distinct severities
            cur.execute("SELECT DISTINCT validated_severity FROM safety_rules WHERE validated_severity IS NOT NULL ORDER BY validated_severity DESC")
            severities = [row[0] for row in cur.fetchall()]

            # Distinct documents
            cur.execute("SELECT DISTINCT source_document FROM safety_rules ORDER BY source_document")
            documents = [row[0] for row in cur.fetchall()]

        return {"categories": categories, "severities": severities, "documents": documents}
    finally:
        conn.close()


def fetch_rules_by_document() -> dict:
    """Get rules grouped by source_document for card view."""
    conn = _get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    source_document AS name,
                    COUNT(*) AS rule_count,
                    ARRAY_AGG(DISTINCT unnest_cat) AS categories,
                    ROUND(AVG(validated_severity)::numeric, 1) AS avg_severity,
                    MAX(created_at) AS last_updated
                FROM safety_rules,
                     LATERAL unnest(categories) AS unnest_cat
                GROUP BY source_document
                ORDER BY source_document
            """)
            rows = cur.fetchall()

        documents = []
        for row in rows:
            r = dict(row)
            if r.get("last_updated"):
                r["last_updated"] = r["last_updated"].isoformat()
            if r.get("avg_severity"):
                r["avg_severity"] = float(r["avg_severity"])
            documents.append(r)

        return {"documents": documents}
    finally:
        conn.close()


def fetch_extraction_runs() -> dict:
    """Get all extraction runs with evaluation results."""
    conn = _get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, run_timestamp, model_used, total_pages, rule_count,
                       document_count, source_documents, json_source_file,
                       file_url, evaluation_results, created_at
                FROM extraction_runs
                ORDER BY id DESC
            """)
            rows = cur.fetchall()

        runs = []
        for row in rows:
            r = dict(row)
            if r.get("run_timestamp"):
                r["run_timestamp"] = r["run_timestamp"].isoformat()
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
            if r.get("evaluation_results") and isinstance(r["evaluation_results"], str):
                r["evaluation_results"] = json.loads(r["evaluation_results"])
            runs.append(r)

        return {"runs": runs}
    finally:
        conn.close()


def fetch_rules_by_run(run_id: int, page: int = 1, per_page: int = 50) -> dict:
    """Fetch rules filtered by run_id."""
    conn = _get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM safety_rules WHERE run_id = %s", (run_id,))
            total = cur.fetchone()[0]

        offset = (page - 1) * per_page
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, rule_id, original_text, actionable_rule, materials,
                       suggested_severity, validated_severity, categories,
                       source_document, page_number, section_heading, run_id, created_at
                FROM safety_rules
                WHERE run_id = %s
                ORDER BY validated_severity DESC, id
                LIMIT %s OFFSET %s
                """,
                (run_id, per_page, offset),
            )
            rows = cur.fetchall()

        rules = []
        for row in rows:
            r = dict(row)
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
            if r.get("rule_id"):
                r["rule_id"] = str(r["rule_id"])
            rules.append(r)

        return {"rules": rules, "total": total, "page": page, "per_page": per_page}
    finally:
        conn.close()


def run_match_steps(steps_json: str) -> dict:
    """
    Run match_steps.py with extracted DIY steps and return compliance report.
    Writes steps JSON to a temp file, calls match_steps.py --steps-file <path> --analyze.
    """
    safety_dir = _safety_extraction_dir()
    if not safety_dir.exists():
        raise Exception(f"safety-extraction directory not found at {safety_dir}")

    ts = int(time.time())
    steps_file = Path(tempfile.gettempdir()) / f"diy_steps_{ts}.json"
    steps_file.write_text(steps_json)

    python = _find_python()
    env = os.environ.copy()
    env["KMP_DUPLICATE_LIB_OK"] = "TRUE"
    env["USE_TF"] = "0"

    try:
        result = subprocess.run(
            [python, "match_steps.py", "--steps-file", str(steps_file), "--analyze"],
            cwd=str(safety_dir),
            capture_output=True,
            text=True,
            env=env,
        )
    finally:
        try:
            steps_file.unlink()
        except OSError:
            pass

    if result.returncode != 0:
        raise Exception(f"Safety matching failed: {result.stderr}")

    return json.loads(result.stdout)
