# Rule Extraction Documentation

## 1. Folder Structure

Files under `rule_extraction/`:

1. `rule_extraction/embeddings.py`  
Purpose: embedding generation and cosine-similarity deduplication helper for extracted rules.  
Role: post-extraction semantic dedup stage.

2. `rule_extraction/evaluate_rules.py`  
Purpose: quality and hallucination evaluation for extracted rule JSON files.  
Role: offline evaluation utility (PDF-grounded or structure-only).

3. `rule_extraction/extract_rules.py`  
Purpose: main PDF-to-rules pipeline using OCR, Groq extraction, validation, severity normalization, embeddings, dedup, and optional DB migration.  
Role: primary extraction engine used directly and via backend subprocess.

4. `rule_extraction/requirements.txt`  
Purpose: dependency specification for extraction/evaluation environment.  
Role: runtime setup and reproducibility.

## 2. File Analysis

### File: `rule_extraction/embeddings.py`
What it does: loads sentence-transformers model, writes embeddings into rule objects, deduplicates near-duplicate rules by cosine similarity matrix.  
Why it exists: extraction stage needs semantic dedup across LLM-generated rules.  
Where used: imported and instantiated by `rule_extraction/extract_rules.py` (`SafetyRuleExtractionService`).

Class: `EmbeddingProcessor`

Function: `__init__(self, model_name="all-MiniLM-L6-v2", similarity_threshold=0.9)`  
Input: model name and similarity threshold.  
Output: initialized processor.  
Logic:
1. Loads `SentenceTransformer(model_name)`.
2. Stores threshold for duplicate pruning.  
External dependencies: `sentence_transformers`.  
Side effects: model loaded in memory.

Function: `generate_embeddings(self, rules)`  
Input: list of rule dicts.  
Output: same list with `embedding` key per rule.  
Logic:
1. Builds text list from each rule's `actionable_rule`.
2. Encodes all texts in batch.
3. Stores vector as list under `rule["embedding"]`.
4. Returns modified list.  
Side effects: model inference.

Function: `deduplicate_rules(self, rules)`  
Input: rules with embeddings.  
Output: filtered rules list.  
Logic:
1. Validates each rule has `embedding`.
2. Builds embedding matrix and normalizes rows.
3. Computes cosine similarity matrix by matrix multiplication.
4. Iterates upper triangle; if similarity > threshold, marks later rule as duplicate.
5. Returns only kept rules and logs removed duplicates.  
Side effects: CPU-heavy matrix operations and logging.

### File: `rule_extraction/evaluate_rules.py`
What it does: evaluates extraction outputs either against source PDF text (brutal mode) or only against expected schema/fields (structure mode).  
Why it exists: measure extraction quality and detect hallucinated/invalid rules.  
Where used: standalone CLI tool; similar logic is also mirrored in backend route module.

Function: `run_brutal_evaluation(pdf_path, extraction_data)`  
Input: source PDF path and extraction JSON object with `rules`.  
Output: aggregate metrics dict including per-check totals and failed rule snippets.  
Logic:
1. Loads PDF page text via PyMuPDF.
2. For each rule, computes checks:
- text_presence (exact/fuzzy in any page)
- page_accuracy (exact/fuzzy on claimed page ±1)
- category_validity (allowed taxonomy)
- severity_consistency (hazard keywords vs severity bounds)
3. Aggregates pass counts and percentages.
4. Returns summary and truncated failed rules list.  
External dependencies: `pymupdf` or `fitz`.  
Side effects: file I/O and CPU text matching.

Function: `run_structure_evaluation(extraction_data)`  
Input: extraction JSON object.  
Output: structural metrics dict.  
Logic:
1. Validates non-empty actionable rule.
2. Validates non-empty original text.
3. Validates categories against allowed set.
4. Validates `validated_severity` is present.
5. Aggregates totals and failed rule list.  
Side effects: none external.

Function: `main()`  
Input: CLI args (`json_file`, optional `--pdf`).  
Output: prints evaluation JSON to stdout.  
Logic:
1. Parses arguments.
2. Loads extraction JSON file.
3. Runs brutal mode if PDF provided, otherwise structure mode.
4. Prints formatted JSON result and exits on missing files.

### File: `rule_extraction/extract_rules.py`
What it does: end-to-end extraction and migration module.
Why it exists: central pipeline for converting PDF safety documents into normalized, deduplicated rule datasets.
Where used:
1. Direct CLI execution for single or batch PDF extraction.
2. Called via subprocess by `backend/rule_matcher.py` during `/api/extract_rules` and websocket extraction.

Classes and exceptions:

Class: `ExtractionError`  
Role: extraction retry exhaustion signal.

Class: `PDFIngestionError`  
Role: invalid/unreadable PDF signal.

Class: `GroqExtractor`

Function: `__init__(api_key, model_name, max_retries)`  
Input: Groq key, model, retries.  
Output: initialized client wrapper.  
Logic: instantiates Groq SDK client and stores config.

Function: `model_name` property  
Output: configured model name.

Function: `extract_rules(text, document_name, page_number, section_heading)`  
Input: page text and metadata.  
Output: extracted rule dict list for that page.  
Logic:
1. Formats extraction prompt with metadata and page text.
2. Calls Groq chat completion.
3. Parses strict JSON with `_parse_json_response`.
4. Enforces categories with `_enforce_categories`.
5. Adds source metadata to each rule.
6. Retries up to max attempts on parsing/API errors.
7. Raises `ExtractionError` after retries exhausted.  
External dependencies: Groq API via SDK.  
Side effects: network calls and logs.

Class: `RuleValidator`

Function: `__init__()`  
Logic: tries to load spaCy model `en_core_web_sm`; falls back if unavailable.

Function: `validate_and_normalize(rules)`  
Input: rule list.  
Output: validated/normalized list.  
Logic:
1. Drops empty actionable rules.
2. Drops vague rules containing known vague phrases.
3. Splits compound rules with `_split_compound_rule`.
4. Enforces imperative verb normalization via `_normalize_verb`.

Function: `_split_compound_rule(rule)`  
Input: one rule.  
Output: one or more rules.  
Logic:
1. Fallback mode: regex split on coordinated action words.
2. spaCy mode: identifies coordinated verb pairs and conjunction positions.
3. Emits split clauses when safe; else returns original.

Function: `_normalize_verb(rule)`  
Input: one rule.  
Output: normalized rule or `None`.  
Logic:
1. Fallback: drop non-actionable starts using skip lemmas; capitalize first token.
2. spaCy mode: requires starting verb-like token and rewrites action to lemma-based imperative.

Class: `SafetyRuleExtractionService`

Function: `__init__(groq_api_key=None, model_name, embedding_model, similarity_threshold, max_retries)`  
Input: service config.  
Output: initialized extraction service.  
Logic: creates `GroqExtractor`, `RuleValidator`, and `EmbeddingProcessor` instances.

Function: `_extract_and_validate(file_path)`  
Input: PDF path.  
Output: pre-dedup validated rules.  
Logic:
1. Ingests PDF pages via `ingest_pdf`.
2. Extracts rules page-by-page via `GroqExtractor.extract_rules`.
3. Validates/normalizes via `RuleValidator`.
4. Applies `override_severity`.
5. Returns combined rules.

Function: `process_document(file_path)`  
Input: single PDF path.  
Output: final deduplicated rules for one document.  
Logic:
1. `_extract_and_validate`.
2. Generate embeddings.
3. Deduplicate rules.
4. Assign UUID `rule_id` per final rule.

Function: `process_batch(file_paths)`  
Input: list of PDF paths.  
Output: globally deduplicated rules across all docs.  
Logic:
1. Runs `_extract_and_validate` per document.
2. Aggregates all rules.
3. Embeds and deduplicates globally.
4. Assigns UUIDs.
5. Computes per-document before/after counts in logs.

Function: `save_results(rules, output_path, document_name="", total_pages=0, source_documents=None)`  
Input: rules and output metadata.  
Output: written JSON path.  
Logic:
1. Builds envelope with timestamp/model/count metadata.
2. Adds `rules` array.
3. Uses custom serializer for numpy/UUID values.
4. Writes JSON to disk.

Standalone functions:

Function: `ingest_pdf(file_path)`  
Input: PDF path.  
Output: page objects (`page_number`, `text`, `section_heading`).  
Logic:
1. Opens PDF.
2. Extracts text from each page.
3. If no text, attempts OCR via PyMuPDF OCR then fallback flags then RapidOCR helper.
4. Detects page heading with `_detect_heading` and carries forward last heading.
5. Returns extracted page list.

Function: `_ocr_page_with_rapidocr(page, dpi=300)`  
Input: page handle and DPI.  
Output: OCR text string.  
Logic: renders page pixmap, runs RapidOCR ONNX engine, joins line texts.

Function: `_detect_heading(page)`  
Input: page handle.  
Output: heading string or `None`.  
Logic: scores spans by relative font size, all-caps pattern, numbered-heading pattern; returns best candidate.

Function: `_parse_json_response(raw)`  
Input: raw LLM response text.  
Output: list of rule dicts.  
Logic: strips `<think>`, markdown fences, extracts first JSON array, parses with `json.loads`.

Function: `_enforce_categories(rules)`  
Input: rule list.  
Output: rule list with normalized `categories`.  
Logic: maps invalid categories to `general_safety`, removes singular `category` key.

Function: `override_severity(rules)`  
Input: rule list.  
Output: same list with `validated_severity`.  
Logic: uses regex patterns for toxic/electrical/PPE signals over actionable+original text and bumps severity floors.

Function: `_get_db_connection(register_vec=True)`  
Input: whether to register pgvector adapter.  
Output: psycopg2 connection.

Function: `_init_schema()`  
Logic: reads `database/schema.sql` and executes it against DB.

Function: `migrate_json_to_db(json_path)`  
Input: extraction JSON file path.  
Output: none.  
Logic:
1. Loads JSON envelope/rules.
2. Optionally inserts extraction run metadata.
3. Bulk inserts rules into `safety_rules` using `execute_values`.
4. Uses `ON CONFLICT (rule_id) DO NOTHING`.

Function: `main()`  
Input: CLI args (`input`, `--output`, `--model`, `--threshold`, `--migrate`).  
Output: writes output JSON and prints summary.  
Logic:
1. Migration mode if `--migrate` provided.
2. Resolves input as single PDF or directory batch.
3. Runs single-doc or batch processing path.
4. Saves JSON envelope to `output/` default path if not provided.

External dependencies and side effects across file:
1. Groq API network calls.
2. OCR/model inference workloads.
3. File reads/writes to PDFs/JSON/logs.
4. Optional DB schema/data writes in migration mode.

### File: `rule_extraction/requirements.txt`
What it does: extraction/evaluation dependency list.  
Why it exists: installation baseline for pipeline runtime.  
Where used: environment setup for CLI and subprocess runs.  
Functions: none.


Dedup flow:

`extract_rules.py::SafetyRuleExtractionService`
  -> `embeddings.py::generate_embeddings`
  -> `embeddings.py::deduplicate_rules`



## 3. Data Flow

End-to-end extraction data flow:

1. Input:
- PDF file(s).

2. Transformations:
- Page text extraction (`ingest_pdf`).
- Optional OCR fallback.
- Heading detection.
- LLM rule extraction per page.
- Category enforcement.
- Rule validation/splitting/verb normalization.
- Severity overrides.
- Embedding generation and deduplication.
- UUID assignment.

3. Output:
- JSON envelope with metadata and final rules.
- Optional DB migration path to `extraction_runs` + `safety_rules`.

Evaluation data flow:
1. Input extraction JSON (+ optional PDF).
2. Check computations.
3. Aggregate metrics output JSON.



## 4. Core Components

1. PDF ingestion and OCR fallback  
Implemented in `extract_rules.py` (`ingest_pdf`, `_ocr_page_with_rapidocr`).

2. LLM extraction and JSON parsing  
Implemented in `extract_rules.py` (`GroqExtractor`, `_parse_json_response`).

3. Rule validation and normalization  
Implemented in `extract_rules.py` (`RuleValidator`).

4. Severity calibration  
Implemented in `extract_rules.py` (`override_severity`).

5. Embedding-based deduplication  
Implemented in `embeddings.py` and orchestrated by `SafetyRuleExtractionService`.

6. Evaluation tooling  
Implemented in `evaluate_rules.py`.

