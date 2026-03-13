-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- Safety rules table
CREATE TABLE IF NOT EXISTS safety_rules (
    id                  SERIAL PRIMARY KEY,
    rule_id             UUID NOT NULL UNIQUE,
    original_text       TEXT NOT NULL,
    actionable_rule     TEXT NOT NULL,
    materials           TEXT[] DEFAULT '{}',
    suggested_severity  INTEGER CHECK (suggested_severity BETWEEN 1 AND 5),
    validated_severity  INTEGER CHECK (validated_severity BETWEEN 1 AND 5),
    categories          TEXT[] DEFAULT '{}',
    source_document     TEXT NOT NULL,
    page_number         INTEGER,
    section_heading     TEXT DEFAULT 'Unknown Section',
    embedding           vector(384),
    run_id              INTEGER,
    created_at          TIMESTAMPTZ DEFAULT now()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_rules_categories  ON safety_rules USING GIN (categories);
CREATE INDEX IF NOT EXISTS idx_rules_severity    ON safety_rules (validated_severity DESC);
CREATE INDEX IF NOT EXISTS idx_rules_document    ON safety_rules (source_document);
CREATE INDEX IF NOT EXISTS idx_rules_rule_id     ON safety_rules (rule_id);
CREATE INDEX IF NOT EXISTS idx_rules_run_id      ON safety_rules (run_id);

-- Vector similarity index (IVFFlat — good for up to ~100k rows)
CREATE INDEX IF NOT EXISTS idx_rules_embedding
    ON safety_rules USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);

-- Extraction runs table
CREATE TABLE IF NOT EXISTS extraction_runs (
    id                  SERIAL PRIMARY KEY,
    run_timestamp       TIMESTAMPTZ NOT NULL,
    model_used          TEXT,
    total_pages         INTEGER,
    rule_count          INTEGER,
    document_count      INTEGER,
    source_documents    TEXT[],
    json_source_file    TEXT,
    file_url            TEXT,
    evaluation_results  JSONB,
    created_at          TIMESTAMPTZ DEFAULT now()
);

-- Add FK after both tables exist (idempotent — safe to re-run)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'fk_rules_run'
          AND table_name = 'safety_rules'
    ) THEN
        ALTER TABLE safety_rules
            ADD CONSTRAINT fk_rules_run
            FOREIGN KEY (run_id) REFERENCES extraction_runs(id);
    END IF;
END $$;

-- Completed scans table (scan history)
CREATE TABLE IF NOT EXISTS completed_scans (
    id              SERIAL PRIMARY KEY,
    video_id        TEXT NOT NULL,
    video_url       TEXT,
    title           TEXT NOT NULL,
    channel         TEXT,
    verdict         TEXT,
    risk_score      REAL,
    output_json     JSONB,
    model_reports   JSONB,
    comparison_data JSONB,
    scan_timestamp  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_scans_video_id ON completed_scans (video_id);
CREATE INDEX IF NOT EXISTS idx_scans_timestamp ON completed_scans (scan_timestamp DESC);

-- Evaluation results table (per-file evaluation, linked to extraction_runs)
CREATE TABLE IF NOT EXISTS evaluation_results (
    id                          SERIAL PRIMARY KEY,
    run_id                      INTEGER NOT NULL REFERENCES extraction_runs(id),
    file_name                   TEXT NOT NULL,
    total_rules                 INTEGER DEFAULT 0,
    text_presence_passed        INTEGER DEFAULT 0,
    text_presence_total         INTEGER DEFAULT 0,
    page_accuracy_passed        INTEGER DEFAULT 0,
    page_accuracy_total         INTEGER DEFAULT 0,
    heading_accuracy_passed     INTEGER DEFAULT 0,
    heading_accuracy_total      INTEGER DEFAULT 0,
    category_validity_passed    INTEGER DEFAULT 0,
    category_validity_total     INTEGER DEFAULT 0,
    severity_consistency_passed INTEGER DEFAULT 0,
    severity_consistency_total  INTEGER DEFAULT 0,
    hallucination_rate          REAL,
    correctness_score           REAL,
    overall_accuracy            REAL,
    failed_rules                JSONB,
    created_at                  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_eval_run_id ON evaluation_results (run_id);
