# Technical Documentation: AI-Powered DIY Safety Analysis System

**Version:** 1.0  
**Date:** March 2026  
**Classification:** Technical Report

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Safety Rule Extraction System](#2-safety-rule-extraction-system)
3. [Rule Matching System](#3-rule-matching-system)
4. [End-to-End Demo Walkthrough](#4-end-to-end-demo-walkthrough)
5. [System Evaluation](#5-system-evaluation)
6. [LLM Comparison and Model Selection](#6-llm-comparison-and-model-selection)
7. [UI and Application Architecture](#7-ui-and-application-architecture)

---

## 1. System Overview

This system performs automated safety compliance analysis on DIY video tutorials sourced from YouTube. A user submits a YouTube URL; the system fetches the video transcript, extracts procedural steps via a large language model, embeds those steps into a vector space, retrieves relevant safety rules from a pre-populated compliance database via cosine similarity search, and then synthesises a structured safety report using a second LLM call.

The system comprises three major subsystems:

1. **Safety Rule Extraction Pipeline** (`safety-extraction/`) — an offline batch process that ingests regulatory PDF documents, extracts safety rules via LLM, generates vector embeddings, deduplicates the rule set, and stores the results in a Supabase PostgreSQL database with the `pgvector` extension.

2. **Rule Matching and Analysis Backend** (`backend/`) — a FastAPI server that orchestrates transcript fetching, step extraction, vector similarity search, and multi-model safety assessment in real time, delivering results as a Server-Sent Events (SSE) stream.

3. **Frontend UI** (`frontend/`) — a React + TypeScript single-page application that renders the analysis pipeline state, DIY steps, per-model safety reports, and a model comparison table.

---

## 2. Safety Rule Extraction System

### 2.1 Data Source

Safety rules are extracted exclusively from regulatory and compliance PDF documents uploaded by an operator. There is no integration with a live OSHA API or any external web service for data ingestion. Documents are loaded from the local filesystem; the operator places PDF files in the `safety-extraction/input/` directory and invokes the pipeline via the command-line entry point (`python -m src <file1.pdf> <file2.pdf>`).

Supported input types:
- Standard text-layer PDFs (construction standards, OSHA handbooks, workshop safety manuals, product handling guides).
- Scanned-image PDFs (handled via OCR fallback — see Section 2.2).

### 2.2 PDF Processing

**Library:** PyMuPDF (`fitz`), invoked inside `safety-extraction/src/ingestion.py`.

**Text extraction logic:**

For each page in the document, `page.get_text()` is called to extract the text layer. If the returned string is empty (indicating a scanned page with no text layer), the pipeline attempts OCR using PyMuPDF's built-in `get_textpage_ocr()` method. If the primary OCR call fails, a second OCR attempt is made with the `TEXT_PRESERVE_WHITESPACE` flag. Pages that produce no text after all attempts are skipped with a warning.

**Heading detection:**

After text extraction, `_detect_heading()` analyses font sizes of all spans on the page. Spans with a font size greater than 1.15× the page median, spans in ALL CAPS under 80 characters, or spans matching a numbered heading pattern (e.g., `1.2.3 SECTION TITLE`) receive a heuristic score. The highest-scoring span is recorded as the `section_heading` for that page. This heading is later passed to the LLM as metadata context.

**Output per page:**

```python
{
    "page_number": int,
    "text": str,       # full extracted text
    "section_heading": str,
}
```

**Chunking strategy:**

The system does not apply a secondary chunking step. Each page is treated as a single chunk and submitted individually to the LLM. This design preserves page-level metadata (page number, section heading) and avoids splitting a rule across artificial chunk boundaries. For very long pages, the LLM's 4096-token output limit constrains rule extraction, but the 32B model handles typical regulatory page lengths without truncation.

### 2.3 LLM for Rule Extraction

| Property | Value |
|---|---|
| Provider | Groq API |
| Model | `qwen/qwen3-32b` |
| Temperature | 0.1 |
| Max output tokens | 4096 |
| Max retries (per page) | 3 |

**Implementation file:** `safety-extraction/src/llm.py`, class `GroqExtractor`.

Qwen3-32B was selected because it produces consistently structured JSON output, has a large context window suitable for dense regulatory text, and operates within the cost constraints of the Groq inference API. Temperature is set to 0.1 to minimise hallucination while allowing minor paraphrasing.

The model is called at line:

```python
response = self._client.chat.completions.create(
    model=self._model_name,
    messages=[system_message, user_message],
    temperature=0.1,
    max_tokens=4096,
)
```

**Response handling:**

The raw response text is post-processed by `_parse_json_response()` which: strips `<think>...</think>` blocks emitted by Qwen3's chain-of-thought wrapper, strips markdown code fences, and extracts the first valid JSON array using bracket-depth matching. Any non-dict items within the array are discarded. If JSON parsing fails, the attempt is retried up to `max_retries` times before raising `ExtractionError`.

### 2.4 Prompt Design

**File:** `safety-extraction/src/prompt.py`

**System message:**

```
"You are a safety compliance extraction engine. Return ONLY a valid JSON array. No commentary."
```

**User prompt template:** `EXTRACTION_PROMPT`

The prompt instructs the model to behave as a "Safety Compliance Extraction Engine" and enforces the following constraints:

- **Atomicity:** Compound instructions must be split into separate rules. Example: "Wear gloves and safety goggles" becomes two rules.
- **Verb-first format:** Every `actionable_rule` must begin with an imperative verb (e.g., "Disconnect", "Wear", "Inspect"). Narrative context such as "To prevent injury, always..." is stripped to the core action.
- **No inference:** The model is explicitly forbidden from generating advice not present in the source text.
- **Category constraint:** Only the 12 predefined categories are permitted. Hallucinated category strings are replaced with `general_safety` by `_enforce_categories()` in post-processing.
- **Discard non-actionable text:** Informational text, legal disclaimers, and vague phrases are to be discarded rather than converted.
- **JSON-only output:** No commentary, markdown fences, or explanations are permitted outside the JSON array. This is enforced both in the prompt and in the retrying parse logic.

**Why strict JSON enforcement is used:**

The extracted rules are consumed programmatically by the embedding and deduplication pipeline and stored directly in a PostgreSQL database. Any free-text prefix or suffix in the response would cause `json.loads()` to raise an exception, triggering a retry. The `_parse_json_response()` function provides defensive fallback parsing (bracket extraction), but the primary goal is to receive structurally correct output on the first attempt to minimise Groq API calls.

**Document metadata injected into each prompt:**

```
DOCUMENT METADATA:
- Document: {document_name}
- Section: {section_heading}
- Page: {page_number}
```

### 2.5 Output Format (Per-Rule JSON Schema)

The LLM is instructed to return a JSON array where each element conforms to the following schema:

| Field | Type | Description |
|---|---|---|
| `original_text` | string | Exact sentence or fragment copied verbatim from the document source page |
| `actionable_rule` | string | Verb-first imperative rule containing a single constraint |
| `category` | string[] | One or more values from the allowed category taxonomy |
| `materials` | string[] | Explicitly named materials, chemicals, or tools referenced in the rule |
| `suggested_severity` | integer (1–5) | LLM-proposed severity based on consequence implied by the text |

After extraction, the service layer adds:

| Field | Type | Description |
|---|---|---|
| `source_document` | string | Stem of the source PDF filename |
| `page_number` | integer | Page number within the source document |
| `section_heading` | string | Detected section heading of the page |
| `validated_severity` | integer (1–5) | Deterministic severity after override rules (see Section 2.8) |
| `rule_id` | UUID string | Assigned after deduplication |
| `embedding` | float[] (384-dim) | Generated by the embedding processor |

**Example JSON object:**

```json
{
  "original_text": "Wear safety goggles when operating any power tool that produces airborne particles.",
  "actionable_rule": "Wear safety goggles when operating power tools that produce airborne particles.",
  "category": ["PPE_required", "power_tools"],
  "materials": ["safety goggles"],
  "suggested_severity": 3,
  "source_document": "OSHA_Woodworking_Handbook",
  "page_number": 14,
  "section_heading": "3.1 EYE AND FACE PROTECTION",
  "validated_severity": 3,
  "rule_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

### 2.6 Rule Categories

All categories are defined in `safety-extraction/src/constants.py` as `ALLOWED_CATEGORIES`.

| Category | Description |
|---|---|
| `electrical` | Rules involving wiring, circuits, live conductors, grounding, arc flash, or panel work |
| `chemical` | Rules involving solvents, adhesives, paints, acids, bleach, ammonia, or other chemical agents |
| `woodworking` | Rules specific to cutting, shaping, sanding, or finishing wood |
| `power_tools` | Rules governing the use of powered equipment: saws, drills, grinders, routers |
| `heat_fire` | Rules involving soldering, welding, open flame, torch work, or flammable material storage |
| `mechanical` | Rules involving load bearing, lifting, jacking, bracing, or structural support |
| `PPE_required` | Rules that mandate specific personal protective equipment |
| `child_safety` | Rules concerning age restrictions, supervision requirements, or activities unsuitable for minors |
| `toxic_exposure` | Rules concerning exposure to substances with systemic toxic effects: asbestos, carbon monoxide, cyanide compounds |
| `ventilation` | Rules requiring adequate air flow, exhaust systems, or open-air conditions |
| `structural` | Rules involving foundation, load-bearing elements, or structural integrity |
| `general_safety` | Fallback category for rules that do not fit any specific category above |

### 2.7 Severity Scale

Severity is represented as an integer on a 1–5 scale. The LLM proposes a `suggested_severity`; the `override_severity()` function in `safety-extraction/src/severity.py` then applies deterministic pattern-based overrides to produce `validated_severity`.

| Level | Interpretation |
|---|---|
| 1 | Minor injury risk; discomfort or superficial injury possible |
| 2 | Moderate injury risk; cuts, burns, or sprains without long-term consequence |
| 3 | Serious injury risk; fractures, chemical burns, or eye damage possible |
| 4 | Life-threatening hazard; electrocution, severe burns, or fall from height |
| 5 | Extreme or fatal risk; legally restricted activity or exposure with lethal consequence |

**Deterministic override rules** (applied after LLM extraction):

- Any rule whose combined text matches patterns for toxic gas (chlorine gas, hydrogen sulfide, carbon monoxide, cyanide, etc.) is forced to severity 5.
- Any rule referencing high voltage, live wire, arc flash, or electrical shock is elevated to a minimum severity of 4.
- Any rule mentioning PPE items (goggles, gloves, hard hat, respirator, etc.) is elevated to a minimum severity of 3.

This prevents the LLM from under-classifying inherently dangerous rules.

### 2.8 Deduplication Logic

**File:** `safety-extraction/src/embeddings.py`, method `EmbeddingProcessor.deduplicate_rules()`

**Algorithm:**

1. All rules must have embeddings generated before deduplication is called.
2. Embeddings are stacked into a matrix of shape `(n, 384)`.
3. Each row is L2-normalised so that the dot product equals the cosine similarity.
4. The normalised matrix is multiplied by its transpose to produce an `(n, n)` cosine similarity matrix.
5. A greedy O(n²) scan is performed: for each rule `i` not yet marked as duplicate, every subsequent rule `j` whose cosine similarity with `i` exceeds the threshold `0.90` is removed.
6. The first occurrence is always kept; later near-duplicate rules are discarded.

**Similarity threshold:** `0.90`. Rules with cosine similarity above this value encode the same semantic constraint and are considered duplicates regardless of minor wording differences.

For multi-document batch processing (`process_batch()`), embeddings are generated across the complete combined rule set before deduplication, so identical rules extracted from two different PDF sources are collapsed into a single entry.

### 2.9 Embedding Concept and Model

**Conceptual explanation:**

An embedding is a fixed-length dense floating-point vector that encodes the semantic meaning of a text string. Two texts with similar meaning are mapped to vectors that are close together in the embedding space, as measured by cosine similarity. In this system, embeddings allow rules stored in the database to be compared with DIY step descriptions without requiring exact keyword overlap. A step describing "attach wires to the breaker panel" will be geometrically close to a rule stating "Disconnect power before connecting any conductor to a live circuit" because both texts share the electrical-connection semantic domain.

**Model:**

| Property | Value |
|---|---|
| Model name | `all-MiniLM-L6-v2` |
| Provider | `sentence-transformers` (Hugging Face) |
| Embedding dimension | 384 |
| Library | `sentence-transformers` Python package |

`all-MiniLM-L6-v2` was selected because it provides a good trade-off between inference speed and semantic accuracy for English-language safety and procedural text. Its 384-dimensional output is compact enough for efficient IVFFlat indexing in PostgreSQL, and the model runs on CPU without a GPU requirement, making it suitable for deployment in constrained environments.

Crucially, the **same model must be used** in both the extraction pipeline (when rule embeddings are generated and stored) and the matching backend (when step embeddings are generated at query time). Mixing embedding models would produce vectors in incompatible spaces, making cosine similarity comparisons meaningless.

### 2.10 Storage in Supabase (PostgreSQL + pgvector)

**File:** `safety-extraction/src/schema.sql`

The system requires the PostgreSQL `vector` extension (pgvector) to be enabled in the target Supabase project.

**Table: `safety_rules`**

| Column | Type | Description |
|---|---|---|
| `id` | SERIAL PRIMARY KEY | Auto-incrementing internal row identifier |
| `rule_id` | UUID UNIQUE NOT NULL | Application-assigned unique identifier per rule |
| `original_text` | TEXT NOT NULL | Verbatim text from source document as extracted |
| `actionable_rule` | TEXT NOT NULL | Verb-first imperative rule produced by the LLM |
| `materials` | TEXT[] | Array of materials/tools named in the rule |
| `suggested_severity` | INTEGER (1–5) | LLM-proposed severity |
| `validated_severity` | INTEGER (1–5) | Severity after deterministic override rules |
| `categories` | TEXT[] | Array of category labels from the allowed taxonomy |
| `source_document` | TEXT NOT NULL | PDF filename stem (without extension) |
| `page_number` | INTEGER | Source page number |
| `section_heading` | TEXT | Detected section heading on the source page |
| `embedding` | vector(384) | 384-dimensional floating-point embedding of `actionable_rule` |
| `created_at` | TIMESTAMPTZ | Row insertion timestamp |

**Indexes:**

- `idx_rules_categories`: GIN index on the `categories` array column, enabling fast `categories && %s::text[]` overlap queries.
- `idx_rules_severity`: B-tree index on `validated_severity DESC` for filtered queries.
- `idx_rules_document`: B-tree index on `source_document` for pagination and filtering.
- `idx_rules_embedding`: IVFFlat index (`embedding vector_cosine_ops`, `lists = 10`), enabling approximate nearest-neighbour cosine similarity search. Configured for up to approximately 100,000 rules.

**Embedding storage and retrieval:**

Embeddings are stored as `vector(384)` columns. During insertion, the Python-side embedding list is serialised as a compact string `[f1,f2,...,f384]` and cast with `%s::vector`. During retrieval, the cosine distance operator `<=>` is used:

```sql
1 - (embedding <=> %s::vector) AS similarity
ORDER BY embedding <=> %s::vector
LIMIT %s
```

The `1 - distance` expression converts a pgvector cosine distance (0 = identical, 2 = opposite) to a cosine similarity score in the range [−1, 1], where 1 is a perfect match.

**Table: `extraction_runs`**

Records each invocation of the extraction pipeline with metadata: model used, total pages processed, rule count, source documents, and evaluation results (stored as JSON).

---

## 3. Rule Matching System

This subsystem is responsible for comparing extracted DIY procedural steps against the stored safety rules database and producing a structured safety report.

### 3.1 Code Workflow

The full pipeline from YouTube URL submission to safety report is:

```
1.  User submits YouTube URL
         ↓
2.  Extract video ID from URL
         ↓
3.  Fetch video transcript (youtube-transcript-api, timestamps at 30s intervals)
         ↓
4.  Fetch video metadata (title, author via YouTube oEmbed API)
         ↓
5.  Send transcript to Groq LLM (streaming) → structured step extraction JSON
         ↓
6.  Parse step JSON: is_diy check, safety_categories, steps[], materials[], tools[]
         ↓
7.  Non-DIY videos: terminate immediately, emit not_diy event
         ↓
8.  For each step: embed (action_summary + step_text + transcript_excerpt)
         ↓
9.  For each step: pgvector cosine search → top-K candidate rules (K=10)
         ↓
10. Filter candidates by cosine similarity threshold (≥ 0.30)
         ↓
11. Two LLMs (qwen/qwen3-32b and openai/gpt-oss-20b) run in parallel:
         ↓
12. Each LLM receives: steps + per-step matched rules + safety_categories
         ↓
13. Each LLM returns: safety_report JSON (verdict, risk score, per-step analysis)
         ↓
14. Model comparison table built from both reports
         ↓
15. Results saved to database (scans table)
         ↓
16. SSE stream terminated with done event
```

### 3.2 Transcript Extraction

**File:** `backend/services/transcript.py`

**Library:** `youtube-transcript-api`

The `_fetch_transcript_sync()` function calls `YouTubeTranscriptApi().fetch(video_id, languages=["en"])`. If no English transcript is available, it falls back to any available language. The returned snippets (each with a `start` float and `text` string) are grouped into 30-second chunks and formatted as:

```
[0:00] First thirty seconds of speech combined into one chunk.
[0:30] Next thirty seconds of speech.
```

This timestamp-prefixed format is passed verbatim to the step extraction LLM, preserving temporal ordering information.

Video metadata (title, author) is fetched from the YouTube oEmbed endpoint (`https://www.youtube.com/oembed`) using `httpx`.

### 3.3 Step Extraction Prompt Design

**File:** `backend/services/groq_client.py`, constant `STEP_EXTRACTION_PROMPT`

The system prompt instructs the model to:

1. **DIY detection (mandatory first step):** Determine whether the video is a DIY tutorial. Non-DIY videos (vlogs, reviews, gaming content, commentary) must return `"is_diy": false` with empty arrays for all other fields.
2. **Strict grounding:** Every step, tool, material, and safety precaution in the output must be explicitly supported by transcript wording. The model is forbidden from inferring safety guidelines not stated in the video.
3. **Safety category classification:** Classify the procedure into one or more of the 12 predefined categories (same taxonomy as the rule extraction system).
4. **Step field definitions:**
   - `transcript_excerpt`: Verbatim copy of the creator's words for that step.
   - `step_text`: Rewritten clean 1–2 sentence instruction removing filler words but preserving measurements and technical terms.
   - `action_summary`: 3–8 word imperative phrase (e.g., "Connect wiring to junction box").
5. **Hallucination prevention:** All extracted elements must be verifiable against the transcript.

The `/no_think` directive appended to the prompt suppresses Qwen3's chain-of-thought output, which would otherwise appear in the streaming response before the JSON.

**Step JSON schema:**

```json
{
  "is_diy": true,
  "title": "string",
  "diy_categories": ["free-text categories"],
  "safety_categories": ["from predefined taxonomy only"],
  "materials": ["list of materials"],
  "tools": ["list of tools"],
  "steps": [
    {
      "step_number": 1,
      "transcript_excerpt": "exact words from transcript",
      "step_text": "clean instruction",
      "action_summary": "imperative phrase"
    }
  ],
  "safety_precautions": ["precautions explicitly stated in video"],
  "target_audience": "adults / teens / children / family",
  "supervision_mentioned": false,
  "skill_level": "beginner / intermediate / advanced"
}
```

### 3.4 Step Embedding Model

**File:** `backend/services/embeddings.py`, class `EmbeddingService`

The same `all-MiniLM-L6-v2` model is used for embedding DIY steps at query time. For each step, the embedding input is constructed by concatenating:

```
action_summary + " " + step_text + " " + transcript_excerpt
```

This produces a richer semantic representation than the `action_summary` alone, and the `transcript_excerpt` grounds the embedding in the creator's specific vocabulary, improving match recall for domain-specific DIY terminology.

The `EmbeddingService` is implemented as a singleton (`get_instance()` class method) so the model is loaded into memory once per server process rather than once per request.

### 3.5 Cosine Similarity and Vector Search

**Cosine similarity** measures the angle between two vectors in the embedding space:

$$\text{similarity}(\vec{a}, \vec{b}) = \frac{\vec{a} \cdot \vec{b}}{\|\vec{a}\| \cdot \|\vec{b}\|}$$

A value of 1.0 indicates identical semantic direction; 0.0 indicates orthogonal (unrelated) vectors; negative values indicate semantic opposition (rare for same-domain text).

In the context of this system: a DIY step embedding and a safety rule embedding with cosine similarity ≥ 0.30 are considered semantically related; the rule is a candidate for matching that step.

pgvector computes cosine similarity using the `<=>` (cosine distance) operator: `distance = 1 - similarity`. The query uses `ORDER BY embedding <=> %s::vector` to sort by ascending distance (descending similarity), and `LIMIT %s` to return the top-K results efficiently via the IVFFlat index.

### 3.6 Top-K Retrieval

**K = 10** rules are retrieved per step by the backend `EmbeddingService` (`DEFAULT_TOP_K = 10`).

For the `RuleMatcher` class in the safety-extraction module (used in offline analysis), `top_k = 15`.

Top-K retrieval is used rather than a fixed similarity cutoff for the initial recall phase because:
- It guarantees a bounded number of candidates regardless of the density of the rule embedding space.
- The similarity threshold is applied as a post-filter (`similarity >= 0.30`) to remove low-quality matches.
- The downstream LLM safety analyser performs the final relevance judgement, which means it is preferable to over-retrieve and let the LLM filter than to under-retrieve and miss important rules.

**Category-filtered search:**

Before the unfiltered top-K search, the backend optionally executes a category-filtered query if `safety_categories` were extracted from the step. This uses the GIN-indexed `categories && %s::text[]` overlap condition to restrict candidates to rules in semantically aligned categories, improving precision. If the category-filtered result set contains fewer than 3 candidates, an unfiltered fallback search is performed and its results are merged (deduplicating by `rule_id`).

### 3.7 Violation Detection and Classification

**File:** `safety-extraction/src/matcher.py`, class `RuleMatcher` and `StepNormalizer`

After retrieval, each candidate rule is classified into one of three match types by deterministic logic. The `StepNormalizer` uses spaCy (`en_core_web_sm`) to lemmatize step text, extract action verbs, detect hazard categories from keyword lists, identify PPE mentions, and detect precaution phrases.

**Match type 1 — Violation:** The step text matches a regex pattern that directly contradicts the rule text. Hard-coded `CONTRADICTION_PATTERNS` cover cases such as:
- Connecting wires to a live panel while the rule requires power disconnection.
- Mixing bleach with ammonia while the rule prohibits combining those chemicals.
- Cutting toward the body while the rule requires cutting away from the body.
- Removing a safety guard while the rule requires keeping it in place.

**Match type 2 — Missing precaution:** The rule requires a safety action that is absent from the step description. Checked categories include:
- PPE: If the rule mentions a PPE item (e.g., goggles, gloves, respirator) and the step description does not, and the step involves a hazard category relevant to that PPE type.
- Power isolation: If the step involves electrical work and the rule requires disconnecting or de-energising, but no isolation language appears in the step.
- Ventilation: If the step involves chemical or respiratory hazards, and the rule requires ventilation that is absent from the step.
- Securing workpiece: If the step involves cutting, and the rule requires clamping or securing, but no securing language appears in the step.

**Match type 3 — High-risk action:** A rule with `validated_severity >= 4` has cosine similarity `>= 0.40` with the step, and either there is a hazard category overlap between the step and the rule, or the similarity is `>= 0.55`. This flag does not require a proven direct contradiction; it serves as a warning that a high-severity rule is semantically related to what the step is doing.

### 3.8 Safety Report Generation (LLM-Based Final Assessment)

**File:** `backend/services/safety_analyzer.py`

After vector matching, the backend constructs a user message that lists all extracted steps with their transcript excerpts, plus the per-step matched rules with their severity scores, categories, and similarity percentages. This combined context is sent to the LLM for final safety assessment.

**System prompt (`SAFETY_ANALYSIS_PROMPT`):**

The prompt instructs the model to produce a structured JSON safety report. Key instructions:
- For each step: identify required precautions (from matched rules and general category knowledge), already-mentioned precautions (what the creator shows in the video), and missing precautions.
- Assign a risk level (1–5) per step.
- Produce an overall verdict: `SAFE`, `UNSAFE`, or `PROFESSIONAL_REQUIRED`.
- Determine whether parent/adult monitoring is required based on tools, chemicals, heat sources, and skill level.
- List critical concerns and recommended additional safety measures.

**Models used for final assessment:**

Both `qwen/qwen3-32b` and `openai/gpt-oss-20b` are called in parallel (`asyncio.gather`). Their reports are buffered until both complete, then emitted simultaneously via SSE along with a model comparison table.

### 3.9 Risk Score

The overall risk score (1.0–5.0) is determined by the LLM analysing the combination of:
- Severity of matched rules per step.
- Number of missing precautions.
- Number of steps assessed at risk level 4 or 5.
- Whether critical hazards (electrical, chemical, structural) are present.

The LLM produces this as a float in its JSON output. The backend does not apply a separate formula; the score is the model's direct output reflecting its holistic assessment of the procedure.

### 3.10 Safety Report Output Format

```json
{
  "verdict": "SAFE | UNSAFE | PROFESSIONAL_REQUIRED",
  "overall_risk_score": 3.2,
  "parent_monitoring_required": true,
  "parent_monitoring_reason": "string",
  "summary": "2–3 sentence summary",
  "critical_concerns": ["concern 1", "concern 2"],
  "step_safety_analysis": [
    {
      "step_number": 1,
      "action_summary": "string",
      "risk_level": 3,
      "required_precautions": ["precaution 1"],
      "already_mentioned_precautions": ["precaution A"],
      "missing_precautions": ["precaution B"],
      "matched_rules": [
        {
          "rule_text": "string",
          "severity": 3,
          "category": "string",
          "relevance": "explanation"
        }
      ]
    }
  ],
  "safety_measures_in_video": ["measure 1"],
  "recommended_additional_measures": ["measure X"]
}
```

---

## 4. End-to-End Demo Walkthrough

The following illustrates a complete analysis run for a hypothetical DIY electrical wiring tutorial.

**Step 1 — User input:**  
The user pastes a YouTube URL (e.g., `https://www.youtube.com/watch?v=xxxxxxxxxxx`) into the URL field and submits the form.

**Step 2 — Transcript fetch:**  
The frontend calls `GET /api/analyze?video_id=xxxxxxxxxxx`. The backend opens an SSE connection. In the first stage, `youtube-transcript-api` fetches the English captions and groups them into 30-second timestamp blocks. Video metadata (title, author) is fetched from YouTube oEmbed and emitted as a `metadata` event.

**Step 3 — Step extraction (streaming):**  
The transcript is sent to Groq with the step extraction system prompt. The response streams token-by-token; the frontend receives `steps_delta` events and renders the raw JSON as it arrives. The `/no_think` directive prevents chain-of-thought text from appearing in the stream. When streaming completes, a `steps_complete` event is emitted containing the full parsed JSON.

Example extracted steps:
```json
[
  { "step_number": 1, "action_summary": "Turn off circuit breaker",
    "step_text": "Locate the circuit breaker panel and switch off the breaker for the target circuit.",
    "transcript_excerpt": "first thing you want to do is go to your breaker box and flip the switch" },
  { "step_number": 2, "action_summary": "Strip wire insulation",
    "step_text": "Use wire strippers to remove 3/4 inch of insulation from each conductor.",
    "transcript_excerpt": "grab your wire strippers and take off about three quarters of an inch" },
  { "step_number": 3, "action_summary": "Connect conductors to outlet terminals",
    "step_text": "Attach the black (hot) conductor to the brass terminal and the white (neutral) to the silver terminal.",
    "transcript_excerpt": "the black wire goes to the gold screw and the white wire goes to the silver" }
]
```
`safety_categories` extracted: `["electrical", "PPE_required"]`

**Step 4 — Vector matching:**  
For each step, the backend generates a 384-dim embedding and queries pgvector. Step 1 ("Turn off circuit breaker") retrieves rules such as:
- "Disconnect power before servicing any electrical component." (similarity: 0.82, severity: 4)
- "Verify circuit is de-energised using a voltage tester before touching conductors." (similarity: 0.71, severity: 4)

Step 3 ("Connect conductors to outlet terminals") retrieves:
- "Never connect conductors to a live circuit." (similarity: 0.64, severity: 5)
- "Wear insulated gloves when handling electrical conductors." (similarity: 0.51, severity: 3)

**Step 5 — Safety report (LLM assessment):**  
Both models receive the step list with matched rules. The backend emits a `safety_report` event for each model. Example report fields:
- `verdict`: `"UNSAFE"` (insulated gloves not mentioned in video)
- `overall_risk_score`: 3.8
- `parent_monitoring_required`: true
- Step 3 `missing_precautions`: `["Wear insulated gloves when handling electrical conductors", "Use a voltage tester to verify circuit is de-energised before connecting"]`

**Step 6 — Model comparison:**  
A `model_comparison` event is emitted containing a structured table comparing both models on verdict, risk score, number of missing precautions, and high-risk step count.

**Step 7 — Persistence:**  
The frontend saves the analysis to the `/api/scans` endpoint. The scan appears in the left sidebar history panel with risk score and verdict.

---

## 5. System Evaluation

### 5.1 What Is Evaluated

The extraction pipeline is evaluated using a 4-check "brutal evaluation" implemented in `backend/extraction/evaluation.py`, function `run_brutal_evaluation()`. This evaluation runs automatically after every extraction pipeline invocation and results are persisted in the `extraction_runs` table.

### 5.2 Evaluation Method and Checks

The evaluation opens the source PDF using PyMuPDF, reads the text from all pages into a dictionary keyed by page number, and then verifies each extracted rule against that dictionary.

**Check 1 — Text Presence:**  
Verifies that the `original_text` field of the extracted rule actually appears somewhere in the source PDF. First attempts an exact substring match (case-insensitive). If that fails, attempts a word-overlap match: the rule passes if at least 60% of its words appear in any page of the PDF. This check detects rules where the LLM generated `original_text` that was not present in the document (hallucination).

**Check 2 — Page Accuracy:**  
Verifies that the `original_text` appears on the claimed `page_number` (with ±1 page tolerance). Uses the first 8 words of `original_text` as a search string. Falls back to a 70% word-overlap test within the ±1 page window. This check detects rules where the page attribution metadata is incorrect.

**Check 3 — Category Validity:**  
Verifies that all values in the `categories` array belong to the 12-element `ALLOWED_CATEGORIES` set. This check detects any categories that survived the `_enforce_categories()` post-processing incorrectly.

**Check 4 — Severity Consistency:**  
Verifies two conditions:
1. If the rule text contains high-hazard keywords (toxic, fatal, death, electrocution, fire, explosion, asbestos, burn, amputation, crush), then `validated_severity` must be ≥ 3.
2. `validated_severity` must not be lower than `suggested_severity`.

This check detects cases where severity was incorrectly downgraded through the override logic.

### 5.3 Metrics

For each check, per-rule pass/fail results are recorded. Aggregate metrics computed:

- **Per-check accuracy:** `checks_passed / checks_total × 100` for each of the 4 checks.
- **Overall accuracy:** `total_checks_passed / total_checks × 100` across all 4 checks and all rules.
- **Rules fully passing:** Count of rules where all 4 checks pass.
- **Rules with failures:** Count of rules where at least one check fails.

A structural evaluation variant (`run_structure_evaluation()`) operates without requiring the source PDF and checks rule structure (verb-first imperative), category validity, and severity consistency only—useful for evaluating rules when the original PDF is not available.

### 5.4 Observations

The text-presence and page-accuracy checks are the primary indicators of hallucination. High pass rates on these checks (>90%) indicate the LLM correctly grounds its extractions in the source document. The severity-consistency check catches cases where the deterministic override patterns did not fire for hazardous rules, which may indicate the need to extend the `SEVERITY_PATTERNS` set.

Low page-accuracy scores on a specific document typically indicate that the document has unusual page layouts (multi-column, table-heavy) where `page.get_text()` returns text in a non-sequential order, causing the section heading detection and page attribution to drift.

---

## 6. LLM Comparison and Model Selection

### 6.1 Models in Production

The backend runs two models in parallel for every safety analysis request:

| Model Key | Model ID | Label |
|---|---|---|
| `qwen` | `qwen/qwen3-32b` | Qwen3 32B |
| `gpt_oss` | `openai/gpt-oss-20b` | GPT-OSS 20B |

Both are served via the Groq API using the OpenAI-compatible chat completions endpoint (`https://api.groq.com/openai/v1/chat/completions`).

### 6.2 Model Selection Rationale

**Qwen3 32B (`qwen/qwen3-32b`):**
- Used in both the extraction pipeline and the safety analysis.
- Produces reliably structured JSON output with minimal need for post-processing cleanup.
- Supports the `/no_think` directive that suppresses chain-of-thought tokens, which is critical for keeping the streaming response clean.
- The 32B parameter size provides sufficient reasoning depth for multi-step safety assessments.
- Temperature 0.1 is used for extraction; this minimises variance while allowing enough flexibility for paraphrasing.
- Temperature 0.0 with `seed: 42` is used for step extraction to enforce fully deterministic output.

**GPT-OSS 20B (`openai/gpt-oss-20b`):**
- Provided as a comparison model to detect model-specific bias or disagreement in safety verdicts.
- Does not support `/no_think`; the system prompt is adjusted at runtime (`is_qwen = "qwen" in model.lower()`) to omit that directive.
- Smaller parameter count than Qwen3 32B, which may produce different risk-scoring behaviour on borderline cases.

### 6.3 Model Comparison Table

The backend generates a structured comparison table after both models complete. Comparison aspects computed deterministically from the two report JSONs (no additional LLM call required):

| Aspect | Description |
|---|---|
| Verdict | `SAFE` / `UNSAFE` / `PROFESSIONAL_REQUIRED` |
| Overall Risk Score | Float 1.0–5.0 |
| Parent Monitoring Required | Boolean |
| Critical Concerns Count | Integer |
| Total Missing Precautions | Sum across all steps |
| Average Step Risk Level | Mean of step `risk_level` values |
| High-Risk Steps (≥ 4) | Count of steps with `risk_level` ≥ 4 |
| Total Matched Rules | Sum of matched rules across all steps |
| Safety Measures Identified | Count of `safety_measures_in_video` |
| Recommended Additions | Count of `recommended_additional_measures` |
| Steps Analyzed | Total step count |

An `agreement` boolean is set per aspect indicating whether both models produced the same value, enabling quick identification of disagreements between models.

### 6.4 Performance Notes

- Both models are invoked with `temperature: 0.1`, `max_tokens: 8192`, `stream: false`, `seed: 42` for the safety analysis call.
- Groq infrastructure provides low-latency inference; typical end-to-end latency for a 10-step DIY analysis is dominated by the transcript fetch and the two parallel LLM calls.
- JSON reliability is high for both models because the prompt enforces strict JSON-only output and the response parser (`_clean_json_response`) strips code fences and extracts the JSON object from any surrounding noise.

---

## 7. UI and Application Architecture

### 7.1 Frontend Framework and Stack

| Component | Technology |
|---|---|
| Framework | React 18 with TypeScript |
| Build tool | Vite |
| Styling | Tailwind CSS |
| CSS preprocessing | PostCSS |
| Type configuration | `tsconfig.json` with strict mode |
| Path aliases | `@/` maps to `src/` |

The application is a single-page application (SPA) with no server-side rendering. The production build is served as static assets.

### 7.2 Application Layout

The main layout (`App.tsx`) is divided into three areas:

- **`TopBar`** — application title bar with settings toggle.
- **`LeftSidebar`** — scan history panel showing past analyses fetched from the `/api/scans` endpoint. Each entry shows video title, channel, verdict, risk score, and date.
- **Main content area** — conditionally renders:
  - `DiyForm`: URL input form and submit button.
  - `VideoInfo`: Video title and author metadata.
  - `AnalysisProgress`: Real-time pipeline status with phase indicators.
  - `DiyStepsContainer` → `DiyStepCard` instances: one card per extracted step.
  - `ModelResultsTabs`: Tab-based view of safety reports per model.
  - `ComplianceVerdict` / `VerdictCard`: Overall verdict display.
- **`RightPanel`** — contextual detail panel (selected step safety analysis, matched rules, missing precautions).
- **`SettingsPanel`** — lazy-loaded panel for API key and model configuration.

### 7.3 State Management

State is managed via `useDiyAnalysis` custom hook (`frontend/src/hooks/useDiyAnalysis.ts`) with React `useState` and `useRef`. There is no global state library.

The hook manages the following state:
- `steps` (`DiyStep[]`): extracted procedural steps.
- `extraction` (`DiyExtraction | null`): full extraction object with materials, tools, categories.
- `report` (`SafetyReport | null`): primary safety report (Qwen3 output by default).
- `modelReports` (`Record<string, ModelReport>`): all per-model reports keyed by model key.
- `comparison` (`ModelComparison | null`): model comparison table.
- `phase` (`AnalysisPhase`): current pipeline phase — `idle | fetching | extracting | analyzing | complete | error | not_diy`.
- `metadata` (`VideoMetadata | null`): video title and author.
- `isLoading`, `isAnalyzing`, `error`, `statusMessage`, `elapsedMs`.

Model reports are buffered in `pendingReportsRef` (a React ref) and only committed to state when the `model_comparison` SSE event arrives. This ensures the UI renders both model results atomically rather than displaying one model's report before the other is ready.

### 7.4 SSE Communication

The frontend connects to the `/api/analyze?video_id=<id>` endpoint using the browser's native `EventSource` API (wrapped in `fetchEventSource` with abort controller support). Incoming events are dispatched through `handleEvent()` which maps event types to state transitions:

| Event Type | Frontend Action |
|---|---|
| `metadata` | Set `metadata` state |
| `status` | Update `statusMessage`, infer `phase` |
| `steps_delta` | Append streaming tokens to `rawText`, filter `<think>` tags |
| `steps_complete` | Parse JSON, set `steps`, `extraction`, `safetyCategories` |
| `not_diy` | Set `isNotDiy`, terminate loading state |
| `safety_report` | Buffer report in `pendingReportsRef` |
| `model_comparison` | Commit all buffered reports + comparison atomically |
| `done` | Set `phase: complete`, stop timer |
| `error` | Set `error` message, reset loading state |

### 7.5 Backend Framework

**File:** `backend/app.py`  
**Framework:** FastAPI

The FastAPI application mounts two routers:

- `api/routes.py` — `APIRouter(prefix="/api")`: all REST and SSE endpoints.
- `ws_router` — WebSocket route for the PDF extraction progress stream.

Static file serving for uploaded PDFs is handled via a mounted `StaticFiles` instance.

**Key endpoints:**

| Method | Path | Description |
|---|---|---|
| GET | `/api/analyze` | SSE stream — full analysis pipeline |
| GET | `/api/health` | Health check with API key and DB status |
| GET | `/api/rules` | Query safety rules with filters (category, severity, document, search, pagination) |
| GET | `/api/filter_options` | Distinct categories, severities, documents for filter dropdowns |
| POST | `/api/extract_rules` | Upload PDF(s), run extraction pipeline (multipart form) |
| GET | `/api/extraction_runs` | List all extraction runs with evaluation results |
| GET | `/api/rules_by_run` | Rules filtered by `run_id` |
| GET | `/api/rules_by_document` | Rules grouped by source document |
| GET/POST | `/api/scans` | Scan history CRUD |
| GET | `/api/scans/{scan_id}` | Retrieve a specific scan by ID |
| WS | `/ws/extract` | WebSocket for real-time extraction progress events |

**`/api/extract_rules` WebSocket flow:**

The PDF upload endpoint supports two modes:
1. **Synchronous (`extract_rules_v2`)**: runs as a blocking subprocess call and returns when complete.
2. **WebSocket-streamed (`extract_rules_with_progress`)**: runs the extraction subprocess with `Popen`, reads stdout line-by-line, parses log messages via regex patterns, and emits progress events to the WebSocket client for each pipeline stage (upload → ingestion → llm\_extraction → validation → embedding → dedup → db\_insert → evaluation → complete).

### 7.6 Database Access

**Database:** Supabase-hosted PostgreSQL with pgvector extension.  
**Connection library:** `psycopg2`  
**Connection URL:** Read from `DATABASE_URL` environment variable; the port is rewritten from 5432 to 6543 to use the Supabase session pooler.

The backend database layer (`backend/db/`) provides:
- `get_db_connection()`: returns a raw psycopg2 connection.
- `fetch_rules_from_db()`: paginated, filtered rule query.
- `fetch_filter_options_from_db()`: distinct categories, severities, documents.
- `fetch_extraction_runs()`: all runs with evaluation JSON.
- `fetch_rules_by_run()`: rules for a specific `run_id`.

The `EmbeddingService` in `backend/services/embeddings.py` opens its own psycopg2 connection for vector similarity queries. pgvector type registration is not used in the backend (embeddings are always serialised to string format for insertion and similarity computations use SQL expressions rather than Python-side vector arithmetic).

### 7.7 Environment Configuration

All runtime secrets and configuration are provided via environment variables read from a `.env` file in the `backend/` directory:

| Variable | Purpose |
|---|---|
| `GROQ_API_KEY` | Groq API authentication for all LLM calls |
| `DATABASE_URL` | Supabase PostgreSQL connection string (port 5432; backend rewrites to 6543) |
| `SUPABASE_URL` | Supabase project URL (used for storage upload reference) |
| `MODEL` | Override default model (defaults to `qwen/qwen3-32b`) |

The `backend/core/config.py` module exposes typed accessor functions (`get_api_key()`, `get_model()`, `get_database_url()`) that read these environment variables.

---

*End of Technical Documentation*
