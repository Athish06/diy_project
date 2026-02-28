"""
Safety analysis helpers — calls the safety-extraction Python pipeline.

Port of src-tauri/src/safety.rs — same logic:
  - extract_rules: run extraction pipeline on a PDF
  - fetch_rules: query rules from DB via query_rules.py
  - fetch_filter_options: get distinct filter values from DB
  - run_match_script: run match_steps.py for compliance analysis
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


def _safety_extraction_dir() -> Path:
    """Resolve the safety-extraction/ directory relative to project root."""
    # backend/ -> diy_project/ -> safety-extraction/
    return Path(__file__).parent.parent / "safety-extraction"


def _find_python() -> str:
    """Find a working Python executable."""
    candidates = ["python", "python3", "py"] if os.name == "nt" else ["python3", "python"]
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

    # Clean up
    try:
        out_path.unlink()
    except OSError:
        pass

    return data


def fetch_rules_from_db(
    category: str | None = None,
    severity: int | None = None,
    document: str | None = None,
    search: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """Fetch existing rules from the database with optional filters & pagination."""
    args = ["--page", str(page), "--per_page", str(per_page)]
    if category:
        args += ["--category", category]
    if severity is not None:
        args += ["--severity", str(severity)]
    if document:
        args += ["--document", document]
    if search:
        args += ["--search", search]
    return _run_query_script(args)


def fetch_filter_options_from_db() -> dict:
    """Fetch distinct filter values (categories, severities, documents) from DB."""
    return _run_query_script(["--filters"])


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
