"""
FastAPI routes — new pipeline:

1. /api/analyze (SSE)  — transcript → LLM extraction → is_diy check →
                          embed steps → pgvector match → LLM safety assessment
2. /api/rules (GET)    — query safety_rules DB with filters
3. /api/filter_options — get distinct filter values
4. /api/extract_rules  — upload PDF, run extraction pipeline

API key is read from .env at all times — no user-facing key management.
"""

import asyncio
import json
import os
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from sse_starlette.sse import EventSourceResponse

from cache import AnalysisCache
from transcript import fetch_transcript, fetch_metadata
from groq_client import extract_steps_stream
from embeddings_service import EmbeddingService
from safety_analyzer import analyze_safety
from safety import (
    extract_rules_from_pdf,
    fetch_rules_from_db,
    fetch_filter_options_from_db,
)

router = APIRouter(prefix="/api")

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
_cache = AnalysisCache()

MAX_TRANSCRIPT_LENGTH = 100_000


def _get_api_key() -> str:
    return os.getenv("GROQ_API_KEY", "")


def _get_model() -> str:
    return os.getenv("MODEL", "qwen/qwen3-32b")


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
                if "report_json" in cached_data:
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "safety_report",
                            "report_json": cached_data["report_json"],
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

                # ------ 6. Final LLM safety assessment ------
                report_json = "{}"
                try:
                    report = await analyze_safety(
                        steps=steps_list,
                        rules_per_step=rules_per_step,
                        safety_categories=safety_categories,
                        video_title=video_title,
                        api_key=api_key,
                        model=model,
                    )
                    report_json = json.dumps(report)
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "safety_report",
                            "report_json": report_json,
                        }),
                    }
                except Exception as e:
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "status",
                            "message": f"Safety assessment error: {e}",
                        }),
                    }

                # ------ 7. Cache result ------
                cache_data = json.dumps({
                    "is_diy": True,
                    "steps_json": steps_json,
                    "safety_categories": safety_categories,
                    "report_json": report_json,
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
# Safety rules endpoints (unchanged — they use the subprocess bridge)
# ---------------------------------------------------------------------------

@router.get("/rules")
async def get_rules(
    category: Optional[str] = Query(None),
    severity: Optional[int] = Query(None),
    document: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1),
    per_page: int = Query(50),
):
    try:
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


@router.post("/extract_rules")
async def extract_rules(file: UploadFile = File(...)):
    """Accept a PDF upload, save to temp, run extraction pipeline, return results."""
    import tempfile
    from pathlib import Path

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    tmp = Path(tempfile.gettempdir()) / file.filename
    content = await file.read()
    tmp.write_bytes(content)

    try:
        result = await asyncio.to_thread(extract_rules_from_pdf, str(tmp))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
