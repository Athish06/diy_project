from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse, urlsplit, urlunsplit

import httpx
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / "backend" / ".env")

YOUTUBE_URL_RE = re.compile(r'https?://(?:www\.)?(?:youtube\.com|youtu\.be)/[^\s,;\]\)>"\']+', re.IGNORECASE)


@dataclass
class VideoEvalResult:
    video_id: str
    video_url: str
    title: str
    channel: str
    scan_id: int | None
    steps_evaluated: int
    total_precautions: int
    supported_precautions: int
    tp: int
    tn: int
    fp: int
    fn: int
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    mrr: float
    faithfulness: float
    spearman: float | None


def get_db_connection():
    url = (os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL", "")).strip()
    if not url:
        raise RuntimeError("DATABASE_URL or SUPABASE_URL is not configured")
    # Handle raw passwords that may contain spaces/special characters in .env.
    try:
        parts = urlsplit(url)
        netloc = parts.netloc
        if "@" in netloc:
            auth, host = netloc.rsplit("@", 1)
            if ":" in auth:
                user, pwd = auth.split(":", 1)
                auth = f"{user}:{quote(pwd, safe='')}"
                netloc = f"{auth}@{host}"
                url = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        pass

    if "supabase.com" in url and "sslmode=" not in url:
        joiner = "&" if "?" in url else "?"
        url = f"{url}{joiner}sslmode=require"

    return psycopg2.connect(url, connect_timeout=10)


def ensure_system_eval_schema() -> None:
    """Ensure required Supabase tables/columns exist for system eval flow."""
    conn = get_db_connection()
    migrations = [
        """
        CREATE TABLE IF NOT EXISTS youtube_urls (
            id              SERIAL PRIMARY KEY,
            url             TEXT NOT NULL UNIQUE,
            video_id        TEXT,
            source_type     TEXT DEFAULT 'manual',
            source_file     TEXT,
            created_at      TIMESTAMPTZ DEFAULT now(),
            last_used_at    TIMESTAMPTZ
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_youtube_urls_video_id ON youtube_urls (video_id);",
        """
        CREATE TABLE IF NOT EXISTS system_eval (
            id                      SERIAL PRIMARY KEY,
            evaluated_at            TIMESTAMPTZ DEFAULT now(),
            model_key               TEXT DEFAULT 'qwen',
            sample_size             INTEGER DEFAULT 0,
            evaluated_scans         INTEGER DEFAULT 0,
            total_steps             INTEGER DEFAULT 0,
            total_precautions       INTEGER DEFAULT 0,
            supported_precautions   INTEGER DEFAULT 0,
            true_positive           INTEGER DEFAULT 0,
            true_negative           INTEGER DEFAULT 0,
            false_positive          INTEGER DEFAULT 0,
            false_negative          INTEGER DEFAULT 0,
            accuracy                REAL,
            precision               REAL,
            recall                  REAL,
            f1_score                REAL,
            mean_reciprocal_rank    REAL,
            faithfulness_score      REAL,
            spearman_correlation    REAL,
            details_json            JSONB,
            youtube_urls            JSONB,
            selected_urls_count     INTEGER DEFAULT 0,
            total_urls_in_pool      INTEGER DEFAULT 0,
            cum_total_steps         INTEGER DEFAULT 0,
            cum_total_precautions   INTEGER DEFAULT 0,
            cum_supported_precautions INTEGER DEFAULT 0,
            cum_true_positive       INTEGER DEFAULT 0,
            cum_true_negative       INTEGER DEFAULT 0,
            cum_false_positive      INTEGER DEFAULT 0,
            cum_false_negative      INTEGER DEFAULT 0,
            cum_accuracy            REAL,
            cum_precision           REAL,
            cum_recall              REAL,
            cum_f1_score            REAL
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_system_eval_evaluated_at ON system_eval (evaluated_at DESC);",
        """
        CREATE TABLE IF NOT EXISTS system_eval_video_results (
            id                      SERIAL PRIMARY KEY,
            eval_id                 INTEGER NOT NULL REFERENCES system_eval(id) ON DELETE CASCADE,
            video_id                TEXT,
            video_url               TEXT,
            scan_id                 INTEGER,
            steps_evaluated         INTEGER DEFAULT 0,
            total_precautions       INTEGER DEFAULT 0,
            supported_precautions   INTEGER DEFAULT 0,
            true_positive           INTEGER DEFAULT 0,
            true_negative           INTEGER DEFAULT 0,
            false_positive          INTEGER DEFAULT 0,
            false_negative          INTEGER DEFAULT 0,
            accuracy                REAL,
            precision               REAL,
            recall                  REAL,
            f1_score                REAL,
            mrr                     REAL,
            faithfulness            REAL,
            spearman                REAL,
            created_at              TIMESTAMPTZ DEFAULT now()
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_system_eval_video_eval_id ON system_eval_video_results (eval_id);",
    ]
    try:
        with conn.cursor() as cur:
            for sql in migrations:
                cur.execute(sql)
        conn.commit()
    finally:
        conn.close()


def verify_supabase_state() -> dict[str, Any]:
    """Return a compact verification summary from Supabase tables."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT COUNT(*) AS c FROM youtube_urls")
            pool_count = int((cur.fetchone() or {}).get("c") or 0)

            cur.execute("SELECT COUNT(*) AS c FROM system_eval")
            eval_count = int((cur.fetchone() or {}).get("c") or 0)

            cur.execute("SELECT COUNT(*) AS c FROM system_eval_video_results")
            video_eval_count = int((cur.fetchone() or {}).get("c") or 0)

            cur.execute(
                """
                SELECT id, evaluated_at, selected_urls_count, evaluated_scans,
                       accuracy, precision, recall, f1_score
                FROM system_eval
                ORDER BY evaluated_at DESC
                LIMIT 1
                """
            )
            latest_eval = dict(cur.fetchone() or {})
            if latest_eval.get("evaluated_at"):
                latest_eval["evaluated_at"] = latest_eval["evaluated_at"].isoformat()

        return {
            "youtube_urls_count": pool_count,
            "system_eval_count": eval_count,
            "system_eval_video_results_count": video_eval_count,
            "latest_system_eval": latest_eval or None,
        }
    finally:
        conn.close()


def extract_video_id_from_url(value: str) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
        return raw
    try:
        p = urlparse(raw)
        host = p.netloc.lower()
        path = p.path.strip("/")
        if "youtu.be" in host:
            vid = path.split("/")[0]
            return vid if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid or "") else None
        if "youtube.com" in host:
            qs = parse_qs(p.query)
            vid = (qs.get("v") or [None])[0]
            if vid and re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
                return vid
            if path.startswith("shorts/"):
                chunks = path.split("/")
                vid = chunks[1] if len(chunks) > 1 else None
                return vid if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid or "") else None
    except Exception:
        return None
    return None


def normalize_youtube_url(value: str) -> str | None:
    vid = extract_video_id_from_url(value)
    if not vid:
        return None
    return f"https://www.youtube.com/watch?v={vid}"


def extract_urls_from_text_blob(text: str) -> list[str]:
    if not text:
        return []
    found = YOUTUBE_URL_RE.findall(text)
    tokens = re.split(r"[\s,;]+", text)
    for token in tokens:
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", token or ""):
            found.append(token)

    deduped: list[str] = []
    seen = set()
    for item in found:
        n = normalize_youtube_url(item)
        if n and n not in seen:
            deduped.append(n)
            seen.add(n)
    return deduped


def extract_urls_from_pdf(path: Path) -> list[str]:
    try:
        try:
            import pymupdf as fitz
        except Exception:
            import fitz  # type: ignore

        doc = fitz.open(str(path))
        chunks: list[str] = []
        for page in doc:
            chunks.append(page.get_text() or "")
            for link in page.get_links() or []:
                if isinstance(link, dict) and link.get("uri"):
                    chunks.append(str(link["uri"]))
        doc.close()
        return extract_urls_from_text_blob("\n".join(chunks))
    except Exception:
        return []


def extract_urls_from_csv(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
    urls: list[str] = []
    for row in reader:
        if not row:
            continue
        normalized = {str(k).strip().lower(): v for k, v in row.items()}
        candidate = normalized.get("youtube_url") or normalized.get("url")
        if candidate:
            urls.extend(extract_urls_from_text_blob(str(candidate)))
    return list(dict.fromkeys(urls))


def extract_urls_from_excel(path: Path) -> list[str]:
    try:
        from openpyxl import load_workbook
    except Exception:
        return []

    wb = load_workbook(filename=str(path), read_only=True, data_only=True)
    ws = wb.active
    headers: list[str] = []
    urls: list[str] = []
    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        vals = ["" if v is None else str(v).strip() for v in row]
        if i == 1:
            headers = [h.lower() for h in vals]
            continue
        if not headers:
            continue
        row_map = {headers[idx]: vals[idx] for idx in range(min(len(headers), len(vals)))}
        candidate = row_map.get("youtube_url") or row_map.get("url")
        if candidate:
            urls.extend(extract_urls_from_text_blob(candidate))
    return list(dict.fromkeys(urls))


def extract_urls_from_file(path: Path) -> list[str]:
    lower = path.name.lower()
    if lower.endswith(".pdf"):
        return extract_urls_from_pdf(path)
    if lower.endswith(".csv"):
        return extract_urls_from_csv(path)
    if lower.endswith(".xlsx") or lower.endswith(".xls"):
        return extract_urls_from_excel(path)
    if lower.endswith(".txt"):
        return extract_urls_from_text_blob(path.read_text(encoding="utf-8", errors="ignore"))
    return []


def collect_and_upsert_urls(urls_dir: Path) -> tuple[list[str], int]:
    ensure_system_eval_schema()
    urls: list[str] = []
    if urls_dir.exists():
        for p in sorted(urls_dir.iterdir()):
            if p.is_file() and not p.name.startswith("."):
                urls.extend(extract_urls_from_file(p))

    urls = list(dict.fromkeys(urls))
    if not urls:
        return [], get_pool_size()

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            for url in urls:
                vid = extract_video_id_from_url(url)
                cur.execute(
                    """
                    INSERT INTO youtube_urls (url, video_id, source_type, source_file, last_used_at)
                    VALUES (%s, %s, %s, %s, now())
                    ON CONFLICT (url)
                    DO UPDATE SET last_used_at = now(), source_type = EXCLUDED.source_type, source_file = EXCLUDED.source_file
                    """,
                    (url, vid, "system_eval_batch", str(urls_dir)),
                )
        conn.commit()
    finally:
        conn.close()

    return urls, get_pool_size()


def get_pool_size() -> int:
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM youtube_urls")
            return int(cur.fetchone()[0])
    finally:
        conn.close()


def get_pool_urls() -> list[str]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT url FROM youtube_urls ORDER BY created_at ASC")
            return [str(r[0]) for r in cur.fetchall()]
    finally:
        conn.close()


def coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def tokenize(text: str) -> set[str]:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    words = [w for w in cleaned.split() if len(w) > 2]
    return set(words)


def average_ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j + 2) / 2.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks


def pearson_corr(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = 0.0
    den_x = den_y = 0.0
    for x, y in zip(xs, ys):
        dx = x - mx
        dy = y - my
        num += dx * dy
        den_x += dx * dx
        den_y += dy * dy
    if den_x <= 0.0 or den_y <= 0.0:
        return None
    return num / math.sqrt(den_x * den_y)


def spearman_corr(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    return pearson_corr(average_ranks(xs), average_ranks(ys))


def binary_metrics(tp: int, tn: int, fp: int, fn: int) -> tuple[float, float, float, float]:
    total = tp + tn + fp + fn
    accuracy = ((tp + tn) / total * 100.0) if total > 0 else 0.0
    precision = (tp / (tp + fp) * 100.0) if (tp + fp) > 0 else 0.0
    recall = (tp / (tp + fn) * 100.0) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return round(accuracy, 2), round(precision, 2), round(recall, 2), round(f1, 2)


def evaluate_single_output(video_id: str, video_url: str, title: str, channel: str, scan_id: int | None, output_json: dict[str, Any]) -> VideoEvalResult:
    try:
        from rule_extraction.extract_rules import override_severity
    except ModuleNotFoundError:
        sys.path.insert(0, str(ROOT))
        from rule_extraction.extract_rules import override_severity

    steps = output_json.get("steps") or []
    model_reports = output_json.get("modelReports") or {}
    qwen = model_reports.get("qwen") if isinstance(model_reports, dict) else None
    if not qwen:
        qwen = output_json.get("report") or {}

    step_analysis = qwen.get("step_safety_analysis") if isinstance(qwen, dict) else []
    if not isinstance(step_analysis, list):
        step_analysis = []

    by_step: dict[int, dict[str, Any]] = {}
    for s in step_analysis:
        if isinstance(s, dict) and isinstance(s.get("step_number"), int):
            by_step[int(s["step_number"])] = s

    tmp_rules = []
    for idx, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            continue
        step_num = step.get("step_number") if isinstance(step.get("step_number"), int) else idx
        txt = (step.get("step_text") or "").strip()
        action = (step.get("action_summary") or txt).strip()
        excerpt = (step.get("transcript_excerpt") or txt).strip()
        tmp_rules.append(
            {
                "rule_id": str(step_num),
                "suggested_severity": 1,
                "validated_severity": 1,
                "actionable_rule": action,
                "original_text": excerpt,
            }
        )

    scored_steps = override_severity(tmp_rules)
    override_by_step = {
        int(r.get("rule_id")): int(r.get("validated_severity") or 1)
        for r in scored_steps
        if str(r.get("rule_id", "")).isdigit()
    }

    tp = tn = fp = fn = 0
    scan_llm: list[float] = []
    scan_override: list[float] = []
    rr_list: list[float] = []
    total_precautions = 0
    supported_precautions = 0

    for idx, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            continue
        step_num = step.get("step_number") if isinstance(step.get("step_number"), int) else idx
        analysis = by_step.get(step_num, {})
        llm_score = coerce_float(analysis.get("risk_level"), default=float("nan"))
        if math.isnan(llm_score):
            continue
        override_score = float(override_by_step.get(step_num, 1))
        scan_llm.append(llm_score)
        scan_override.append(override_score)

        y_pred = 1 if llm_score >= 3.0 else 0
        y_true = 1 if override_score >= 3.0 else 0
        if y_true == 1 and y_pred == 1:
            tp += 1
        elif y_true == 0 and y_pred == 0:
            tn += 1
        elif y_true == 0 and y_pred == 1:
            fp += 1
        else:
            fn += 1

        matched_rules = analysis.get("matched_rules") or []
        rr = 0.0
        if isinstance(matched_rules, list) and matched_rules:
            for rank, rule in enumerate(matched_rules, start=1):
                if not isinstance(rule, dict):
                    continue
                sev = coerce_float(rule.get("severity"), default=0.0)
                if sev >= max(3.0, override_score):
                    rr = 1.0 / rank
                    break
        rr_list.append(rr)

        required_precautions = analysis.get("required_precautions") or []
        if isinstance(required_precautions, list):
            evidence_text = " ".join(
                [
                    str(step.get("step_text") or ""),
                    str(step.get("transcript_excerpt") or ""),
                    " ".join(
                        str((r.get("rule_text") or r.get("actionable_rule") or ""))
                        for r in matched_rules if isinstance(r, dict)
                    ),
                ]
            )
            evidence_tokens = tokenize(evidence_text)
            for precaution in required_precautions:
                tokens = tokenize(str(precaution))
                if not tokens:
                    continue
                total_precautions += 1
                overlap = len(tokens & evidence_tokens)
                if overlap >= 2 and (overlap / len(tokens)) >= 0.5:
                    supported_precautions += 1

    accuracy, precision, recall, f1_score = binary_metrics(tp, tn, fp, fn)
    mrr = round(sum(rr_list) / len(rr_list), 4) if rr_list else 0.0
    faithfulness = round((supported_precautions / total_precautions) * 100.0, 2) if total_precautions > 0 else 100.0
    spearman = spearman_corr(scan_llm, scan_override)

    return VideoEvalResult(
        video_id=video_id,
        video_url=video_url,
        title=title,
        channel=channel,
        scan_id=scan_id,
        steps_evaluated=len(scan_llm),
        total_precautions=total_precautions,
        supported_precautions=supported_precautions,
        tp=tp,
        tn=tn,
        fp=fp,
        fn=fn,
        accuracy=accuracy,
        precision=precision,
        recall=recall,
        f1_score=f1_score,
        mrr=mrr,
        faithfulness=faithfulness,
        spearman=(round(spearman, 4) if spearman is not None else None),
    )


def stream_analyze(api_base: str, video_id: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    extraction_obj: dict[str, Any] = {}
    reports: dict[str, dict[str, Any]] = {}
    comparison: dict[str, Any] | None = None

    with httpx.Client(timeout=300.0) as client:
        with client.stream("GET", f"{api_base}/api/analyze", params={"video_id": video_id}) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                text = line.decode("utf-8", errors="ignore") if isinstance(line, bytes) else line
                if not text.startswith("data: "):
                    continue
                payload = text[6:]
                try:
                    event = json.loads(payload)
                except Exception:
                    continue
                e_type = event.get("type")
                if e_type == "error":
                    raise RuntimeError(str(event.get("message") or "Analyze route failed"))
                if e_type == "metadata":
                    metadata = event
                elif e_type == "steps_complete":
                    steps_json = event.get("steps_json") or "{}"
                    extraction_obj = json.loads(steps_json)
                elif e_type == "safety_report":
                    key = str(event.get("model_key") or "unknown")
                    report_json = event.get("report_json") or "{}"
                    reports[key] = json.loads(report_json)
                elif e_type == "model_comparison":
                    comp = event.get("comparison_json")
                    if isinstance(comp, str):
                        comparison = json.loads(comp)
                    elif isinstance(comp, dict):
                        comparison = comp

    if not extraction_obj:
        raise RuntimeError(f"No extraction result produced for video {video_id}")

    steps = extraction_obj.get("steps") or []
    safety_categories = extraction_obj.get("safety_categories") or []
    primary = reports.get("qwen") or (next(iter(reports.values())) if reports else {})
    if not primary:
        raise RuntimeError(f"No safety report produced for video {video_id}")

    return {
        "title": metadata.get("title") or extraction_obj.get("title") or f"Video {video_id}",
        "channel": metadata.get("author") or "",
        "output_json": {
            "extraction": extraction_obj,
            "steps": steps,
            "safetyCategories": safety_categories,
            "report": primary,
            "modelReports": reports,
            "comparison": comparison or {},
        },
    }


def save_scan(api_base: str, video_id: str, video_url: str, title: str, channel: str, output_json: dict[str, Any]) -> int | None:
    report = output_json.get("report") or {}
    body = {
        "video_id": video_id,
        "video_url": video_url,
        "title": title,
        "channel": channel,
        "verdict": report.get("verdict") or "",
        "risk_score": report.get("overall_risk_score"),
        "output_json": output_json,
    }
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(f"{api_base}/api/scans", json=body)
            resp.raise_for_status()
            return int(resp.json().get("id"))
    except Exception:
        return None


def persist_batch_result(selected_urls: list[str], per_video: list[VideoEvalResult]) -> dict[str, Any]:
    if not per_video:
        raise RuntimeError("No video metrics to persist")

    avg_accuracy = round(sum(v.accuracy for v in per_video) / len(per_video), 2)
    avg_precision = round(sum(v.precision for v in per_video) / len(per_video), 2)
    avg_recall = round(sum(v.recall for v in per_video) / len(per_video), 2)
    avg_f1 = round(sum(v.f1_score for v in per_video) / len(per_video), 2)
    avg_mrr = round(sum(v.mrr for v in per_video) / len(per_video), 4)
    avg_faith = round(sum(v.faithfulness for v in per_video) / len(per_video), 2)
    spearmans = [v.spearman for v in per_video if v.spearman is not None]
    avg_spearman = round(sum(spearmans) / len(spearmans), 4) if spearmans else None

    total_steps = sum(v.steps_evaluated for v in per_video)
    total_precautions = sum(v.total_precautions for v in per_video)
    supported_precautions = sum(v.supported_precautions for v in per_video)
    tp = sum(v.tp for v in per_video)
    tn = sum(v.tn for v in per_video)
    fp = sum(v.fp for v in per_video)
    fn = sum(v.fn for v in per_video)

    details_json = {
        "notes": {
            "accuracy": "Average per-video accuracy over selected batch.",
            "precision": "Average per-video precision over selected batch.",
            "recall": "Average per-video recall over selected batch.",
            "f1_score": "Average per-video F1 over selected batch.",
            "mean_reciprocal_rank": "Average per-video MRR over selected batch.",
            "faithfulness_score": "Average per-video faithfulness over selected batch.",
            "spearman_correlation": "Average per-video Spearman over selected batch.",
        },
        "selected_urls": selected_urls,
        "scan_breakdown": [
            {
                "scan_id": v.scan_id,
                "video_id": v.video_id,
                "title": v.title,
                "scan_timestamp": None,
                "steps_evaluated": v.steps_evaluated,
                "avg_llm_risk": None,
                "avg_override_risk": None,
                "scan_spearman": v.spearman,
                "scan_mrr": v.mrr,
                "faithfulness": v.faithfulness,
                "accuracy": v.accuracy,
                "precision": v.precision,
                "recall": v.recall,
                "f1_score": v.f1_score,
            }
            for v in per_video
        ],
    }

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT COUNT(*) FROM youtube_urls")
            total_pool = int(cur.fetchone()[0])

            cur.execute(
                """
                INSERT INTO system_eval
                    (model_key, sample_size, evaluated_scans, total_steps,
                     total_precautions, supported_precautions,
                     true_positive, true_negative, false_positive, false_negative,
                     accuracy, precision, recall, f1_score,
                     mean_reciprocal_rank, faithfulness_score, spearman_correlation,
                     details_json, youtube_urls, selected_urls_count, total_urls_in_pool)
                VALUES (%s, %s, %s, %s,
                        %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s)
                RETURNING id, evaluated_at
                """,
                (
                    "qwen",
                    len(selected_urls),
                    len(per_video),
                    total_steps,
                    total_precautions,
                    supported_precautions,
                    tp,
                    tn,
                    fp,
                    fn,
                    avg_accuracy,
                    avg_precision,
                    avg_recall,
                    avg_f1,
                    avg_mrr,
                    avg_faith,
                    avg_spearman,
                    psycopg2.extras.Json(details_json),
                    psycopg2.extras.Json(selected_urls),
                    len(selected_urls),
                    total_pool,
                ),
            )
            inserted = cur.fetchone()
            eval_id = int(inserted["id"])

            for v in per_video:
                cur.execute(
                    """
                    INSERT INTO system_eval_video_results
                        (eval_id, video_id, video_url, scan_id, steps_evaluated,
                         total_precautions, supported_precautions,
                         true_positive, true_negative, false_positive, false_negative,
                         accuracy, precision, recall, f1_score, mrr, faithfulness, spearman)
                    VALUES (%s, %s, %s, %s, %s,
                            %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        eval_id,
                        v.video_id,
                        v.video_url,
                        v.scan_id,
                        v.steps_evaluated,
                        v.total_precautions,
                        v.supported_precautions,
                        v.tp,
                        v.tn,
                        v.fp,
                        v.fn,
                        v.accuracy,
                        v.precision,
                        v.recall,
                        v.f1_score,
                        v.mrr,
                        v.faithfulness,
                        v.spearman,
                    ),
                )

            cur.execute(
                """
                SELECT
                    COALESCE(SUM(steps_evaluated), 0) AS total_steps,
                    COALESCE(SUM(total_precautions), 0) AS total_precautions,
                    COALESCE(SUM(supported_precautions), 0) AS supported_precautions,
                    COALESCE(SUM(true_positive), 0) AS tp,
                    COALESCE(SUM(true_negative), 0) AS tn,
                    COALESCE(SUM(false_positive), 0) AS fp,
                    COALESCE(SUM(false_negative), 0) AS fn
                FROM system_eval_video_results
                """
            )
            agg = cur.fetchone() or {}
            cum_acc, cum_prec, cum_rec, cum_f1 = binary_metrics(
                int(agg.get("tp") or 0),
                int(agg.get("tn") or 0),
                int(agg.get("fp") or 0),
                int(agg.get("fn") or 0),
            )
            cur.execute(
                """
                UPDATE system_eval
                SET cum_total_steps = %s,
                    cum_total_precautions = %s,
                    cum_supported_precautions = %s,
                    cum_true_positive = %s,
                    cum_true_negative = %s,
                    cum_false_positive = %s,
                    cum_false_negative = %s,
                    cum_accuracy = %s,
                    cum_precision = %s,
                    cum_recall = %s,
                    cum_f1_score = %s
                WHERE id = %s
                """,
                (
                    int(agg.get("total_steps") or 0),
                    int(agg.get("total_precautions") or 0),
                    int(agg.get("supported_precautions") or 0),
                    int(agg.get("tp") or 0),
                    int(agg.get("tn") or 0),
                    int(agg.get("fp") or 0),
                    int(agg.get("fn") or 0),
                    cum_acc,
                    cum_prec,
                    cum_rec,
                    cum_f1,
                    eval_id,
                ),
            )

        conn.commit()
        return {
            "eval_id": eval_id,
            "evaluated_at": inserted["evaluated_at"].isoformat() if inserted and inserted.get("evaluated_at") else datetime.now(timezone.utc).isoformat(),
            "evaluated_scans": len(per_video),
            "selected_urls_count": len(selected_urls),
            "metrics": {
                "accuracy": avg_accuracy,
                "precision": avg_precision,
                "recall": avg_recall,
                "f1_score": avg_f1,
                "mean_reciprocal_rank": avg_mrr,
                "faithfulness_score": avg_faith,
                "spearman_correlation": avg_spearman,
            },
        }
    finally:
        conn.close()


def run_batch(api_base: str, urls_dir: Path, from_index: int, to_index: int) -> dict[str, Any]:
    ensure_system_eval_schema()
    added_urls, total_pool_after = collect_and_upsert_urls(urls_dir)
    pool = get_pool_urls()

    if not pool:
        raise RuntimeError("youtube_urls pool is empty. Add files into system_eval/youtube_urls first.")

    if from_index < 1:
        raise RuntimeError("--from-index must be >= 1")
    if to_index < from_index:
        raise RuntimeError("--to-index must be >= --from-index")
    if to_index > len(pool):
        raise RuntimeError(f"--to-index ({to_index}) exceeds total URLs in pool ({len(pool)})")

    selected_urls = pool[from_index - 1:to_index]

    print(f"Total URLs in pool: {len(pool)}")
    print(f"New/updated URLs from folder: {len(added_urls)}")
    print(f"Selected range: {from_index}..{to_index} ({len(selected_urls)} urls)")

    per_video: list[VideoEvalResult] = []
    failures: list[dict[str, str]] = []

    for idx, url in enumerate(selected_urls, start=from_index):
        video_id = extract_video_id_from_url(url)
        if not video_id:
            failures.append({"url": url, "error": "Invalid YouTube URL"})
            continue

        print(f"[{idx}] Analyzing {video_id} ...")
        try:
            result = stream_analyze(api_base, video_id)
            output_json = result["output_json"]
            title = str(result.get("title") or f"Video {video_id}")
            channel = str(result.get("channel") or "")
            scan_id = save_scan(api_base, video_id, url, title, channel, output_json)
            per_video.append(evaluate_single_output(video_id, url, title, channel, scan_id, output_json))
            print(f"[{idx}] done | title={title}")
        except Exception as exc:
            failures.append({"url": url, "error": str(exc)})
            print(f"[{idx}] failed | {exc}")

    if not per_video:
        raise RuntimeError(f"No videos evaluated successfully. Failures: {len(failures)}")

    summary = persist_batch_result(selected_urls, per_video)
    summary["failures"] = failures
    summary["per_video"] = [
        {
            "video_id": v.video_id,
            "video_url": v.video_url,
            "title": v.title,
            "scan_id": v.scan_id,
            "metrics": {
                "accuracy": v.accuracy,
                "precision": v.precision,
                "recall": v.recall,
                "f1_score": v.f1_score,
                "mean_reciprocal_rank": v.mrr,
                "faithfulness_score": v.faithfulness,
                "spearman_correlation": v.spearman,
            },
            "steps_evaluated": v.steps_evaluated,
            "precautions": {
                "total": v.total_precautions,
                "supported": v.supported_precautions,
            },
        }
        for v in per_video
    ]
    summary["total_urls_in_pool"] = total_pool_after
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch system evaluation from URL pool")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000", help="Backend base URL")
    parser.add_argument("--urls-dir", default=str(Path(__file__).resolve().parent / "youtube_urls"), help="Folder containing PDF/CSV/XLSX/TXT with URLs")
    parser.add_argument("--from-index", type=int, help="1-based start index in youtube_urls pool")
    parser.add_argument("--to-index", type=int, help="1-based end index in youtube_urls pool")
    parser.add_argument("--collect-only", action="store_true", help="Only collect URLs into youtube_urls table, do not run analysis")
    parser.add_argument("--verify-db", action="store_true", help="Print verification summary from Supabase tables")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent / "last_batch_result.json"), help="Output result JSON path")
    args = parser.parse_args()

    if args.collect_only:
        urls_dir = Path(args.urls_dir)
        added_urls, total_pool_after = collect_and_upsert_urls(urls_dir)
        summary = {
            "collect_only": True,
            "added_or_updated_urls": len(added_urls),
            "total_urls_in_pool": total_pool_after,
            "sample_urls": added_urls[:10],
        }
        if args.verify_db:
            summary["verification"] = verify_supabase_state()
        print(json.dumps(summary, indent=2))
        return 0

    if args.from_index is None or args.to_index is None:
        raise SystemExit("--from-index and --to-index are required unless --collect-only is used")

    summary = run_batch(
        api_base=args.api_base.rstrip("/"),
        urls_dir=Path(args.urls_dir),
        from_index=args.from_index,
        to_index=args.to_index,
    )

    if args.verify_db:
        summary["verification"] = verify_supabase_state()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\nBatch evaluation complete")
    print(json.dumps({
        "eval_id": summary.get("eval_id"),
        "evaluated_scans": summary.get("evaluated_scans"),
        "metrics": summary.get("metrics"),
        "failures": len(summary.get("failures", [])),
    }, indent=2))
    print(f"Saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
