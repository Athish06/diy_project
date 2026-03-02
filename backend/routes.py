"""
FastAPI routes — new pipeline:

1. /api/analyze (SSE)  — transcript → LLM extraction → is_diy check →
                          embed steps → pgvector match → LLM safety assessment
2. /api/rules (GET)    — query safety_rules DB with filters
3. /api/filter_options — get distinct filter values
4. /api/extract_rules  — upload PDFs, run extraction pipeline
5. /api/rules_by_document — PDF-grouped rule counts
6. /api/extraction_runs — all runs with evaluation
7. /api/rules_by_run   — rules filtered by run_id

API key is read from .env at all times — no user-facing key management.
"""

import asyncio
import base64
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, List
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Query, UploadFile, File, WebSocket, WebSocketDisconnect, Request
from sse_starlette.sse import EventSourceResponse

from cache import AnalysisCache
from transcript import fetch_transcript, fetch_metadata
from groq_client import extract_steps_stream
from embeddings_service import EmbeddingService
from safety_analyzer import analyze_safety
from safety import (
    extract_rules_v2,
    extract_rules_with_progress,
    fetch_rules_from_db,
    fetch_filter_options_from_db,
    fetch_rules_by_document,
    fetch_extraction_runs,
    fetch_rules_by_run,
    run_brutal_evaluation,
    _save_evaluation_results,
    _get_db_connection,
)

router = APIRouter(prefix="/api")
ws_router = APIRouter()  # No prefix for WebSocket
_extract_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="extract")

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
_cache = AnalysisCache()

MAX_TRANSCRIPT_LENGTH = 100_000

# Multi-model configuration: both models run in parallel for safety analysis
ANALYSIS_MODELS = [
    {"key": "qwen", "model_id": "qwen/qwen3-32b", "label": "Qwen3 32B"},
    {"key": "gpt_oss", "model_id": "openai/gpt-oss-20b", "label": "GPT-OSS 20B"},
]


def _get_api_key() -> str:
    return os.getenv("GROQ_API_KEY", "")


def _get_model() -> str:
    return os.getenv("MODEL", "qwen/qwen3-32b")


def _build_model_comparison(reports: dict[str, dict]) -> dict:
    """Build a comparison table across all model reports (no LLM needed)."""
    comparison = {"models": [], "aspects": []}

    model_keys = []
    for m in ANALYSIS_MODELS:
        key = m["key"]
        if key in reports and reports[key]:
            model_keys.append(key)
            comparison["models"].append({"key": key, "label": m["label"]})

    if len(model_keys) < 2:
        return comparison

    # Build aspect rows
    def _aspect(name: str, extractor):
        values = {}
        for k in model_keys:
            try:
                values[k] = extractor(reports[k])
            except Exception:
                values[k] = "N/A"
        # check agreement
        unique = set(str(v) for v in values.values() if v != "N/A")
        return {"aspect": name, "values": values, "agreement": len(unique) <= 1}

    comparison["aspects"] = [
        _aspect("Verdict", lambda r: r.get("verdict", "N/A")),
        _aspect("Overall Risk Score", lambda r: round(r.get("overall_risk_score", 0), 1)),
        _aspect("Parent Monitoring Required", lambda r: "Yes" if r.get("parent_monitoring_required") else "No"),
        _aspect("Critical Concerns Count", lambda r: len(r.get("critical_concerns", []))),
        _aspect("Total Missing Precautions", lambda r: sum(
            len(s.get("missing_precautions", [])) for s in r.get("step_safety_analysis", [])
        )),
        _aspect("Average Step Risk Level", lambda r: round(
            sum(s.get("risk_level", 0) for s in r.get("step_safety_analysis", []))
            / max(len(r.get("step_safety_analysis", [])), 1), 1
        )),
        _aspect("High-Risk Steps (>=4)", lambda r: sum(
            1 for s in r.get("step_safety_analysis", []) if s.get("risk_level", 0) >= 4
        )),
        _aspect("Total Matched Rules", lambda r: sum(
            len(s.get("matched_rules", [])) for s in r.get("step_safety_analysis", [])
        )),
        _aspect("Safety Measures Identified", lambda r: len(r.get("safety_measures_in_video", []))),
        _aspect("Recommended Additions", lambda r: len(r.get("recommended_additional_measures", []))),
        _aspect("Steps Analyzed", lambda r: len(r.get("step_safety_analysis", []))),
    ]

    return comparison


# ---------------------------------------------------------------------------
# Health / config check
# ---------------------------------------------------------------------------

@router.get("/health")
async def health():
    key = _get_api_key()
    db = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL", "")
    return {
        "status": "ok",
        "api_key_configured": bool(key),
        "database_configured": bool(db),
        "model": _get_model(),
    }


# ---------------------------------------------------------------------------
# DIY analysis — SSE stream  (the main pipeline)
# ---------------------------------------------------------------------------

@router.get("/analyze")
async def analyze_diy(video_id: str = Query(...)):
    """
    Server-Sent Events stream implementing the full analysis pipeline:

    Events emitted:
      status         — progress messages
      metadata       — video title + author
      steps_delta    — streaming LLM tokens
      steps_complete — full extraction JSON (includes is_diy, safety_categories)
      not_diy        — video is not a DIY tutorial
      safety_report  — final LLM safety assessment
      done           — analysis complete
      error          — something went wrong
    """

    async def event_generator():
        try:
            api_key = _get_api_key()
            if not api_key:
                yield {
                    "event": "message",
                    "data": json.dumps({
                        "type": "error",
                        "message": "GROQ_API_KEY not configured on server. Check .env file.",
                    }),
                }
                return

            model = _get_model()

            # ------ Check cache ------
            cached = _cache.get(video_id)
            if cached:
                cached_data = json.loads(cached)
                async with httpx.AsyncClient() as client:
                    try:
                        meta = await fetch_metadata(client, video_id)
                        yield {
                            "event": "message",
                            "data": json.dumps({
                                "type": "metadata",
                                "title": meta.title,
                                "author": meta.author,
                            }),
                        }
                    except Exception:
                        pass

                if cached_data.get("is_diy") is False:
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "not_diy",
                            "message": "This video is not a DIY tutorial.",
                        }),
                    }
                    yield {"event": "message", "data": json.dumps({"type": "done"})}
                    return

                if "steps_json" in cached_data:
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "steps_complete",
                            "steps_json": cached_data["steps_json"],
                            "is_diy": True,
                            "safety_categories": cached_data.get("safety_categories", []),
                        }),
                    }
                # Emit cached multi-model reports
                cached_all = cached_data.get("all_reports_json", {})
                if cached_all:
                    for m in ANALYSIS_MODELS:
                        rpt = cached_all.get(m["key"])
                        if rpt:
                            yield {
                                "event": "message",
                                "data": json.dumps({
                                    "type": "safety_report",
                                    "model_key": m["key"],
                                    "model_label": m["label"],
                                    "report_json": rpt,
                                }),
                            }
                elif "report_json" in cached_data:
                    # Legacy single-model cache fallback
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "safety_report",
                            "model_key": ANALYSIS_MODELS[0]["key"],
                            "model_label": ANALYSIS_MODELS[0]["label"],
                            "report_json": cached_data["report_json"],
                        }),
                    }
                # Emit cached comparison
                if "comparison_json" in cached_data:
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "model_comparison",
                            "comparison_json": cached_data["comparison_json"],
                        }),
                    }
                yield {"event": "message", "data": json.dumps({"type": "done"})}
                return

            # ------ 1. Fetch transcript + metadata ------
            async with httpx.AsyncClient() as client:
                yield {
                    "event": "message",
                    "data": json.dumps({
                        "type": "status",
                        "message": "Fetching video transcript...",
                    }),
                }

                transcript_task = asyncio.create_task(fetch_transcript(client, video_id))
                metadata_task = asyncio.create_task(fetch_metadata(client, video_id))

                transcript_result, metadata_result = await asyncio.gather(
                    transcript_task, metadata_task, return_exceptions=True
                )

                if isinstance(transcript_result, Exception):
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "error",
                            "message": str(transcript_result),
                        }),
                    }
                    return

                video_title = ""
                if not isinstance(metadata_result, Exception):
                    video_title = metadata_result.title
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "metadata",
                            "title": metadata_result.title,
                            "author": metadata_result.author,
                        }),
                    }

                # Validate transcript length
                if len(transcript_result.text) > MAX_TRANSCRIPT_LENGTH:
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "error",
                            "message": (
                                f"Transcript is too long ({len(transcript_result.text) // 1000}k chars). "
                                f"Maximum is {MAX_TRANSCRIPT_LENGTH // 1000}k characters."
                            ),
                        }),
                    }
                    return

                # ------ 2. Extract DIY steps via Groq (streaming) ------
                yield {
                    "event": "message",
                    "data": json.dumps({
                        "type": "status",
                        "message": "Extracting DIY steps from transcript...",
                    }),
                }

                steps_json = ""
                async for event in extract_steps_stream(
                    client, api_key, model, transcript_result.text
                ):
                    if event["type"] == "steps_delta":
                        yield {"event": "message", "data": json.dumps(event)}
                    elif event["type"] == "steps_complete":
                        steps_json = event["steps_json"]

                if not steps_json:
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "error",
                            "message": "Failed to extract steps from transcript.",
                        }),
                    }
                    return

                # ------ 3. Check is_diy ------
                parsed_extraction = json.loads(steps_json)
                is_diy = parsed_extraction.get("is_diy", True)
                safety_categories = parsed_extraction.get("safety_categories", ["general_safety"])
                steps_list = []

                if isinstance(parsed_extraction, dict):
                    steps_list = parsed_extraction.get("steps", [])
                elif isinstance(parsed_extraction, list):
                    steps_list = parsed_extraction

                # Send steps_complete with is_diy and safety_categories
                yield {
                    "event": "message",
                    "data": json.dumps({
                        "type": "steps_complete",
                        "steps_json": steps_json,
                        "is_diy": is_diy,
                        "safety_categories": safety_categories,
                    }),
                }

                if not is_diy or not steps_list:
                    _cache.set(video_id, json.dumps({"is_diy": False}))
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "not_diy",
                            "message": "This video is not a DIY tutorial. No safety analysis needed.",
                        }),
                    }
                    yield {"event": "message", "data": json.dumps({"type": "done"})}
                    return

                # ------ 4. Embed steps ------
                yield {
                    "event": "message",
                    "data": json.dumps({
                        "type": "status",
                        "message": f"Generating embeddings for {len(steps_list)} steps...",
                    }),
                }

                embed_service = await asyncio.to_thread(EmbeddingService.get_instance)
                step_embeddings = await asyncio.to_thread(
                    embed_service.embed_steps, steps_list
                )

                # ------ 5. Match against safety rules via pgvector ------
                yield {
                    "event": "message",
                    "data": json.dumps({
                        "type": "status",
                        "message": "Matching steps against safety rules database...",
                    }),
                }

                rules_per_step: dict[int, list] = {}
                for step, embedding in zip(steps_list, step_embeddings):
                    step_num = step.get("step_number", 0)
                    try:
                        matched = await asyncio.to_thread(
                            embed_service.find_rules_for_step,
                            step,
                            embedding,
                            safety_categories,
                        )
                        rules_per_step[step_num] = matched
                    except Exception as e:
                        rules_per_step[step_num] = []
                        yield {
                            "event": "message",
                            "data": json.dumps({
                                "type": "status",
                                "message": f"Rule matching for step {step_num} skipped: {e}",
                            }),
                        }

                total_matched = sum(len(v) for v in rules_per_step.values())
                yield {
                    "event": "message",
                    "data": json.dumps({
                        "type": "status",
                        "message": (
                            f"Found {total_matched} matching rules across "
                            f"{len(steps_list)} steps. Running safety assessment..."
                        ),
                    }),
                }

                # ------ 6. Multi-model safety assessment (parallel) ------
                yield {
                    "event": "message",
                    "data": json.dumps({
                        "type": "status",
                        "message": f"Running safety assessment across {len(ANALYSIS_MODELS)} models...",
                    }),
                }

                async def _run_model(m: dict) -> tuple[str, dict | None, str | None]:
                    """Run safety analysis for a single model, return (key, report, error)."""
                    try:
                        r = await analyze_safety(
                            steps=steps_list,
                            rules_per_step=rules_per_step,
                            safety_categories=safety_categories,
                            video_title=video_title,
                            api_key=api_key,
                            model=m["model_id"],
                        )
                        return (m["key"], r, None)
                    except Exception as exc:
                        return (m["key"], None, str(exc))

                model_tasks = [_run_model(m) for m in ANALYSIS_MODELS]
                model_results = await asyncio.gather(*model_tasks)

                all_reports: dict[str, dict] = {}
                all_reports_json: dict[str, str] = {}
                primary_report_json = "{}"

                for key, rpt, err in model_results:
                    if rpt:
                        all_reports[key] = rpt
                        rpt_json = json.dumps(rpt)
                        all_reports_json[key] = rpt_json
                        # Find label
                        label = next((m["label"] for m in ANALYSIS_MODELS if m["key"] == key), key)
                        yield {
                            "event": "message",
                            "data": json.dumps({
                                "type": "safety_report",
                                "model_key": key,
                                "model_label": label,
                                "report_json": rpt_json,
                            }),
                        }
                        if key == ANALYSIS_MODELS[0]["key"]:
                            primary_report_json = rpt_json
                    else:
                        label = next((m["label"] for m in ANALYSIS_MODELS if m["key"] == key), key)
                        yield {
                            "event": "message",
                            "data": json.dumps({
                                "type": "status",
                                "message": f"Safety assessment error for {label}: {err}",
                            }),
                        }

                # ------ 6b. Build comparison table (no LLM) ------
                comparison = _build_model_comparison(all_reports)
                comparison_json = json.dumps(comparison)
                yield {
                    "event": "message",
                    "data": json.dumps({
                        "type": "model_comparison",
                        "comparison_json": comparison_json,
                    }),
                }

                # ------ 7. Cache result ------
                cache_data = json.dumps({
                    "is_diy": True,
                    "steps_json": steps_json,
                    "safety_categories": safety_categories,
                    "report_json": primary_report_json,
                    "all_reports_json": {k: v for k, v in all_reports_json.items()},
                    "comparison_json": comparison_json,
                })
                _cache.set(video_id, cache_data)

                yield {"event": "message", "data": json.dumps({"type": "done"})}

        except Exception as e:
            yield {
                "event": "message",
                "data": json.dumps({"type": "error", "message": str(e)}),
            }

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# Safety rules endpoints
# ---------------------------------------------------------------------------

@router.get("/rules")
async def get_rules(
    category: Optional[str] = Query(None),
    severity: Optional[int] = Query(None),
    document: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    run_id: Optional[int] = Query(None),
    page: int = Query(1),
    per_page: int = Query(50),
):
    try:
        if run_id is not None:
            result = await asyncio.to_thread(
                fetch_rules_by_run,
                run_id=run_id,
                page=page,
                per_page=per_page,
            )
            return result

        result = await asyncio.to_thread(
            fetch_rules_from_db,
            category=category,
            severity=severity,
            document=document,
            search=search,
            page=page,
            per_page=per_page,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/filter_options")
async def get_filter_options():
    try:
        result = await asyncio.to_thread(fetch_filter_options_from_db)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rules_by_document")
async def get_rules_by_document():
    """Get rules grouped by source_document for PDF card view."""
    try:
        result = await asyncio.to_thread(fetch_rules_by_document)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/extraction_runs")
async def get_extraction_runs():
    """Get all extraction runs with evaluation results."""
    try:
        result = await asyncio.to_thread(fetch_extraction_runs)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/extract_rules")
async def extract_rules(files: List[UploadFile] = File(default=[])):
    """Accept one or more PDF uploads, run extraction pipeline on each, return results."""

    if not files:
        raise HTTPException(status_code=400, detail="No files provided.")

    results = []
    errors = []

    for file in files:
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            errors.append({"file": file.filename or "unknown", "error": "Not a PDF file"})
            continue

        tmp = Path(tempfile.gettempdir()) / file.filename
        content = await file.read()
        tmp.write_bytes(content)

        try:
            result = await asyncio.to_thread(
                extract_rules_v2,
                str(tmp),
                file.filename,
            )
            results.append({
                "file": file.filename,
                "run_id": result["run_id"],
                "extraction": result["extraction"],
                "evaluation_results": result["evaluation_results"],
            })
        except Exception as e:
            errors.append({"file": file.filename, "error": str(e)})
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass

    return {
        "results": results,
        "errors": errors,
        "total_files": len(files),
        "successful": len(results),
        "failed": len(errors),
    }


@router.post("/run_evaluation/{run_id}")
async def trigger_evaluation(run_id: int):
    """Run brutal evaluation on an existing extraction run."""
    import psycopg2.extras as pge

    try:
        conn = _get_db_connection()
        try:
            # Get run info
            with conn.cursor(cursor_factory=pge.RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, source_documents, json_source_file FROM extraction_runs WHERE id = %s",
                    (run_id,),
                )
                run = cur.fetchone()
                if not run:
                    raise HTTPException(status_code=404, detail=f"Run #{run_id} not found")

            # Get rules for this run
            with conn.cursor(cursor_factory=pge.RealDictCursor) as cur:
                cur.execute(
                    """SELECT rule_id, original_text, actionable_rule, materials,
                              suggested_severity, validated_severity, categories,
                              source_document, page_number, section_heading
                       FROM safety_rules WHERE run_id = %s""",
                    (run_id,),
                )
                rules = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

        if not rules:
            return {"run_id": run_id, "error": "No rules found for this run"}

        # Build minimal extraction data for evaluation
        extraction_data = {"rules": rules}

        # We can't evaluate without the PDF file. Return structure-only checks.
        evaluation = await asyncio.to_thread(
            _run_structure_evaluation, extraction_data
        )

        await asyncio.to_thread(_save_evaluation_results, run_id, evaluation)

        return {"run_id": run_id, "evaluation_results": evaluation}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _run_structure_evaluation(extraction_data: dict) -> dict:
    """Structural evaluation (no PDF needed): rule structure, categories, severity."""
    rules = extraction_data.get("rules", [])
    if not rules:
        return {"total_rules": 0, "overall_accuracy": 100.0, "checks": {}}

    ALLOWED_CATEGORIES = {
        "electrical", "chemical", "woodworking", "power_tools",
        "heat_fire", "mechanical", "PPE_required", "child_safety",
        "toxic_exposure", "ventilation", "structural", "general_safety",
    }
    HAZARD_KEYWORDS = [
        "toxic", "fatal", "death", "electrocution", "fire",
        "explosion", "asbestos", "cyanide", "carbon monoxide",
        "burn", "amputation", "crush",
    ]
    IMPERATIVE_STARTERS = {
        "wear", "use", "ensure", "inspect", "verify", "check", "avoid",
        "maintain", "keep", "store", "place", "install", "remove", "clean",
        "replace", "test", "secure", "ground", "disconnect", "apply",
        "protect", "follow", "do", "provide", "label", "mark", "cover",
        "ventilate", "monitor", "report", "shut", "turn", "lock",
        "never", "always", "immediately", "properly", "regularly",
        "operate", "handle", "dispose", "measure", "attach",
    }

    check_totals = {
        "rule_structure": {"passed": 0, "total": 0},
        "category_validity": {"passed": 0, "total": 0},
        "severity_consistency": {"passed": 0, "total": 0},
    }
    results_per_rule = []

    for rule in rules:
        actionable = (rule.get("actionable_rule") or "").strip()
        categories = rule.get("categories", [])
        suggested_sev = rule.get("suggested_severity") or 1
        validated_sev = rule.get("validated_severity") or suggested_sev
        original_text = (rule.get("original_text") or "").lower()

        checks = {}
        failed = []

        # Rule structure
        rule_ok = False
        if actionable:
            first_word = actionable.split()[0].lower().rstrip(".,;:")
            rule_ok = first_word in IMPERATIVE_STARTERS
            if not rule_ok and len(actionable.split()) > 1:
                second_word = actionable.split()[1].lower().rstrip(".,;:")
                if first_word in {"always", "never", "immediately", "properly", "regularly", "strictly", "not", "do"}:
                    rule_ok = second_word in IMPERATIVE_STARTERS
        checks["rule_structure"] = rule_ok
        check_totals["rule_structure"]["total"] += 1
        if rule_ok:
            check_totals["rule_structure"]["passed"] += 1
        else:
            failed.append("rule_structure")

        # Category validity
        cats_valid = all(c in ALLOWED_CATEGORIES for c in categories) if categories else True
        checks["category_validity"] = cats_valid
        check_totals["category_validity"]["total"] += 1
        if cats_valid:
            check_totals["category_validity"]["passed"] += 1
        else:
            failed.append("category_validity")

        # Severity consistency
        combined = original_text + " " + actionable.lower()
        has_hazard = any(kw in combined for kw in HAZARD_KEYWORDS)
        sev_ok = True
        if has_hazard and validated_sev < 3:
            sev_ok = False
        if validated_sev < suggested_sev:
            sev_ok = False
        checks["severity_consistency"] = sev_ok
        check_totals["severity_consistency"]["total"] += 1
        if sev_ok:
            check_totals["severity_consistency"]["passed"] += 1
        else:
            failed.append("severity_consistency")

        results_per_rule.append({
            "rule_id": str(rule.get("rule_id", "")),
            "actionable_rule": actionable[:100],
            "checks": checks,
            "all_passed": len(failed) == 0,
            "failed_checks": failed,
        })

    total_checks = sum(ct["total"] for ct in check_totals.values())
    total_passed = sum(ct["passed"] for ct in check_totals.values())
    per_check_accuracy = {}
    for name, ct in check_totals.items():
        per_check_accuracy[name] = round(ct["passed"] / ct["total"] * 100, 1) if ct["total"] > 0 else 100.0

    overall = round(total_passed / total_checks * 100, 1) if total_checks > 0 else 100.0
    failed_rules = [r for r in results_per_rule if not r["all_passed"]]

    return {
        "total_rules": len(rules),
        "total_checks": total_checks,
        "checks_passed": total_passed,
        "overall_accuracy": overall,
        "per_check_accuracy": per_check_accuracy,
        "rules_all_passed": len(rules) - len(failed_rules),
        "rules_with_failures": len(failed_rules),
        "failed_rules": failed_rules[:50],
        "evaluation_type": "structural",
    }


# ---------------------------------------------------------------------------
# Completed Scans (persistent history)
# ---------------------------------------------------------------------------

@router.post("/scans")
async def save_scan(request: Request):
    """Save a completed scan to the database."""
    import psycopg2.extras
    body = await request.json()
    video_id = body.get("video_id", "")
    video_url = body.get("video_url", "")
    title = body.get("title", "")
    channel = body.get("channel", "")
    verdict = body.get("verdict", "")
    risk_score = body.get("risk_score")
    output_json = body.get("output_json", {})
    model_reports = body.get("output_json", {}).get("modelReports")
    comparison_data = body.get("output_json", {}).get("comparison")

    if not video_id or not title:
        raise HTTPException(status_code=400, detail="video_id and title are required")

    conn = _get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO completed_scans
                    (video_id, video_url, title, channel, verdict, risk_score, output_json,
                     model_reports, comparison_data)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, scan_timestamp
                """,
                (video_id, video_url, title, channel, verdict, risk_score,
                 psycopg2.extras.Json(output_json),
                 psycopg2.extras.Json(model_reports) if model_reports else None,
                 psycopg2.extras.Json(comparison_data) if comparison_data else None),
            )
            row = cur.fetchone()
            conn.commit()
            return {"id": row[0], "scan_timestamp": row[1].isoformat()}
    finally:
        conn.close()


@router.get("/scans")
async def list_scans():
    """Fetch recent scan history (latest 50)."""
    conn = _get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, video_id, video_url, title, channel, verdict,
                       risk_score, scan_timestamp
                FROM completed_scans
                ORDER BY scan_timestamp DESC
                LIMIT 50
                """
            )
            rows = cur.fetchall()
            return {
                "scans": [
                    {
                        "id": r[0],
                        "video_id": r[1],
                        "video_url": r[2],
                        "title": r[3],
                        "channel": r[4],
                        "verdict": r[5],
                        "risk_score": r[6],
                        "scan_timestamp": r[7].isoformat() if r[7] else None,
                    }
                    for r in rows
                ]
            }
    finally:
        conn.close()


@router.get("/scans/{scan_id}")
async def get_scan(scan_id: int):
    """Fetch a single scan with full output."""
    conn = _get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, video_id, video_url, title, channel, verdict,
                       risk_score, scan_timestamp, output_json
                FROM completed_scans
                WHERE id = %s
                """,
                (scan_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Scan not found")
            return {
                "id": row[0],
                "video_id": row[1],
                "video_url": row[2],
                "title": row[3],
                "channel": row[4],
                "verdict": row[5],
                "risk_score": row[6],
                "scan_timestamp": row[7].isoformat() if row[7] else None,
                "output_json": row[8],
            }
    finally:
        conn.close()


# ---------------------------------------------------------------------------

@ws_router.websocket("/ws/extract")
async def ws_extract(ws: WebSocket):
    """
    WebSocket extraction with real-time progress.

    Protocol:
      Client sends: {"files": [{"name": "doc.pdf", "data": "<base64>"}]}
      Server sends: {"step": "...", ...detail...} for each progress event
      Server sends: {"step": "complete", ...} or {"step": "error", ...}
    """
    await ws.accept()

    try:
        # 1. Receive file data from client
        raw = await ws.receive_text()
        msg = json.loads(raw)
        files_data = msg.get("files", [])

        if not files_data:
            await ws.send_json({"step": "error", "status": "No files provided"})
            await ws.close()
            return

        loop = asyncio.get_event_loop()
        all_results = []

        for file_info in files_data:
            file_name = file_info.get("name", "unknown.pdf")
            file_b64 = file_info.get("data", "")

            if not file_b64:
                await ws.send_json({
                    "step": "error",
                    "status": f"No data for file: {file_name}",
                })
                continue

            # Decode base64 and save to temp file
            file_bytes = base64.b64decode(file_b64)
            tmp = tempfile.NamedTemporaryFile(
                delete=False, suffix=".pdf", prefix="extract_"
            )
            tmp.write(file_bytes)
            tmp.close()
            tmp_path = tmp.name

            # Create a thread-safe queue for progress events
            import queue
            progress_queue: queue.Queue = queue.Queue()

            def progress_callback(step: str, detail: dict):
                """Called from the extraction thread — pushes to queue."""
                progress_queue.put({"step": step, **detail})

            def run_extraction():
                """Run in thread pool."""
                try:
                    return extract_rules_with_progress(
                        tmp_path, file_name, progress_callback
                    )
                except Exception as e:
                    progress_queue.put({
                        "step": "error",
                        "status": f"Extraction failed: {str(e)}",
                    })
                    return None

            # Start extraction in thread pool
            future = loop.run_in_executor(_extract_pool, run_extraction)

            # Poll the progress queue and send events to WebSocket
            while not future.done():
                try:
                    event = progress_queue.get_nowait()
                    await ws.send_json(event)
                except queue.Empty:
                    pass
                await asyncio.sleep(0.1)

            # Drain any remaining events
            while not progress_queue.empty():
                event = progress_queue.get_nowait()
                await ws.send_json(event)

            result = future.result()
            if result:
                all_results.append(result)

            # Cleanup temp file
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        # Final summary
        await ws.send_json({
            "step": "done",
            "status": f"All files processed ({len(all_results)} succeeded)",
            "results": [
                {
                    "run_id": r.get("run_id"),
                    "rule_count": r.get("extraction", {}).get("rule_count", 0),
                    "accuracy": r.get("evaluation_results", {}).get("overall_accuracy"),
                }
                for r in all_results
            ],
        })

    except WebSocketDisconnect:
        pass
    except json.JSONDecodeError:
        await ws.send_json({"step": "error", "status": "Invalid JSON message"})
    except Exception as e:
        try:
            await ws.send_json({"step": "error", "status": str(e)})
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass

