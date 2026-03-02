"""
Safety rule extraction pipeline — calls the safety-extraction CLI tool.

Provides:
  - extract_rules_v2: extraction + DB insert + evaluation
  - extract_rules_with_progress: same with real-time progress callbacks (WebSocket)
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

from db.connection import get_db_connection
from extraction.evaluation import run_brutal_evaluation, save_evaluation_results


def _safety_extraction_dir() -> Path:
    """Resolve the safety-extraction/ directory relative to project root."""
    return Path(__file__).parent.parent.parent / "safety-extraction"


def _find_python() -> str:
    """Find a working Python executable."""
    candidates = (
        ["python", "python3", "py"] if os.name == "nt" else ["python3", "python"]
    )
    for candidate in candidates:
        path = shutil.which(candidate)
        if path:
            return candidate
    return candidates[0]


def _strip_embeddings(data: dict) -> dict:
    """Remove heavyweight embedding arrays from rules before sending to frontend."""
    if "rules" in data and isinstance(data["rules"], list):
        for rule in data["rules"]:
            if isinstance(rule, dict):
                rule.pop("embedding", None)
    return data


def _upload_to_supabase_storage(file_path: str, original_filename: str) -> str | None:
    """Upload PDF to Supabase safety_files bucket. Returns reference URL or None."""
    try:
        supabase_url = os.getenv("SUPABASE_URL", "")
        match = re.search(r"@db\.([^.]+)\.supabase\.co", supabase_url)
        if not match:
            return None
        return f"supabase://safety_files/{original_filename}"
    except Exception:
        return None


def _insert_run_and_rules(
    extraction_data: dict, original_filename: str, file_url: str | None
) -> int:
    """Insert extraction run + rules into DB with run_id linkage. Returns run_id."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO extraction_runs
                    (run_timestamp, model_used, total_pages, rule_count,
                     document_count, source_documents, json_source_file, file_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    extraction_data.get(
                        "extraction_timestamp",
                        datetime.now(timezone.utc).isoformat(),
                    ),
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
                             source_document, page_number, section_heading,
                             embedding, run_id)
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


def _prepare_env() -> dict:
    """Build environment dict for running the safety-extraction subprocess."""
    env = os.environ.copy()
    env["KMP_DUPLICATE_LIB_OK"] = "TRUE"
    env["USE_TF"] = "0"
    supabase_url = os.getenv("SUPABASE_URL", "")
    if supabase_url and not env.get("DATABASE_URL"):
        env["DATABASE_URL"] = supabase_url
    groq_key = os.getenv("GROQ_API_KEY", "")
    if groq_key:
        env["GROQ_API_KEY"] = groq_key
    return env


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
    env = _prepare_env()

    result = subprocess.run(
        [python, "-m", "src", str(input_path), "--output", str(out_path)],
        cwd=str(safety_dir),
        capture_output=True,
        text=True,
        env=env,
    )

    if result.returncode != 0:
        raise Exception(
            f"Extraction failed (exit {result.returncode}):\n"
            f"{result.stderr}{result.stdout}"
        )

    raw = out_path.read_text()
    data = json.loads(raw)

    try:
        out_path.unlink()
    except OSError:
        pass

    file_url = _upload_to_supabase_storage(file_path, original_filename)
    run_id = _insert_run_and_rules(data, original_filename, file_url)

    evaluation = run_brutal_evaluation(file_path, data)
    save_evaluation_results(run_id, evaluation)

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
    DB insert + evaluation run directly in this process.
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
    env = _prepare_env()

    progress_callback("upload", {
        "status": f"File received: {original_filename}",
        "file": original_filename,
    })

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
        bufsize=1,
    )

    # Regex patterns for parsing pipeline log lines
    re_ingest = _re.compile(r"Ingesting PDF: (.+?) \((\d+) pages\)")
    re_page_content = _re.compile(r"PDF ingestion complete: (\d+) pages with content")
    re_page_extract = _re.compile(r"Page (\d+): extracted (\d+) rules")
    re_pre_dedup = _re.compile(r"Pre-dedup rules for '(.+?)': (\d+)")
    re_loading_embed = _re.compile(r"Loading embedding model")
    re_embed_done = _re.compile(r"Generated embeddings for (\d+) rules")
    re_dedup_done = _re.compile(r"Deduplication: (\d+) rules → (\d+) rules")
    re_pipeline_done = _re.compile(r"Pipeline complete .+?: (\d+) final rules")
    re_batch_done = _re.compile(r"Batch complete: (\d+) final deduplicated")
    re_batch_summary = _re.compile(r"BATCH SUMMARY — (\d+) documents?, (\d+) total")

    total_pages = 0
    current_page = 0
    last_step = "ingestion"
    all_output: list[str] = []

    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        all_output.append(line)

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
            pct = (
                round((current_page / max(total_pages, 1)) * 100) if total_pages else 0
            )
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

        progress_callback(last_step, {"status": line[:200]})

    proc.wait()

    if proc.returncode != 0:
        tail = "\n".join(all_output[-30:]) if all_output else "(no output)"
        raise Exception(
            f"Extraction pipeline failed (exit {proc.returncode}):\n{tail}"
        )

    if not out_path.exists():
        raise Exception("Pipeline produced no output file")

    raw = out_path.read_text()
    data = json.loads(raw)

    try:
        out_path.unlink()
    except OSError:
        pass

    # Override document names with original filename
    data["document_name"] = original_filename
    data["source_documents"] = [original_filename]
    for rule in data.get("rules", []):
        rule["source_document"] = original_filename

    file_url = _upload_to_supabase_storage(file_path, original_filename)

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

    progress_callback("evaluation", {
        "status": "Running brutal evaluation (4 checks)",
    })

    evaluation = run_brutal_evaluation(file_path, data)
    save_evaluation_results(run_id, evaluation)

    progress_callback("evaluation", {
        "status": f"Evaluation complete — {evaluation.get('overall_accuracy', '?')}% accurate",
        "accuracy": evaluation.get("overall_accuracy"),
        "percentage": 100,
    })

    _strip_embeddings(data)

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
