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

-- Add FK after both tables exist
ALTER TABLE safety_rules
    ADD CONSTRAINT IF NOT EXISTS fk_rules_run
    FOREIGN KEY (run_id) REFERENCES extraction_runs(id);

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
