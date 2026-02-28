# Safety Compliance Extraction Engine — Architecture & Flow

## Overview

The Safety Compliance Extraction Engine is a Python pipeline that ingests safety-related PDF documents (OSHA regulations, Safety Data Sheets, EPA guidance, etc.), extracts **atomic, actionable safety rules** using an LLM, validates and normalizes them with NLP, deduplicates via semantic embeddings, and stores the results in PostgreSQL with pgvector for search and viewing.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CLI Entry Point                              │
│                      src/__main__.py                                │
│  ┌──────────┐   ┌──────────────┐                                   │
│  │ Single   │   │ Batch Mode   │  (directory of PDFs)              │
│  │ PDF Mode │   │ Global Dedup │                                   │
│  └────┬─────┘   └──────┬───────┘                                   │
│       │                │                                            │
│       └───────┬────────┘                                            │
│               ▼                                                     │
│  ┌─────────────────────────────────────────────────────────┐       │
│  │       SafetyRuleExtractionService  (service.py)         │       │
│  │                                                         │       │
│  │  ┌───────────┐  ┌──────────────┐  ┌───────────────┐   │       │
│  │  │ 1. INGEST │→ │ 2. EXTRACT   │→ │ 3. VALIDATE   │   │       │
│  │  │ PDF→Text  │  │ LLM→Rules   │  │ NLP→Normalize │   │       │
│  │  └───────────┘  └──────────────┘  └───────────────┘   │       │
│  │       │                │                  │            │       │
│  │       ▼                ▼                  ▼            │       │
│  │  ingestion.py     llm.py             validator.py      │       │
│  │  + PyMuPDF        + Groq API         + spaCy           │       │
│  │  + OCR fallback   + prompt.py        + Compound split  │       │
│  │                   + JSON parse       + Verb normalize  │       │
│  │                                                         │       │
│  │  ┌───────────────┐  ┌──────────────┐  ┌────────────┐  │       │
│  │  │ 4. SEVERITY   │→ │ 5. EMBED     │→ │ 6. DEDUP   │  │       │
│  │  │ Regex Override│  │ 384-dim vecs │  │ Cosine sim  │  │       │
│  │  └───────────────┘  └──────────────┘  └────────────┘  │       │
│  │       │                │                  │            │       │
│  │       ▼                ▼                  ▼            │       │
│  │  severity.py      embeddings.py      embeddings.py     │       │
│  │  + Regex patterns + MiniLM-L6-v2    + Similarity mtx  │       │
│  │  + Floor logic    + sentence-tfmrs  + Greedy removal  │       │
│  └─────────────────────────────────────────────────────────┘       │
│               │                                                     │
│               ▼                                                     │
│       ┌───────────────┐                                            │
│       │ 7. SAVE JSON  │ → output/*.json                           │
│       └───────┬───────┘                                            │
│               │                                                     │
│               ▼                                                     │
│       ┌───────────────┐    ┌───────────────────┐                   │
│       │ 8. MIGRATE    │ →  │ PostgreSQL +       │                  │
│       │ migrate.py    │    │ pgvector (Supabase)│                  │
│       └───────────────┘    └────────┬──────────┘                   │
│                                     │                               │
│                                     ▼                               │
│                            ┌────────────────┐                      │
│                            │ 9. WEB VIEWER  │                      │
│                            │ FastAPI + HTML  │                      │
│                            │ localhost:8000  │                      │
│                            └────────────────┘                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Pipeline Stages — Detailed Flow

### Stage 1: PDF Ingestion (`ingestion.py`)

**Input:** Path to a `.pdf` file  
**Output:** List of `{ page_number, text, section_heading }` dicts

```
PDF File
  │
  ├── For each page:
  │     │
  │     ├── Extract text via PyMuPDF (fitz)
  │     │
  │     ├── If text is empty → OCR fallback
  │     │     ├── Attempt 1: get_textpage_ocr(flags=0, full=True)
  │     │     └── Attempt 2: get_textpage_ocr(flags=TEXT_PRESERVE_WHITESPACE)
  │     │
  │     ├── Heading Detection (_detect_heading):
  │     │     ├── Analyze font sizes via get_text("dict")
  │     │     ├── Compute median font size across all spans
  │     │     ├── Score candidates:
  │     │     │     ├── Font size > 1.15× median → +ratio score
  │     │     │     ├── ALL-CAPS text → +10
  │     │     │     └── Numbered heading (e.g. "1.2.3 Title") → +15
  │     │     └── Return highest-scoring candidate (max 200 chars)
  │     │
  │     └── Emit { page_number, text, section_heading }
  │
  └── Return list of page dicts
```

**Key details:**
- OCR requires Tesseract to be installed on the system
- `section_heading` carries forward — if no heading detected on a page, the previous heading is used
- Empty pages (no text even after OCR) are skipped

---

### Stage 2: LLM Extraction (`llm.py` + `prompt.py`)

**Input:** Page text, document name, page number, section heading  
**Output:** List of raw rule dicts per page

```
Page Text
  │
  ├── Format prompt (EXTRACTION_PROMPT) with:
  │     ├── {document_name}
  │     ├── {section_heading}
  │     ├── {page_number}
  │     └── {text}
  │
  ├── Send to Groq API:
  │     ├── Model: qwen/qwen3-32b (configurable)
  │     ├── Temperature: 0.1 (near-deterministic)
  │     ├── Max tokens: 4,096
  │     ├── System message: "Safety Compliance Extraction Engine..."
  │     └── User message: formatted prompt
  │
  ├── Parse response:
  │     ├── Strip markdown fences (```json ... ```)
  │     ├── Bracket-match to find first JSON array [ ... ]
  │     └── json.loads() → list of rule dicts
  │
  ├── Post-extraction enforcement:
  │     ├── _enforce_categories():
  │     │     ├── Normalize "category" → "categories" (ensure list)
  │     │     ├── Check each category against ALLOWED_CATEGORIES
  │     │     └── Replace hallucinated categories with "general_safety"
  │     │
  │     └── Attach source metadata:
  │           ├── source_document = document_name
  │           ├── page_number = page_number
  │           └── section_heading = section_heading
  │
  └── Retry logic: up to 3 attempts on failure
```

**Prompt instructs the LLM to output:**
```json
[
  {
    "original_text": "exact quote from source",
    "actionable_rule": "Verb-first imperative rule",
    "category": "one of 12 allowed categories",
    "materials": ["material1", "material2"],
    "suggested_severity": 3
  }
]
```

**12 Allowed Categories:**
`electrical`, `chemical`, `woodworking`, `power_tools`, `heat_fire`, `mechanical`, `PPE_required`, `child_safety`, `toxic_exposure`, `ventilation`, `structural`, `general_safety`

**Severity Scale:**
| Level | Meaning |
|-------|---------|
| 1 | Informational — best practice, no immediate risk |
| 2 | Low — minor risk if ignored |
| 3 | Medium — moderate injury possible |
| 4 | High — serious injury likely |
| 5 | Critical — death or irreversible harm |

---

### Stage 3: Validation & Normalization (`validator.py`)

**Input:** List of raw rule dicts from LLM  
**Output:** Filtered, split, normalized rule dicts

```
Raw Rules
  │
  ├── Filter Vague Rules:
  │     └── Remove any rule whose actionable_rule contains
  │         vague phrases: "be careful", "use caution",
  │         "exercise care", "take precautions", "as needed",
  │         "when necessary", "if applicable", "as appropriate"
  │
  ├── Split Compound Rules (_split_compound_rule):
  │     ├── Parse with spaCy dependency tree
  │     ├── Find "and"/"or" conjunctions (cc dependency)
  │     ├── Check if conjunction joins two VERBs (not nouns)
  │     │     ├── If verb-conjoined: split into separate rules
  │     │     │   e.g. "Wear gloves and inspect equipment"
  │     │     │   → "Wear gloves" + "Inspect equipment"
  │     │     └── If noun-conjoined: keep together
  │     │         e.g. "Wear gloves and goggles" → no split
  │     └── Each split rule inherits parent's metadata
  │
  └── Normalize Verb (_normalize_verb):
        ├── Tokenize with spaCy
        ├── Skip leading adverbs/particles:
        │     POS tags: ADV, PART
        │     Lemmas: always, never, immediately, properly,
        │             carefully, regularly, not, do, only,
        │             strictly, continuously, thoroughly
        ├── Check first "real" token is a VERB
        │     ├── Yes → lemmatize it (e.g. "wearing" → "wear")
        │     └── No → discard the rule (returns None)
        └── Reconstruct: lemmatized_verb + rest of sentence
```

---

### Stage 4: Severity Override (`severity.py`)

**Input:** Validated rules  
**Output:** Rules with `validated_severity` field added

```
Validated Rules
  │
  ├── For each rule:
  │     ├── Combine actionable_rule + original_text
  │     ├── Normalize: lowercase, strip punctuation
  │     │
  │     ├── Match against SEVERITY_PATTERNS (in order):
  │     │
  │     │   Pattern 1 — toxic_fatal (force → 5):
  │     │     Matches: toxic gas, chlorine, carbon monoxide,
  │     │     cyanide, hydrogen sulfide, asbestos, fatal,
  │     │     death, immediately dangerous, IDLH
  │     │     → Always set severity = 5
  │     │
  │     │   Pattern 2 — electrical_hazard (floor → 4):
  │     │     Matches: high voltage, arc flash, live circuit,
  │     │     energized, lockout.tagout, electrocution
  │     │     → Set severity = max(current, 4)
  │     │
  │     │   Pattern 3 — ppe_mention (floor → 3):
  │     │     Matches: goggles, safety glasses, respirator,
  │     │     hard hat, helmet, face shield, gloves,
  │     │     hearing protection, steel.toe
  │     │     → Set severity = max(current, 3)
  │     │
  │     └── Set validated_severity (or copy suggested_severity if no match)
  │
  └── Return rules with validated_severity
```

---

### Stage 5: Embedding Generation (`embeddings.py`)

**Input:** Rules with text fields  
**Output:** Rules with `embedding` field (384-dim float vector)

```
Rules
  │
  ├── Collect all actionable_rule texts
  ├── Encode with sentence-transformers/all-MiniLM-L6-v2
  │     ├── Model: 22M parameters, 384-dim output
  │     ├── Batch encode for efficiency
  │     └── Normalize to unit vectors
  ├── Attach embedding list to each rule
  └── Return rules with embeddings
```

---

### Stage 6: Deduplication (`embeddings.py`)

**Input:** Rules with embeddings  
**Output:** Deduplicated rules (threshold: cosine similarity > 0.9)

```
Rules with Embeddings
  │
  ├── Stack all embeddings into matrix (N × 384)
  ├── Normalize rows to unit length
  ├── Compute cosine similarity matrix: S = E · Eᵀ (N × N)
  │
  ├── Greedy deduplication:
  │     For i in range(N):
  │       For j in range(i+1, N):
  │         If S[i][j] > threshold (0.9):
  │           Mark rule[j] for removal (keep earlier rule)
  │           Log: "Duplicate: 'rule_j' ≈ 'rule_i' (sim=0.95)"
  │
  ├── Remove marked rules
  └── Return deduplicated set
```

**Single-doc vs. Batch mode:**
- **Single-doc** (`process_document`): dedup within one PDF only
- **Batch** (`process_batch`): all PDFs extracted first, then **global dedup** across the entire corpus — eliminates cross-document duplicates

---

### Stage 7: JSON Output (`service.py`)

**Output format:**
```json
{
  "extraction_timestamp": "2026-02-28T12:48:12+00:00",
  "model_used": "qwen/qwen3-32b",
  "total_pages": 450,
  "rule_count": 738,
  "document_name": "batch",
  "source_documents": ["doc1.pdf", "doc2.pdf", "..."],
  "document_count": 23,
  "rules": [
    {
      "rule_id": "uuid-v4",
      "original_text": "exact quote from source PDF",
      "actionable_rule": "wear safety goggles when operating grinding equipment",
      "materials": ["safety goggles", "grinding equipment"],
      "suggested_severity": 3,
      "validated_severity": 4,
      "categories": ["PPE_required"],
      "source_document": "OSHA 1910.133",
      "page_number": 5,
      "section_heading": "EYE AND FACE PROTECTION",
      "embedding": [0.025, 0.041, -0.065, "...(384 floats)"]
    }
  ]
}
```

---

### Stage 8: Database Migration (`migrate.py` → `db.py` → `schema.sql`)

```
JSON Output File
  │
  ├── init_schema():
  │     ├── CREATE EXTENSION IF NOT EXISTS vector
  │     ├── CREATE TABLE safety_rules (
  │     │     id SERIAL PRIMARY KEY,
  │     │     rule_id UUID UNIQUE,
  │     │     original_text TEXT,
  │     │     actionable_rule TEXT,
  │     │     materials TEXT[],
  │     │     suggested_severity INT (1-5),
  │     │     validated_severity INT (1-5),
  │     │     categories TEXT[],
  │     │     source_document TEXT,
  │     │     page_number INT,
  │     │     section_heading TEXT,
  │     │     embedding vector(384),
  │     │     created_at TIMESTAMPTZ
  │     │   )
  │     ├── CREATE TABLE extraction_runs (metadata tracking)
  │     └── CREATE INDEXES:
  │           ├── GIN on categories (array containment)
  │           ├── B-tree on validated_severity DESC
  │           ├── B-tree on source_document
  │           └── IVFFlat on embedding (vector_cosine_ops)
  │
  ├── Insert extraction_runs metadata
  │
  └── Batch insert rules:
        ├── execute_values() with page_size=100
        ├── Convert embedding array → pgvector string "[0.1,0.2,...]"
        └── ON CONFLICT (rule_id) DO NOTHING (idempotent)
```

**Database:** PostgreSQL + pgvector on Supabase (Session Pooler, port 6543)

---

### Stage 9: Web Viewer (`webapp.py` + templates)

```
FastAPI Server (localhost:8000)
  │
  ├── GET / — Rules Table
  │     ├── Filters: category, severity, document, text search
  │     ├── Pagination: 50 rules/page
  │     ├── Sorted by: validated_severity DESC, source_document, page_number
  │     ├── Display: rule text, original text (truncated),
  │     │   severity badge (colored circle), category pills,
  │     │   materials list, source info (doc + page + heading)
  │     └── Template: templates/index.html
  │
  └── GET /stats — Dashboard
        ├── Total rules count (hero number)
        ├── Rules by Document (horizontal bar chart)
        ├── Rules by Category (horizontal bar chart + pills)
        ├── Rules by Severity (horizontal bar chart + colored badges)
        └── Template: templates/stats.html
```

---

## CLI Commands Reference

```bash
# Extract from a single PDF
python -m src input/document.pdf

# Extract from all PDFs in a directory (batch mode + global dedup)
python -m src input/

# Custom output path and model
python -m src input/ --output results.json --model llama-3.3-70b-versatile

# Adjust dedup threshold (lower = more aggressive dedup)
python -m src input/ --threshold 0.85

# Migrate JSON results to PostgreSQL
python -m src.migrate output/batch_23_docs_20260228_184812.json

# Launch web viewer
python -m src.webapp
# Opens at http://localhost:8000
```

---

## Data Flow Summary

```
  PDF Files (input/)
       │
       ▼
  ┌──────────┐     ┌──────────┐     ┌────────────┐     ┌──────────┐
  │ PyMuPDF  │────▶│ Groq LLM │────▶│ spaCy NLP  │────▶│ Regex    │
  │ Ingest   │     │ Extract  │     │ Validate   │     │ Severity │
  └──────────┘     └──────────┘     └────────────┘     └──────────┘
                                                             │
       ┌─────────────────────────────────────────────────────┘
       ▼
  ┌──────────────┐     ┌──────────┐     ┌────────┐     ┌──────────┐
  │ Sentence     │────▶│ Cosine   │────▶│ JSON   │────▶│ Postgres │
  │ Transformers │     │ Dedup    │     │ Output │     │ pgvector │
  │ Embed        │     │ (>0.9)   │     │        │     │          │
  └──────────────┘     └──────────┘     └────────┘     └──────────┘
                                                             │
                                                             ▼
                                                       ┌──────────┐
                                                       │ FastAPI  │
                                                       │ Viewer   │
                                                       │ :8000    │
                                                       └──────────┘
```

---

## Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| PDF Parsing | PyMuPDF (fitz) | Text extraction + OCR fallback |
| LLM | Groq API (qwen/qwen3-32b) | Structured rule extraction |
| NLP | spaCy (en_core_web_sm) | POS tagging, dependency parsing, lemmatization |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) | 384-dim semantic vectors |
| Database | PostgreSQL + pgvector (Supabase) | Storage + vector similarity search |
| Web Server | FastAPI + Jinja2 + Uvicorn | HTML viewer with filters |
| Environment | python-dotenv | API key and DB credential management |
