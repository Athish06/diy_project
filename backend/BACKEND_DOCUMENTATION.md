# Backend Codebase Documentation

## 1. Folder Structure

Files under `backend/`:

1. `.env`  
Purpose: local runtime configuration (API keys, model name, DB URL, runtime env flags).  
Role: supplies environment variables consumed by `app.py`, `rule_matcher.py`, and `embeddings.py`.

2. `app.py`  
Purpose: FastAPI app bootstrap and middleware/router wiring.  
Role: backend entrypoint; exposes API and WebSocket routes.

3. `embeddings.py`  
Purpose: embedding generation and pgvector similarity search.  
Role: semantic retrieval layer between extracted DIY steps and `safety_rules` DB table.

4. `requirements.txt`  
Purpose: Python package dependency list.  
Role: environment reproducibility for backend runtime.

5. `rule_matcher.py`  
Purpose: main API layer plus extraction orchestration, DB access, evaluation logic, safety analysis orchestration, caching, and websocket extraction.  
Role: core backend service module.

6. `steps_extract.py`  
Purpose: Groq streaming client for transcript-to-structured-DIY extraction.  
Role: LLM extraction adapter used by analysis endpoint.

7. `transcript.py`  
Purpose: YouTube transcript and metadata fetching/formatting.  
Role: ingestion layer for YouTube source data.


## 2. File Analysis

### File: `backend/app.py`  -> where the server runs
What it does: 
initializes FastAPI app, CORS,startup checks, mounts routers.  
Why it exists: decouples app bootstrap from route business logic.  
Where used: process entrypoint when running backend (`uvicorn` call at file bottom).

Functions:

Function: `lifespan(app: FastAPI)`  
Input: `app` (FastAPI instance).  
Output: async context manager lifecycle events (no explicit return payload).  
Logic:
1. Reads `GROQ_API_KEY`, database URL, model via imported helper functions from `rule_matcher.py`.
2. Prints warnings if API key or DB URL are missing.
3. Prints model and configuration status.
4. Yields control to run app lifecycle.
Calls: `get_api_key`, `get_database_url`, `get_model` from `backend/rule_matcher.py`.  
Side effects: console logging.

Module-level effects:
1. `load_dotenv()` loads env vars from `.env`.
2. Creates `app = FastAPI(...)` with lifespan.
3. Adds permissive CORS (`allow_origins=["*"]`, all methods/headers, credentials true).
4. Includes `router` and `ws_router` from `backend/rule_matcher.py`.
5. In `__main__`, starts uvicorn (`host=0.0.0.0`, `port=8000`, `reload=True`).

### File: `backend/transcript.py`
What it does: retrieves transcript snippets and metadata from YouTube, formats transcript with time-chunk labels.  
Why it exists: isolate external YouTube access and transcript preprocessing.  
Where used: `analyze_diy` endpoint in `backend/rule_matcher.py`.

Classes:

Class: `TranscriptResult`  
Field: `text: str`.

Class: `VideoMetadata`  
Fields: `title: str`, `author: str`.

Functions:

Function: `_format_timestamp(seconds: float) -> str`  
Input: seconds float.  
Output: timestamp string (`m:ss` or `h:mm:ss`).  
Logic: integer conversion and component formatting.  
Dependencies: none.  
Side effects: none.

Function: `_format_transcript_with_timestamps(snippets: list[dict]) -> str`  
Input: transcript snippets with `start` and `text`.  
Output: newline-separated transcript chunks prefixed with `[timestamp]`.  
Logic:
1. Returns empty string if no snippets.
2. Groups snippets into 30-second windows (`CHUNK_INTERVAL_SECONDS`).
3. Joins cleaned texts per chunk.
4. Builds formatted lines with start timestamp.
Dependencies: `_format_timestamp`.  
Side effects: none.

Function: `_fetch_transcript_sync(video_id: str) -> str`  
Input: YouTube video ID.  
Output: formatted transcript string.  
Logic:
1. Instantiates `YouTubeTranscriptApi`.
2. Tries English transcript first, then any language fallback.
3. Handles transcript-disabled/unavailable cases with explicit exceptions.
4. Extracts `start` + `text` for non-empty snippets.
5. Returns chunked formatted transcript.
External dependencies: `youtube-transcript-api`.  
Side effects: network call to YouTube transcript backend.

Function: `fetch_transcript(client: httpx.AsyncClient, video_id: str) -> TranscriptResult`  
Input: async HTTP client (unused), video ID.  
Output: `TranscriptResult`.  
Logic: runs blocking fetch in worker thread using `asyncio.to_thread`, wraps result in dataclass.  
Dependencies: `_fetch_transcript_sync`.  
Side effects: threaded execution, external network indirectly.

Function: `fetch_metadata(client: httpx.AsyncClient, video_id: str) -> VideoMetadata`  
Input: async HTTP client, video ID.  
Output: `VideoMetadata`.  
Logic:
1. Builds YouTube oEmbed URL.
2. GETs metadata with timeout.
3. Validates 2xx status.
4. Parses JSON title and author name.
Dependencies: `httpx`.  
Side effects: network call to YouTube oEmbed endpoint.

### File: `backend/steps_extract.py`
What it does: streams LLM output for DIY extraction from transcript via Groq SSE-like response stream.  
Why it exists: isolates transcript-to-structured-JSON LLM prompt and streaming parser.  
Where used: `analyze_diy` in `backend/rule_matcher.py`.

Functions:

Function: `_clean_json_response(text: str) -> str`  
Input: raw LLM text.  
Output: JSON substring string.  
Logic:
1. Trims whitespace.
2. Removes markdown code fences if present.
3. Extracts first JSON object or array bounds.
4. Returns cleaned text.
Dependencies: none.  
Side effects: none.

Function: `extract_steps_stream(client, api_key, model, transcript) -> AsyncGenerator[dict, None]`  
Input: `httpx.AsyncClient`, Groq API key, model ID, transcript text.  
Output: async stream of dict events:
- `{"type": "steps_delta", "text": "..."}`
- `{"type": "steps_complete", "steps_json": "..."}`
Logic:
1. Builds user prompt from transcript + static system prompt.
2. Sends streaming POST to Groq chat completions (`stream=True`).
3. Handles HTTP errors (401/429/503/custom).
4. Iterates response lines; parses `data: ...` chunks.
5. Extracts delta tokens and yields `steps_delta`.
6. After completion, validates non-empty output.
7. Cleans and JSON-parses response.
8. Re-serializes as JSON string and yields `steps_complete`.
External dependencies: Groq HTTP API via `httpx`, `json`.  
Side effects: outbound network call.

### File: `backend/embeddings.py`
What it does: creates sentence embeddings and performs pgvector similarity search for matching safety rules.  
Why it exists: retrieval abstraction around embedding model + DB vector search.  
Where used: `analyze_diy` in `backend/rule_matcher.py`.

Class: `EmbeddingService`  
Role: singleton service for embedding + retrieval.

Methods:

Function: `get_instance(cls) -> EmbeddingService`  
Input: class reference.  
Output: singleton instance.  
Logic: lazily instantiates `EmbeddingService` once and returns cached instance.  
Dependencies: class variable `_instance`.  
Side effects: initial model load on first call.

Function: `__init__(self, model_name="all-MiniLM-L6-v2")`  
Input: model name string.  
Output: instance init.  
Logic: imports and loads `SentenceTransformer(model_name)`, stores model handle.  
External dependencies: `sentence_transformers`.  
Side effects: heavy model load in memory.

Function: `embed_texts(self, texts: list[str]) -> list[list[float]]`  
Input: list of text strings.  
Output: list of embedding vectors.  
Logic: batch encodes texts using model, converts vectors to Python lists.  
Side effects: CPU/GPU inference.

Function: `embed_text(self, text: str) -> list[float]`  
Input: single text.  
Output: single embedding vector.  
Logic: calls `embed_texts([text])` and returns first item.  
Side effects: model inference.

Function: `embed_steps(self, steps: list[dict]) -> list[list[float]]`  
Input: list of extracted step dicts.  
Output: step embeddings.  
Logic:
1. For each step, concatenates `action_summary`, `step_text`, optional `transcript_excerpt`.
2. Skips empty list fast.
3. Batch embeds concatenated texts.
Dependencies: `embed_texts`.  
Side effects: model inference.

Function: `_get_db_url(self) -> str`  
Input: none.  
Output: DB URL string.  
Logic:
1. Reads `DATABASE_URL` or `SUPABASE_URL`.
2. Raises if missing.
3. Rewrites port `5432` to `6543` for Supabase session pooler.
Dependencies: `os`, `re`.  
Side effects: none.

Function: `find_matching_rules(self, step_embedding, categories=None, top_k=10, threshold=0.30) -> list[dict]`  
Input: embedding vector, optional category filters, top-k, similarity threshold.  
Output: filtered matching rule rows with `similarity`.  
Logic:
1. Opens DB connection.
2. Converts embedding to pgvector literal string.
3. Builds SQL query against `safety_rules`, optional category overlap filter.
4. Orders by vector distance `<=>`, limits `top_k`.
5. Computes similarity as `1 - distance`.
6. Keeps rows above threshold and normalizes IDs.
7. Returns filtered list.
External dependencies: `psycopg2`, pgvector operator in DB.  
Side effects: DB connection + query.

Function: `find_rules_for_step(self, step, step_embedding, safety_categories=None, top_k=10) -> list[dict]`  
Input: step dict, step embedding, optional video safety categories, top-k.  
Output: candidate rule list.  
Logic:
1. Category-filtered retrieval first.
2. If fewer than 3 results, fallback to unfiltered retrieval.
3. Deduplicates by `rule_id`.
4. Returns merged candidates.
Dependencies: `find_matching_rules`.  
Side effects: up to two DB queries.

### File: `backend/rule_matcher.py`
What it does: main orchestration layer for API routes, DB fetch/persist, extraction subprocess, evaluation, safety LLM analysis, caching, websocket progress.  
Why it exists: consolidates backend business logic and HTTP/WebSocket interfaces.  
Where used: imported by `backend/app.py` to mount routers and config helpers.

Classes:

Class: `_CacheEntry`  
Function: `__init__(self, data: str)`  
Input: serialized result JSON string.  
Output: cache entry object with monotonic timestamp.  
Side effects: none.

Class: `AnalysisCache`  
Function: `__init__(self)` initializes in-memory dict.  
Function: `get(self, video_id)` returns cached payload if present and not expired; removes expired entry.  
Function: `set(self, video_id, data)` stores payload then triggers cleanup.  
Function: `_cleanup(self)` removes expired entries and oldest entries over max size.  
Dependencies: `time.monotonic`.  
Side effects: in-memory mutation only.

Config helpers:

Function: `get_api_key() -> str`  
Input: none.  
Output: `GROQ_API_KEY` or empty string.  
Side effects: none.

Function: `get_model() -> str`  
Input: none.  
Output: `MODEL` env or default `qwen/qwen3-32b`.  
Side effects: none.

Function: `get_database_url() -> str`  
Input: none.  
Output: `DATABASE_URL` or `SUPABASE_URL`.  
Side effects: none.

DB connection/query functions:

Function: `get_db_connection()`  
Input: none.  
Output: active psycopg2 connection.  
Logic: reads DB env vars, raises if missing.  
Side effects: opens DB connection.

Function: `fetch_rules_from_db(category, severity, document, search, page, per_page) -> dict`  
Input: optional filters + pagination.  
Output: paginated rules payload with total count.  
Logic:
1. Builds dynamic WHERE conditions.
2. If `document` provided, maps filename to `extraction_runs.id` first and prefers `run_id` filter.
3. Executes count query.
4. Executes paginated select with join to `extraction_runs`.
5. Serializes datetime and `rule_id` string forms.
Side effects: DB reads.

Function: `fetch_filter_options_from_db() -> dict`  
Input: none.  
Output: distinct categories, severities, documents.  
Logic: three DB queries for filter dimensions.  
Side effects: DB reads.

Function: `fetch_rules_by_document() -> dict`  
Input: none.  
Output: per-document aggregates (`rule_count`, categories, avg severity, last_updated).  
Side effects: DB read and aggregation.

Function: `fetch_extraction_runs() -> dict`  
Input: none.  
Output: extraction runs list sorted descending by id.  
Logic: parses timestamps and JSON string if needed.  
Side effects: DB reads.

Function: `fetch_rules_by_run(run_id, page, per_page) -> dict`  
Input: run id and pagination.  
Output: run-scoped paginated rules + total.  
Side effects: DB reads.


## Evaluation functions:

Function: `save_evaluation_results(run_id, evaluation, file_name="unknown") -> None`  
Input: run ID, evaluation dict, source file name.  
Output: none.  
Logic:
1. Derives pass counts and percentages from `evaluation.check_totals`.
2. Inserts row into `evaluation_results`.
3. Updates `extraction_runs.evaluation_results` JSON for compatibility.
Side effects: DB writes.

Function: `_compute_correctness_metrics(rules, include_rule_ids=None, cosine_threshold=0.7) -> tuple[float, int]`  
Input: list of rules, optional rule-id filter, cosine threshold.  
Output: average cosine similarity percent, count above threshold.  
Logic:
1. Optionally filters rules.
2. Builds `(original_text, actionable_rule)` pairs.
3. Loads sentence transformer model.
4. Embeds both texts and computes cosine per pair.
5. Returns aggregated score and pass count.
Side effects: model load/inference; no DB/network.

Function: `run_brutal_evaluation(pdf_path, extraction_data) -> dict`  
Input: source PDF path and extraction data with rules.  
Output: detailed evaluation summary (check totals, accuracy metrics, failed rules, hallucination rate, correctness score, IDs).  
Logic:
1. Opens PDF via PyMuPDF and collects lowercase page text map.
2. For each rule, runs checks:
- text presence across document
- page accuracy (+/-1 page tolerance)
- heading accuracy
- category validity against allowed set
- severity consistency vs hazard keywords and suggested severity
3. Computes aggregate metrics.
4. Computes cosine correctness on text-presence-passed rules.
5. Returns metrics payload.
Side effects: file I/O, CPU-heavy text matching + embedding inference.

Function: `run_structure_evaluation(extraction_data) -> dict`  
Input: extraction rules.  
Output: structure-only quality metrics (no PDF checks).  
Logic: validates actionable text presence, original text presence, category validity, severity existence.  
Side effects: none external.

Metric helpers:

Function: `_coerce_float(value, default=0.0) -> float`  
Function: `_tokenize(text) -> set[str]`  
Function: `_average_ranks(values) -> list[float]`  
Function: `_pearson_corr(xs, ys) -> float | None`  
Function: `_spearman_corr(xs, ys) -> float | None`  
Function: `_binary_metrics(tp, tn, fp, fn) -> tuple[float, float, float, float]`  
Role: local math/text utilities for evaluation calculations.  
Note: in the read code, these helpers are defined but not called by route handlers shown.

## Extraction orchestration:

Function: `_safety_extraction_dir() -> Path`  
Output: path to `rule_extraction/` sibling folder.

Function: `_find_python() -> str`  
Output: executable command candidate (`python`, `python3`, or `py`) based on OS/path availability.

Function: `_strip_embeddings(data: dict) -> dict`  
Output: extraction data with rule-level `embedding` removed.

Function: `_get_supabase_project_ref() -> str | None`  
Output: Supabase project ref parsed from connection URL or env override.

Function: `_upload_to_supabase_storage(file_path, original_filename) -> str | None`  
Input: local PDF path + original filename.  
Output: public storage URL or `None`.  
Logic:
1. Derives project ref and API key from env.
2. POSTs file bytes to Supabase Storage object API with upsert.
3. Builds public URL on success.
Side effects: reads file, outbound HTTP request, prints warnings.

Function: `_insert_run_and_rules(extraction_data, original_filename, file_url) -> int`  
Input: extracted rules payload, filename, optional public file URL.  
Output: inserted extraction run ID.  
Logic:
1. Inserts row into `extraction_runs`.
2. Iterates rules, serializes embeddings if present.
3. Inserts into `safety_rules` (`ON CONFLICT (rule_id) DO NOTHING`).
4. Commits and returns run ID.
Side effects: DB writes.

Function: `_prepare_env() -> dict`  
Output: subprocess env dict with UTF-8, runtime flags, DB/API key propagation.

Function: `extract_rules_v2(file_path, original_filename) -> dict`  
Input: PDF file path + original filename.  
Output: dict with extraction payload, `run_id`, and evaluation results.  
Logic:
1. Validates file and extension.
2. Runs `rule_extraction/extract_rules.py` via `subprocess.run`.
3. Loads output JSON file.
4. Uploads source PDF to Supabase storage.
5. Inserts run + rules into DB.
6. Executes brutal evaluation and saves evaluation rows.
7. Strips embeddings from response.
Side effects: subprocess execution, temp file I/O, network upload, DB writes.

Function: `extract_rules_with_progress(file_path, original_filename, progress_callback) -> dict`  
Input: PDF path, filename, callback.  
Output: same shape as `extract_rules_v2`.  
Logic:
1. Spawns extraction subprocess with streamed stdout.
2. Parses stdout regex patterns into progress events (`ingestion`, `llm_extraction`, `embedding`, `deduplication`, `complete`).
3. Reads output JSON.
4. Uploads file, inserts DB rows, evaluates, saves results.
Side effects: subprocess, callback invocations, temp file I/O, network upload, DB writes.

## Safety LLM analysis:

Function: `_build_safety_user_message(steps, rules_per_step, safety_categories, video_title="") -> str`  
Input: extracted steps, matched rules map, categories, optional title.  
Output: long textual prompt containing step-by-step context and matched rules.  
Side effects: none.

Function: `_clean_json_response(text: str) -> str`  
Output: cleaned JSON object substring from model output.

Function: `analyze_safety(steps, rules_per_step, safety_categories, video_title="", api_key=None, model="qwen/qwen3-32b") -> dict`  
Input: structured steps + per-step matched rules + model settings.  
Output: normalized safety report dict (verdict, risk score, per-step analysis, etc.).  
Logic:
1. Resolves API key.
2. Builds user message and model request body.
3. Sends non-streaming Groq chat completion request.
4. Handles API error statuses.
5. Parses JSON content; validates dict.
6. Backfills expected default keys.
Side effects: outbound Groq API call, logging.

Comparison helper:

Function: `_build_model_comparison(reports: dict[str, dict]) -> dict`  
Input: per-model report dict.  
Output: comparison table structure with agreement flags across several aspects.  
Logic: for available models, computes aspect values and marks agreement when values match.

Routes/endpoints:

Function: `health()` mapped to `GET /api/health`  
Returns service status booleans and model.

Function: `analyze_diy(video_id)` mapped to `GET /api/analyze` (SSE)  
Core streamed pipeline:
1. Validate API key.
2. Serve cached result when available.
3. Fetch transcript and metadata in parallel.
4. Stream transcript extraction deltas from `extract_steps_stream`.
5. Parse extraction, branch if non-DIY.
6. Generate embeddings with `EmbeddingService`.
7. Find matching rules per step via pgvector.
8. Run multi-model safety assessments in parallel (`ANALYSIS_MODELS`).
9. Emit model reports and comparison.
10. Cache assembled result.
11. Emit done/error events.

Local nested functions in this route:
- `event_generator()`: SSE producer.
- `_run_model(m)`: single-model safety analysis task wrapper.

Function: `get_rules(...)` mapped to `GET /api/rules`  
Returns either run-filtered rules (`fetch_rules_by_run`) or general filtered rules (`fetch_rules_from_db`).

Function: `get_filter_options()` mapped to `GET /api/filter_options`  
Returns category/severity/document options.

Function: `get_rules_by_document_endpoint()` mapped to `GET /api/rules_by_document`  
Returns grouped document stats.

Function: `get_extraction_runs()` mapped to `GET /api/extraction_runs`  
Returns extraction run history.

Function: `get_evaluation_results(run_id=None)` mapped to `GET /api/evaluation_results`  
Returns evaluation rows, optionally filtered by run.

Function: `extract_rules_endpoint(files)` mapped to `POST /api/extract_rules`  
Handles multipart PDF uploads, processes each file through `extract_rules_v2`, collects successes/errors.

Function: `trigger_evaluation(run_id)` mapped to `POST /api/run_evaluation/{run_id}`  
Logic:
1. Loads run info + rules.
2. Downloads source PDF via `file_url`.
3. Re-runs brutal evaluation.
4. Deletes rules failing text-presence check.
5. Updates run rule count.
6. Persists evaluation.
Side effects: network download, temp file, DB deletes/updates/inserts.

Function: `save_scan(request)` mapped to `POST /api/scans`  
Stores completed scan metadata + JSON outputs into `completed_scans`.

Function: `list_scans()` mapped to `GET /api/scans`  
Returns last 200 scan summaries.

Function: `get_scan(scan_id)` mapped to `GET /api/scans/{scan_id}`  
Returns one stored scan record with `output_json`.

Function: `ws_extract(ws)` mapped to `WS /ws/extract`  
Logic:
1. Accept websocket.
2. Receives base64-encoded PDF list.
3. Writes temp files.
4. Runs `extract_rules_with_progress` in thread executor.
5. Polls queue and emits progress events.
6. Sends final done payload.
Local nested functions:
- `progress_callback(step, detail)`.
- `run_extraction()`.

### File: `backend/requirements.txt`
What it does: pinned/minimum backend dependencies.  
Why it exists: reproducible installs for FastAPI, LLM calls, transcript fetching, embeddings, DB, PDF/OCR.  
Where used: environment setup.  
Functions: none.

### File: `backend/.env`
What it does: stores local env values (`GROQ_API_KEY`, `MODEL`, `SUPABASE_URL`, and runtime flags).  
Why it exists: runtime configuration without hardcoding in Python modules.  
Where used: loaded by `backend/app.py`; read via `os.getenv` across modules.  
Functions: none.  
Side effect on startup: environment variables are injected into process by `load_dotenv()`.

## 3. Inter-file Communication

Primary execution graph for analysis:

`backend/app.py`  
-> imports routers/config helpers from `backend/rule_matcher.py`  
-> mounts API + WS routes

`backend/rule_matcher.py` (`GET /api/analyze`)  
-> `backend/transcript.py::fetch_transcript`  
-> `backend/transcript.py::fetch_metadata`  
-> `backend/steps_extract.py::extract_steps_stream`  
-> `backend/embeddings.py::EmbeddingService.get_instance/embed_steps/find_rules_for_step`  
-> internal `analyze_safety` (Groq API)  

DB communication path:

`backend/rule_matcher.py`  
-> psycopg2 connections via `get_db_connection`  
-> tables queried/updated include `safety_rules`, `extraction_runs`, `evaluation_results`, `completed_scans`, and migration-managed eval tables.

Rule extraction path:

`backend/rule_matcher.py::extract_rules_v2` or `extract_rules_with_progress`  
-> subprocess runs `rule_extraction/extract_rules.py`  
-> parses generated JSON output  
-> optional upload to Supabase Storage HTTP API  
-> persists run/rules/evaluation in DB

WebSocket extraction path:

Client WS `/ws/extract`  
-> `backend/rule_matcher.py::ws_extract`  
-> thread pool executes `extract_rules_with_progress`  
-> callback queue streams progress messages back over WS.

## 4. API Flow

Base prefix from router: `/api` for HTTP routes.

Endpoint: `GET /api/health` 

Flow:
1. Read API key, DB URL, model.
2. Return config status flags and model string.
Calls: `get_api_key`, `get_database_url`, `get_model`.


Endpoint: `GET /api/analyze?video_id=...`  


Flow:
1. Check server Groq key.
2. Try cache hit for `video_id`.
3. Fetch transcript and metadata concurrently.
5. Parse extraction JSON and DIY flag.
6. If non-DIY or no steps, send `not_diy` and stop.
7. Embed extracted steps.
8. Retrieve matched safety rules per step from pgvector.
9. Run safety assessment across configured models in parallel.
10. Build comparison payload.
11. Cache all outputs.
12. Stream completion.
Calls: `fetch_transcript`, `fetch_metadata`, `extract_steps_stream`, `EmbeddingService` methods, `analyze_safety`, `_build_model_comparison`.

Endpoint: `GET /api/rules`  
Flow:
1. Parse query filters.
2. If `run_id` provided, query run-specific rules.
3. Else query filtered/global rules.
Calls: `fetch_rules_by_run` or `fetch_rules_from_db`.

Endpoint: `GET /api/filter_options`  
Flow: fetch distinct categories/severities/documents.  
Calls: `fetch_filter_options_from_db`.

Endpoint: `GET /api/rules_by_document`  
Flow: DB aggregation grouped by document.  
Calls: `fetch_rules_by_document`.

Endpoint: `GET /api/extraction_runs`  
Flow: return extraction run rows.  
Calls: `fetch_extraction_runs`.

Endpoint: `GET /api/evaluation_results`  
Flow:
2. Query `evaluation_results`.
3. Serialize timestamps/JSON strings.
Calls: direct DB query in handler.

Endpoint: `POST /api/extract_rules` (multipart files)  
Flow:
1. Validate input files.
2. For each PDF, write temp file.
3. Run `extract_rules_v2`.
4. Collect per-file success/error.
Calls: `extract_rules_v2` -> subprocess + DB + storage + evaluation.

Endpoint: `POST /api/run_evaluation/{run_id}`  
Flow:
1. Load run metadata and rules from DB.
2. Download source PDF via `file_url`.
3. Run brutal evaluation.
4. Delete text-presence failed rules.
5. Update run count and save evaluation.
Calls: `run_brutal_evaluation`, `save_evaluation_results`, direct DB ops.

Endpoint: `POST /api/scans`  
Flow:
1. Parse JSON body.
2. Validate required fields.
3. Insert scan row with JSON payloads.
Calls: direct DB insert.

Endpoint: `GET /api/scans`  
Flow: query and return recent scan summaries.  
Calls: direct DB read.

Endpoint: `GET /api/scans/{scan_id}`  
Flow: query one scan by id and return full output JSON.  
Calls: direct DB read.

Endpoint: `WS /ws/extract`  
Flow:
1. Receive base64 PDF payload(s).
2. Save each as temp PDF.
3. Run extraction in executor thread.
4. Emit incremental progress events.
5. Emit final summary.
Calls: `extract_rules_with_progress`.

## 5. Data Flow

### End-to-end flow: YouTube analysis (`GET /api/analyze`)

1. Input:
- `video_id` query parameter.

2. Ingestion:
- transcript text from YouTube transcript API (`transcript.py`).
- metadata from YouTube oEmbed (`transcript.py`).

3. Transformation:
- transcript passed to Groq extraction prompt (`steps_extract.py`).
- streaming delta events emitted to SSE client.
- final JSON extraction parsed in `rule_matcher.py`.
- checks `is_diy`, `steps`, `safety_categories`.

4. Retrieval:
- step text fields combined and embedded (`embeddings.py`).
- per-step pgvector similarity search against `safety_rules`.
- category-filtered retrieval then fallback unfiltered merge.

5. Safety reasoning:
- build model prompt with steps + matched rules + categories.
- run one request per configured model in parallel (`analyze_safety`).
- parse strict JSON response and normalize expected fields.

6. Aggregation:
- compare model outputs (`_build_model_comparison`).
- cache final payload in process memory by `video_id`.

7. Output:
- SSE stream includes status, metadata, steps, per-model reports, comparison, and done/error events.

### End-to-end flow: Rule extraction from PDFs (`POST /api/extract_rules` or `WS /ws/extract`)

1. Input:
- one or more PDF files (multipart or base64).

2. Extraction pipeline:
- call external script `rule_extraction/extract_rules.py` via subprocess.
- read generated JSON file output.

3. Persistence:
- optional upload source PDF to Supabase Storage for public URL.
- insert extraction run row.
- insert rules into `safety_rules` (dedupe by rule_id conflict ignore).

4. Evaluation:
- run brutal PDF-grounded checks.
- save evaluation rows.
- strip embeddings from response payload.

5. Output:
- HTTP returns batch results/errors.
- WS streams progress milestones + final summary.

## 6. Dependencies

Module dependency graph (backend-only):

1. `backend/app.py` depends on:
- `backend/rule_matcher.py` (`router`, `ws_router`, config helper functions).
- `python-dotenv`, `fastapi`, `fastapi.middleware.cors`.

Reason: app setup, route registration, startup diagnostics.

2. `backend/rule_matcher.py` depends on:
- `backend/transcript.py` for YouTube transcript/metadata.
- `backend/steps_extract.py` for streaming extraction.
- `backend/embeddings.py` for embeddings + vector retrieval.
- `httpx` for Groq and PDF download calls.
- `psycopg2` for DB reads/writes.
- `sse-starlette` for SSE response.
- stdlib subprocess/tempfile/threading utilities.
- external `rule_extraction/extract_rules.py` subprocess.

Reason: orchestration of all major backend use cases.

3. `backend/steps_extract.py` depends on:
- `httpx`, `json`.
- Groq chat completions API endpoint.

Reason: LLM streaming extraction client.

4. `backend/transcript.py` depends on:
- `youtube-transcript-api`.
- `httpx` for oEmbed metadata.

Reason: YouTube data ingestion.

5. `backend/embeddings.py` depends on:
- `sentence-transformers` (model inference).
- `psycopg2` + pgvector-enabled Postgres.

Reason: retrieval over rule embedding vectors.

6. `backend/.env` and env variables are runtime dependencies for:
- API keys.
- model selection.
- DB connectivity.
- subprocess behavior flags.

## 7. Core Components

1. Transcript extraction  
Implemented in `backend/transcript.py`.  
Core functions: `_fetch_transcript_sync`, `fetch_transcript`, `fetch_metadata`.  
Behavior: fetches transcript snippets, chunks by time intervals, and fetches video metadata via oEmbed.

2. Step extraction  
Implemented in `backend/steps_extract.py` and consumed by `backend/rule_matcher.py`.  
Core function: `extract_steps_stream`.  
Behavior: sends transcript to Groq with strict JSON prompt, streams partial deltas, emits final extraction JSON.

3. Embedding generation  
Implemented in `backend/embeddings.py`.  
Core methods: `EmbeddingService.embed_steps`, `embed_texts`.  
Behavior: converts structured step text into 384-d vectors using `all-MiniLM-L6-v2`.

4. Rule matching  
Implemented in `backend/embeddings.py`.  
Core methods: `find_matching_rules`, `find_rules_for_step`.  
Behavior: category-aware pgvector cosine search against `safety_rules`, with fallback search and deduplication.

5. Safety analysis  
Implemented in `backend/rule_matcher.py`.  
Core function: `analyze_safety`; orchestration in `analyze_diy`.  
Behavior: sends matched-step context to Groq, parses JSON safety report, runs multiple model variants in parallel, compares outputs.




