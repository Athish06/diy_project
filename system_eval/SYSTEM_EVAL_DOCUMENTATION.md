# System Eval Documentation

## 1. Folder Structure

Files under `system_eval/`:

1. `system_eval/run_batch_eval.py`  
Purpose: URL pool ingestion, batch invocation of backend analysis, per-video metric computation, and persistence of system-level evaluation metrics.  
Role: batch evaluator and orchestrator for end-to-end system assessment.

2. `system_eval/youtube_urls/.gitkeep`  
Purpose: keeps URL pool folder in version control even when empty.  
Role: placeholder only; real URL source files (PDF/CSV/XLSX/TXT) are expected to be dropped into this folder at runtime.

## 2. File Analysis

### File: `system_eval/run_batch_eval.py`
What it does: builds/maintains a YouTube URL pool in DB, runs backend `/api/analyze` and `/api/scans` for selected URL ranges, computes label and step-level metrics, and stores batch + per-video results in DB tables.  
Why it exists: provides repeatable system evaluation pipeline over curated YouTube samples.  
Where used: standalone CLI execution in local/CI evaluation runs.

Data classes:

Class: `VideoEvalResult`  
Purpose: typed in-memory container for per-video computed metrics and labels.

Class: `PoolEntry`  
Purpose: typed container for URL-pool records (URL/video ID/title/categories/ground truth).

Functions:

Function: `get_db_connection()`  
Input: none.  
Output: psycopg2 connection.  
Logic:
1. Reads `DATABASE_URL` or `SUPABASE_URL`.
2. URL-encodes raw password component if needed.
3. Appends `sslmode=require` for Supabase URLs if absent.
4. Connects with timeout.  
Side effects: opens DB connection.

Function: `ensure_system_eval_schema()`  
Input: none.  
Output: none.  
Logic: executes migrations creating/updating `youtube_urls`, `system_eval`, and `system_eval_video_results` tables/indexes.  
Side effects: DB DDL schema mutation.

Function: `verify_supabase_state()`  
Input: none.  
Output: summary dict with table counts and latest eval row.  
Side effects: DB reads.

Function: `extract_video_id_from_url(value)`  
Input: URL or possible raw video id string.  
Output: normalized 11-char video id or `None`.  
Logic: handles `youtu.be`, `youtube.com/watch?v=...`, and shorts URL forms.

Function: `normalize_youtube_url(value)`  
Input: URL or id-like value.  
Output: canonical `https://www.youtube.com/watch?v=<id>` or `None`.

Function: `_normalize_header_key(value)`  
Input: header text.  
Output: alphanumeric lowercase normalized key for loose CSV/XLSX header matching.

Function: `_sanitize_db_text(value)`  
Input: optional text.  
Output: cleaned text or `None`.  
Logic: removes null bytes, strips invalid utf-8 and whitespace.

Function: `_normalize_ground_truth_label(value)`  
Input: raw label string.  
Output: normalized label in `{SAFE, UNSAFE, PSUA}` or `None`.

Function: `_ground_truth_to_binary(label)`  
Input: normalized label.  
Output: binary unsafe mapping (`SAFE=0`, `UNSAFE/PSUA=1`) or `None`.

Function: `_extract_url_and_label_pairs_from_text(text)`  
Input: raw text.  
Output: list of `(url, label)` tuples.  
Logic:
1. Tries URL+label and label+URL regex patterns.
2. Falls back to URL-only extraction when no pairs found.

Function: `extract_urls_from_text_blob(text)`  
Input: raw text blob.  
Output: deduplicated normalized URL list.  
Logic: regex-extracts full URLs and raw 11-char IDs, normalizes and deduplicates.

Function: `_build_pool_entry(url, title=None, categories=None, label=None)`  
Input: candidate fields from source files.  
Output: `PoolEntry` or `None`.  
Logic: normalizes URL/id and label, sanitizes text fields.

Function: `extract_entries_from_pdf(path)`  
Input: PDF path.  
Output: `PoolEntry` list.  
Logic: extracts page text and explicit links from PDF, parses URL+label pairs, builds entries.

Function: `extract_entries_from_csv(path)`  
Input: CSV path.  
Output: deduplicated `PoolEntry` list.  
Logic: flexible header normalization, supports URL/title/categories/label columns.

Function: `extract_entries_from_excel(path)`  
Input: XLSX/XLS path.  
Output: deduplicated `PoolEntry` list.  
Logic: same mapping style as CSV using `openpyxl`.

Function: `extract_entries_from_file(path)`  
Input: source file path.  
Output: `PoolEntry` list.  
Logic: dispatches by extension (`.pdf`, `.csv`, `.xlsx/.xls`, `.txt`).

Function: `collect_and_upsert_urls(urls_dir)`  
Input: folder path.  
Output: tuple `(added_or_updated_entries, total_pool_size)`.  
Logic:
1. Ensures schema.
2. Reads all non-hidden files in folder and extracts entries.
3. Deduplicates by URL.
4. Upserts into `youtube_urls` with metadata/labels and updates `last_used_at`.
5. Returns processed entries and pool count.  
Side effects: DB upserts.

Function: `get_pool_size()`  
Input: none.  
Output: integer count from `youtube_urls`.

Function: `get_pool_entries()`  
Input: none.  
Output: ordered `PoolEntry` list from DB.

Function: `coerce_float(value, default=0.0)`  
Function: `tokenize(text)`  
Function: `average_ranks(values)`  
Function: `pearson_corr(xs, ys)`  
Function: `spearman_corr(xs, ys)`  
Function: `binary_metrics(tp, tn, fp, fn)`  
Role: generic numeric/text utilities for metrics.

Function: `map_predicted_label(report)`  
Input: model report dict.  
Output: predicted label `{SAFE, UNSAFE, PSUA}` or `None`.  
Logic: first uses verdict mapping, then falls back to risk-score thresholds.

Function: `evaluate_single_output(video_id, video_url, title, channel, scan_id, output_json, ground_truth_label)`  
Input: per-video output payload and optional ground truth label.  
Output: `VideoEvalResult`.  
Logic:
1. Pulls steps and report data from output JSON.
2. Imports `override_severity` from `rule_extraction.extract_rules` for heuristic baseline severity.
3. Computes per-step confusion matrix (LLM risk vs override severity thresholding).
4. Computes ranking quality (MRR) from matched rules.
5. Computes faithfulness from required precaution token overlap evidence.
6. Computes Spearman correlation between LLM risk and override risk.
7. Maps predicted label and binary label confusion values against ground truth.

Function: `stream_analyze(api_base, video_id)`  
Input: backend base URL and video id.  
Output: normalized analysis payload with title/channel/output_json.  
Logic:
1. Opens streaming request to `/api/analyze`.
2. Parses SSE `data:` lines and event payloads.
3. Captures metadata, extraction JSON, model reports, and model comparison.
4. Selects primary report (`qwen` or first available).
5. Returns consolidated output object.  
External dependencies: backend API SSE stream.

Function: `_is_rate_limit_error(exc)`  
Input: exception.  
Output: bool for rate-limit classification by message.

Function: `analyze_with_retries(api_base, video_id, max_attempts=5)`  
Input: API base and video ID.  
Output: result from `stream_analyze`.  
Logic: retries only on detected rate-limit errors using exponential backoff.

Function: `save_scan(api_base, video_id, video_url, title, channel, output_json)`  
Input: scan metadata and output payload.  
Output: inserted scan id or `None` if save fails.  
Logic: POSTs to backend `/api/scans`.

Function: `persist_batch_result(selected_urls, per_video)`  
Input: selected URL list and per-video metrics list.  
Output: persisted batch summary dict.  
Logic:
1. Aggregates label-level confusion totals and metrics.
2. Aggregates MRR, faithfulness, Spearman, precaution counts.
3. Inserts one `system_eval` row with summary and details JSON.
4. Inserts per-video rows into `system_eval_video_results`.
5. Computes cumulative totals over all video-results rows.
6. Updates cumulative columns for current eval row.

Function: `run_batch(api_base, urls_dir, from_index, to_index, pool=None, added_entries=None, total_pool_after=None)`  
Input: API base, URL source folder, selection range, optional preloaded pool data.  
Output: batch summary dict with per-video and failure arrays.  
Logic:
1. Ensures schema and URL pool readiness.
2. Validates index range and minimum batch size (>=5).
3. For each selected URL:
- run analyze with retries
- save scan
- evaluate output metrics
4. Persists aggregate summary.
5. Returns full batch result structure.

Function: `_prompt_index(prompt, min_value, max_value)`  
Input: prompt and limits.  
Output: validated user integer from stdin.

Function: `main()`  
Input: CLI args:
- `--api-base`
- `--urls-dir`
- `--from-index`/`--to-index`
- `--collect-only`
- `--run-only`
- `--verify-db`
- `--out`
Output: process exit code and output JSON file for batch result.  
Logic:
1. Handles mutually exclusive collect-only/run-only.
2. Collects/upserts URL pool unless run-only.
3. Resolves index range (interactive prompt when missing).
4. Runs batch and optional DB verification.
5. Writes summary JSON to `--out` and prints concise completion info.

### File: `system_eval/youtube_urls/.gitkeep`
What it does: placeholder file only.  
Why it exists: preserve directory in repo.  
Where used: not executed.




