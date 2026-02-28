# Safety Rule Extraction Service

Modular Python package that ingests safety documents (PDFs, including scanned),
extracts atomic actionable safety rules via **Groq** ( qwen/qwen3-32b),
validates/normalises/deduplicates them, and writes structured JSON output.



## Setup

```bash
cd safety-extraction

# Create virtual environment
python -m venv .venv

# Activate
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Download spaCy language model
python -m spacy download en_core_web_sm

# Configure API key
cp .env.example .env
# Edit .env and add your Groq API key (https://console.groq.com/keys)
```

## Usage

### Single PDF

```bash
python -m src input/safety-manual.pdf
```

### Directory of PDFs

```bash
python -m src input/
```

### Custom output path

```bash
python -m src input/sds.pdf --output output/sds-rules.json
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--model` | `qwen/qwen3-32b` | Groq model to use |
| `--threshold` | `0.9` | Cosine similarity threshold for deduplication |
| `--output` / `-o` | `output/<name>_<timestamp>.json` | Output file path |

### Programmatic Usage

```python
from src import SafetyRuleExtractionService

service = SafetyRuleExtractionService(groq_api_key="gsk_...")
rules = service.process_document("input/safety-manual.pdf")
service.save_results(rules, "output/rules.json", document_name="safety-manual")
```

## Output Format

```json
{
  "document_name": "safety-manual",
  "extraction_timestamp": "2026-02-28T12:00:00+00:00",
  "model_used": "qwen/qwen3-32b",
  "total_pages": 24,
  "rule_count": 87,
  "rules": [
    {
      "rule_id": "a1b2c3d4-...",
      "original_text": "Always wear safety goggles when operating the grinder.",
      "actionable_rule": "Wear safety goggles when operating the grinder.",
      "source_document": "safety-manual",
      "page_number": 3,
      "section_heading": "PERSONAL PROTECTIVE EQUIPMENT",
      "categories": ["PPE_required", "power_tools"],
      "materials": ["safety goggles", "grinder"],
      "suggested_severity": 2,
      "validated_severity": 3,
      "embedding": [0.012, -0.034, ...]
    }
  ]
}
```

## Pipeline

1. **Ingest PDF** — text extraction via PyMuPDF; OCR fallback for scanned pages
2. **Detect headings** — font size analysis, ALL-CAPS, numbered patterns
3. **Extract rules** — structured prompt to Groq  with strict JSON parsing
4. **Validate** — verb-first check (adverb-skipping), vague rule filtering
5. **Split compounds** — dependency parsing to split verb-conjoined clauses
6. **Override severity** — deterministic regex-based keyword matching
7. **Generate embeddings** — all-MiniLM-L6-v2 (384-dim, computed once)
8. **Deduplicate** — cosine similarity > 0.9 removal
9. **Output** — JSON with metadata envelope

## Allowed Categories

`electrical` · `chemical` · `woodworking` · `power_tools` · `heat_fire` · `mechanical` · `PPE_required` · `child_safety` · `toxic_exposure` · `ventilation` · `structural` · `general_safety`

## Severity Scale

| Level | Meaning |
|---|---|
| 1 | Minor injury risk |
| 2 | Moderate injury risk |
| 3 | Serious injury risk |
| 4 | Life-threatening hazard |
| 5 | Extreme/fatal risk |

## Logs

Logs are written to both console and `extraction.log` in this directory.
