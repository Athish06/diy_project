"""
FastAPI routes — full analysis pipeline and safety rules management.

Endpoints:
  1. /api/analyze (SSE)  — transcript → LLM extraction → is_diy check →
                           embed steps → pgvector match → LLM safety assessment
  2. /api/rules (GET)    — query safety_rules DB with filters
  3. /api/filter_options — get distinct filter values
  4. /api/extract_rules  — upload PDFs, run extraction pipeline
  5. /api/rules_by_document — PDF-grouped rule counts
  6. /api/extraction_runs — all runs with evaluation
  7. /api/rules_by_run   — rules filtered by run_id
  8. /api/scans           — completed scan history (CRUD)
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
from fastapi import (
    APIRouter, HTTPException, Query, UploadFile, File,
    WebSocket, WebSocketDisconnect, Request,
)
from sse_starlette.sse import EventSourceResponse

from core.cache import AnalysisCache
from core.config import get_api_key, get_model, get_database_url
from services.transcript import fetch_transcript, fetch_metadata
from services.groq_client import extract_steps_stream
from services.embeddings import EmbeddingService
from services.safety_analyzer import analyze_safety
from extraction.pipeline import extract_rules_v2, extract_rules_with_progress
from extraction.evaluation import (
    run_brutal_evaluation,
    save_evaluation_results,
    run_structure_evaluation,
)
from db.connection import get_db_connection
from db.queries import (
    fetch_rules_from_db,
    fetch_filter_options_from_db,
    fetch_rules_by_document,
    fetch_extraction_runs,
    fetch_rules_by_run,
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

    def _aspect(name: str, extractor):
        values = {}
        for k in model_keys:
            try:
                values[k] = extractor(reports[k])
            except Exception:
                values[k] = "N/A"
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
    key = get_api_key()
    db = get_database_url()
    return {
        "status": "ok",
        "api_key_configured": bool(key),
        "database_configured": bool(db),
        "model": get_model(),
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
      safety_report  — final LLM safety assessment (per model)
      model_comparison — comparison across models
      done           — analysis complete
      error          — something went wrong
    """

    async def event_generator():
        try:
            api_key = get_api_key()
            if not api_key:
                yield {
                    "event": "message",
                    "data": json.dumps({
                        "type": "error",
                        "message": "GROQ_API_KEY not configured on server. Check .env file.",
                    }),
                }
                return

            model = get_model()

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
                safety_categories = parsed_extraction.get(
                    "safety_categories", ["general_safety"]
                )
                steps_list = []

                if isinstance(parsed_extraction, dict):
                    steps_list = parsed_extraction.get("steps", [])
                elif isinstance(parsed_extraction, list):
                    steps_list = parsed_extraction

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
                    """Run safety analysis for a single model."""
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
                        label = next(
                            (m["label"] for m in ANALYSIS_MODELS if m["key"] == key),
                            key,
                        )
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
                        label = next(
                            (m["label"] for m in ANALYSIS_MODELS if m["key"] == key),
                            key,
                        )
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
async def get_rules_by_document_endpoint():
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
    """Accept one or more PDF uploads, run extraction pipeline, return results."""

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
    """Run structural evaluation on an existing extraction run."""
    import psycopg2.extras as pge

    try:
        conn = get_db_connection()
        try:
            with conn.cursor(cursor_factory=pge.RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, source_documents, json_source_file "
                    "FROM extraction_runs WHERE id = %s",
                    (run_id,),
                )
                run = cur.fetchone()
                if not run:
                    raise HTTPException(
                        status_code=404, detail=f"Run #{run_id} not found"
                    )

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

        extraction_data = {"rules": rules}

        evaluation = await asyncio.to_thread(
            run_structure_evaluation, extraction_data
        )

        await asyncio.to_thread(save_evaluation_results, run_id, evaluation)

        return {"run_id": run_id, "evaluation_results": evaluation}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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

    conn = get_db_connection()
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
    conn = get_db_connection()
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
    conn = get_db_connection()
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
# WebSocket extraction with real-time progress
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

            file_bytes = base64.b64decode(file_b64)
            tmp = tempfile.NamedTemporaryFile(
                delete=False, suffix=".pdf", prefix="extract_"
            )
            tmp.write(file_bytes)
            tmp.close()
            tmp_path = tmp.name

            import queue
            progress_queue: queue.Queue = queue.Queue()

            def progress_callback(step: str, detail: dict):
                progress_queue.put({"step": step, **detail})

            def run_extraction():
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

            future = loop.run_in_executor(_extract_pool, run_extraction)

            while not future.done():
                try:
                    event = progress_queue.get_nowait()
                    await ws.send_json(event)
                except queue.Empty:
                    pass
                await asyncio.sleep(0.1)

            while not progress_queue.empty():
                event = progress_queue.get_nowait()
                await ws.send_json(event)

            result = future.result()
            if result:
                all_results.append(result)

            try:
                os.unlink(tmp_path)
            except OSError:
                pass

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
